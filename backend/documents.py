"""Document extraction for the PDF / PowerPoint / Word pipeline.

The video pipeline turns speech into timestamped segments; this turns pages into
page-numbered segments, so the same index, the same retrieval and the same chat
can answer about a handout with `p. 12` citations instead of `12:40`.

Deliberately dependency-light: pypdf for PDF text, python-pptx and python-docx
for the Office formats. Scanned PDF pages have no text layer at all, so their
embedded images are handed to the same Groq vision call the frame OCR already
uses -- no PDF renderer (and no AGPL library) is needed for that.

Output shape, identical for every format:

    {"kind": "pdf", "page_count": 12,
     "pages": [{"page": 1, "heading": "Εισαγωγή", "text": "..."}, ...]}
"""

import base64
import io
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# A chunk is what one embedding covers. Long enough to hold a full explanation,
# short enough that a single citation still points at something specific.
CHUNK_CHARS = 1100
CHUNK_OVERLAP = 150

# Pages with less text than this are treated as scanned and sent to OCR.
_SCANNED_PAGE_CHARS = 40
# Vision calls are the slow, paid part; cap how many a single document may OCR.
_MAX_OCR_PAGES = 15

SUPPORTED_EXTENSIONS = {".pdf", ".pptx", ".docx"}

# --- Google Document AI (optional) -------------------------------------------
# pypdf reads a text layer; it cannot read a scan at all, and what it returns is
# one flat string per page. Document AI returns the page as structure -- text
# blocks in reading order, with their bounding boxes -- for $1.50 per 1,000
# pages (first 1,000 free every month). It is used for PDFs only, and only when
# credentials and a processor are configured: without them this module behaves
# exactly as it did before, which keeps the pipeline deployable without a GCP
# project.
#
# The online :process endpoint accepts at most 15 pages / 20 MB per call, so a
# longer handout is cut into 14-page pieces with pypdf, sent one at a time, and
# the page texts are stitched back together in order.

DOCUMENT_AI_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or ""
DOCUMENT_AI_PROJECT = os.getenv("DOCUMENT_AI_PROJECT") or ""
DOCUMENT_AI_LOCATION = os.getenv("DOCUMENT_AI_LOCATION", "eu")
DOCUMENT_AI_PROCESSOR = os.getenv("DOCUMENT_AI_PROCESSOR_ID") or ""
DOCUMENT_AI_MAX_PAGES = 14
DOCUMENT_AI_MAX_BYTES = 19 * 1024 * 1024
# How many of those pieces fly at once. The processor quota is 120 requests per
# minute; latency per request is ~7s, so three concurrent calls turn a 3-piece
# handout from ~21s into ~8s.
DOCUMENT_AI_CONCURRENCY = int(os.getenv("DOCUMENT_AI_CONCURRENCY", "3") or "3")

_documentai_token = None
_documentai_token_expiry = 0.0
_documentai_lock = threading.Lock()


def documentai_available() -> bool:
    """True only when a processor and usable credentials are both configured."""
    return bool(
        DOCUMENT_AI_CREDENTIALS
        and DOCUMENT_AI_PROCESSOR
        and os.path.exists(DOCUMENT_AI_CREDENTIALS)
    )


def _documentai_project() -> str:
    if DOCUMENT_AI_PROJECT:
        return DOCUMENT_AI_PROJECT
    with open(DOCUMENT_AI_CREDENTIALS, "r", encoding="utf-8") as handle:
        return json.load(handle)["project_id"]


def _documentai_access_token() -> str:
    """OAuth token for the service account, cached until just before it expires."""
    global _documentai_token, _documentai_token_expiry
    with _documentai_lock:
        if _documentai_token and time.time() < _documentai_token_expiry - 60:
            return _documentai_token
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account

        credentials = service_account.Credentials.from_service_account_file(
            DOCUMENT_AI_CREDENTIALS,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        credentials.refresh(Request())
        _documentai_token = credentials.token
        expiry = credentials.expiry.timestamp() if credentials.expiry else time.time() + 3000
        _documentai_token_expiry = expiry
        return _documentai_token


def _anchored_text(full_text: str, layout: dict) -> str:
    """The slice of the document text a layout block points at."""
    anchor = (layout or {}).get("textAnchor") or {}
    parts = []
    for segment in anchor.get("textSegments") or []:
        start = int(segment.get("startIndex", 0) or 0)
        end = int(segment.get("endIndex", 0) or 0)
        if end > start:
            parts.append(full_text[start:end])
    return _clean("".join(parts))


def _documentai_process(pdf_bytes: bytes, first_page: int) -> list:
    """One :process call for a ≤14-page PDF piece."""
    import requests

    project = _documentai_project()
    url = (
        f"https://{DOCUMENT_AI_LOCATION}-documentai.googleapis.com/v1/projects/"
        f"{project}/locations/{DOCUMENT_AI_LOCATION}/processors/{DOCUMENT_AI_PROCESSOR}:process"
    )
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {_documentai_access_token()}",
            "Content-Type": "application/json",
        },
        json={
            "rawDocument": {
                "content": base64.b64encode(pdf_bytes).decode("ascii"),
                "mimeType": "application/pdf",
            }
        },
        timeout=300,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Document AI HTTP {response.status_code}: {response.text[:300]}")

    document = response.json().get("document") or {}
    full_text = document.get("text") or ""
    pages = []
    for index, page in enumerate(document.get("pages") or [], start=first_page):
        # Paragraphs, in reading order, give the page back its shape; a page with
        # no paragraph anchors falls back to the whole page block.
        blocks = [
            _anchored_text(full_text, paragraph.get("layout"))
            for paragraph in page.get("paragraphs") or []
        ]
        text = "\n\n".join(block for block in blocks if block).strip()
        if not text:
            text = _anchored_text(full_text, page.get("layout"))
        if not text:
            continue
        pages.append({"page": index, "heading": _heading_for(text), "text": text})
    return pages


def extract_pdf_documentai(path: Path, image_ocr=None) -> dict:
    """Read a PDF through Document AI, splitting it to fit the online endpoint."""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(path))
    total = len(reader.pages)

    # Build every piece first, then send them concurrently: each request carries
    # ~7 seconds of latency and a handout usually needs two or three, which used
    # to run back to back. The processor allows 120 requests per minute, so three
    # in flight at once is well inside the quota.
    pieces = []
    for start in range(0, total, DOCUMENT_AI_MAX_PAGES):
        writer = PdfWriter()
        for page in reader.pages[start : start + DOCUMENT_AI_MAX_PAGES]:
            writer.add_page(page)
        buffer = io.BytesIO()
        writer.write(buffer)
        payload = buffer.getvalue()
        if len(payload) > DOCUMENT_AI_MAX_BYTES:
            raise RuntimeError(
                f"pages {start + 1}-{start + DOCUMENT_AI_MAX_PAGES} exceed the 20 MB limit"
            )
        pieces.append((start + 1, payload))

    pages = []
    if pieces:
        with ThreadPoolExecutor(max_workers=min(DOCUMENT_AI_CONCURRENCY, len(pieces))) as pool:
            futures = [
                pool.submit(_documentai_process, payload, first_page=first_page)
                for first_page, payload in pieces
            ]
            # Results come back in submission order, so the pages stay in order.
            for future in futures:
                pages.extend(future.result())

    if not pages:
        raise RuntimeError("Document AI returned no text")
    return {"kind": "pdf", "page_count": total, "pages": pages}


def _clean(text: str) -> str:
    """Collapse the whitespace a PDF extractor scatters through a paragraph."""
    text = str(text or "").replace("\x00", " ")
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if not (3 <= len(stripped) <= 80):
        return False
    if stripped.endswith((".", ",", ";", ":")):
        return False
    letters = [c for c in stripped if c.isalpha()]
    if len(letters) < 3:
        return False
    # Short, unpunctuated, mostly-capitalised lines are headings in practice.
    return stripped.isupper() or stripped.istitle()


def _heading_for(text: str) -> str | None:
    for line in text.splitlines()[:6]:
        if _looks_like_heading(line):
            return line.strip()
    return None


def extract_pdf(path: Path, image_ocr=None) -> dict:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = []
    ocr_budget = _MAX_OCR_PAGES

    for index, page in enumerate(reader.pages, start=1):
        try:
            text = _clean(page.extract_text() or "")
        except Exception:
            text = ""

        # No text layer: it is a scan. Ask vision to read the page image instead,
        # which is the only way a scanned handout becomes searchable at all.
        if len(text) < _SCANNED_PAGE_CHARS and image_ocr and ocr_budget > 0:
            try:
                for image in list(page.images)[:1]:
                    data = image.data
                    suffix = (Path(getattr(image, "name", "") or "x.png").suffix or ".png").lower()
                    mime = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"
                    if data and len(data) > 2048:
                        recognised = _clean(image_ocr(data, mime) or "")
                        if recognised:
                            text = recognised
                            ocr_budget -= 1
                            print(f"[Docs] page {index}: scanned, OCR recovered {len(text)} chars")
                            break
            except Exception as error:
                print(f"[Docs] page {index}: OCR skipped ({error})")

        if not text:
            continue
        pages.append({"page": index, "heading": _heading_for(text), "text": text})

    return {"kind": "pdf", "page_count": len(reader.pages), "pages": pages}


def extract_pptx(path: Path) -> dict:
    from pptx import Presentation

    presentation = Presentation(str(path))
    pages = []

    for index, slide in enumerate(presentation.slides, start=1):
        blocks = []
        for shape in slide.shapes:
            if not getattr(shape, "has_text_frame", False):
                continue
            text = _clean(shape.text_frame.text)
            if text:
                blocks.append(text)

        # Speaker notes usually carry what the presenter actually explains, so
        # they belong in the index next to the slide's own text.
        try:
            if slide.has_notes_slide:
                notes = _clean(slide.notes_slide.notes_text_frame.text)
                if notes:
                    blocks.append(f"Speaker notes:\n{notes}")
        except Exception:
            pass

        text = "\n\n".join(blocks).strip()
        if not text:
            continue

        first_block = blocks[0] if blocks else ""
        heading = _heading_for(first_block) or (first_block.splitlines()[0][:80] if first_block else None)
        pages.append({"page": index, "heading": heading, "text": text})

    return {"kind": "pptx", "page_count": len(presentation.slides), "pages": pages}


def extract_docx(path: Path) -> dict:
    from docx import Document

    document = Document(str(path))
    blocks = []
    for paragraph in document.paragraphs:
        text = _clean(paragraph.text)
        if not text:
            continue
        style = (getattr(paragraph.style, "name", "") or "").lower()
        if "heading" in style:
            blocks.append(f"## {text}")
        else:
            blocks.append(text)

    # A Word file has no fixed pages, so pages are synthesised from paragraph
    # runs: roughly one screen of text per unit, splitting between blocks so a
    # sentence never gets cut in half.
    pages = []
    buffer = []
    length = 0
    page_number = 1
    for block in blocks:
        buffer.append(block)
        length += len(block)
        if length >= 2600:
            text = "\n\n".join(buffer)
            pages.append({"page": page_number, "heading": _heading_for(text), "text": text})
            page_number += 1
            buffer = []
            length = 0
    if buffer:
        text = "\n\n".join(buffer)
        pages.append({"page": page_number, "heading": _heading_for(text), "text": text})

    return {"kind": "docx", "page_count": len(pages), "pages": pages}


def extract_figure_images(
    path: Path,
    max_pages: int = 12,
    min_bytes: int = 3_500,
    max_side: int = 1400,
) -> list:
    """The largest embedded image of each page, for the figure reader.

    Text extraction drops every figure: a tree, a graph or a table drawn on the
    page is not text, so a question about "the tree in Figure 14" has nothing to
    stand on. Each page's biggest image is handed to vision once at ingest, and
    its description is indexed as a `[figure p.N]` chunk.

    The size floor is deliberately low: a simple line drawing of a tree compresses
    to a few kilobytes, and those are exactly the figures worth reading. Capped on
    pages because vision calls are the slow, paid part.
    """
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    figures = []
    for index, page in enumerate(reader.pages, start=1):
        if index > max_pages:
            break
        try:
            images = list(page.images)
        except Exception:
            continue
        if not images:
            continue

        best = None
        best_size = 0
        for image in images:
            try:
                size = len(image.data or b"")
            except Exception:
                continue
            if size > best_size:
                best, best_size = image, size
        if best is None:
            continue
        if best_size < min_bytes:
            print(f"[Docs] page {index}: image {best_size} bytes, too small to read")
            continue

        suffix = (Path(getattr(best, "name", "") or "figure.png").suffix or ".png").lower()
        mime = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"
        data = best.data

        # Downscale before the vision call. A scanned page arrives at 2000px+ and
        # the reader gains nothing from that: a smaller JPEG is fewer tokens, less
        # upload time and less memory while several uploads run at once.
        try:
            import io

            from PIL import Image

            with Image.open(io.BytesIO(data)) as image:
                if max(image.size) > max_side:
                    image.thumbnail((max_side, max_side))
                buffer = io.BytesIO()
                image.convert("RGB").save(buffer, format="JPEG", quality=82, optimize=True)
                shrunk = buffer.getvalue()
                if len(shrunk) < len(data):
                    data, mime = shrunk, "image/jpeg"
        except Exception:
            pass

        try:
            figures.append({"page": index, "data": data, "mime": mime})
            print(f"[Docs] page {index}: figure {len(data)} bytes ({mime})")
        except Exception:
            continue

    return figures


def extract_document(path: Path, file_name: str = "", image_ocr=None) -> dict:
    """Dispatch on the extension. Raises ValueError for anything unsupported."""
    suffix = Path(file_name or path.name).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"unsupported document type '{suffix or 'unknown'}': "
            f"expected one of {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    if suffix == ".pdf":
        if documentai_available():
            try:
                result = extract_pdf_documentai(path, image_ocr=image_ocr)
                print(
                    f"[Docs] Document AI read {result['page_count']} pages, "
                    f"{sum(len(p['text']) for p in result['pages'])} chars"
                )
            except Exception as error:
                # The OCR branch must never cost an upload: pypdf still works on
                # any PDF that carries a text layer.
                print(f"[Docs] Document AI failed ({error}); falling back to pypdf")
                result = extract_pdf(path, image_ocr=image_ocr)
        else:
            result = extract_pdf(path, image_ocr=image_ocr)
    elif suffix == ".pptx":
        result = extract_pptx(path)
    else:
        result = extract_docx(path)

    if not result["pages"]:
        raise ValueError("no readable text found in this document")

    for page in result["pages"]:
        page["page"] = int(page["page"])
    result["pages"].sort(key=lambda item: item["page"])
    return result


def chunk_pages(pages: list, chunk_chars: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list:
    """Split each page into overlapping windows that keep their page number.

    The heading is prefixed to every chunk: retrieval matches on it, and without
    it a chunk from the middle of a section answers with no idea what section it
    came from.
    """
    chunks = []

    for page in pages:
        page_number = int(page["page"])
        heading = page.get("heading")
        text = _clean(page.get("text") or "")
        if not text:
            continue

        start = 0
        while start < len(text):
            end = min(start + chunk_chars, len(text))
            piece = text[start:end]
            if end < len(text):
                # Break on the last sentence boundary so a chunk does not stop
                # mid-sentence; fall back to the hard cut when there is none.
                boundary = max(piece.rfind(". "), piece.rfind("\n"), piece.rfind("; "))
                if boundary > chunk_chars * 0.5:
                    piece = piece[: boundary + 1]
                    end = start + boundary + 1

            body = piece.strip()
            if body:
                label = f"[p.{page_number}{' | ' + heading if heading else ''}] "
                chunks.append(
                    {
                        "text": label + body,
                        "page": page_number,
                        "heading": heading,
                    }
                )

            if end >= len(text):
                break
            start = max(end - overlap, start + 1)

    return chunks
