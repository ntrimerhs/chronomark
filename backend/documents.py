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

import io
import re
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
