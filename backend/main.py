from fastapi import FastAPI, Request, UploadFile, BackgroundTasks, Form, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from pathlib import Path
import os
import re
import shutil
import tempfile
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from fastapi.staticfiles import StaticFiles
from video_processing import extract_audio
from video_processing import _probe_duration_seconds
from video_processing import extract_frames, extract_frame_at, normalize_video
import cloudflare_media
import cloudflare_stream
from whisper import (
    can_transcribe_directly,
    transcribe_audio_chunks,
    transcribe_media_direct,
)
import base64
import asyncio
import json
import math
import uuid
import jobs as job_store
from bert import create_embeddings_from_transcript, embed_query, warm_up as warm_text_model
from qdrant_store import ensure_collections, store_text_embeddings, clear_collections
from qdrant_store import client, TEXT_COLLECTION, FRAME_COLLECTION, search_text, scroll_all_text
from qdrant_client import models as qmodels
import metrics
import auth_guard

from llama import (
    ask_llama,
    ask_document,
    ChapterMarkerStream,
    complete_with_continuation,
    split_chapter_marker,
    suggest_title,
    suggest_title_from_text,
    describe_figure,
    digest_segment,
    document_flashcards,
    document_notes,
    document_quiz,
    document_chapters,
    extract_examples,
    map_examples_to_excerpts,
    transcribe_image,
)

import documents as document_tools

from pydantic import BaseModel
import sys

import conversations
from services import r2_service
from services import user_scope
from services import video_registry
import compliance
from services.r2_service import (
    generate_presigned_download_url,
    generate_presigned_upload_url,
)

# Progress output uses ✓ / ✗ / ↻ / ⏱. A non-interactive Windows process gets a
# cp1252 stdout, where printing any of those raises UnicodeEncodeError -- and
# since those prints sit inside the pipeline's try blocks, the encoding error
# was being reported as a processing failure. Reconfigure once, here, so a
# progress line can never fail a job.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

class Question(BaseModel):
    question: str
    video_id: str | None = None
    conversation_id: str | None = None
    # Prior conversation turns as [{"role": "user"|"assistant", "content": str}, ...],
    # oldest first. Optional -- lets the LLM handle follow-up questions
    # ("what about that?") instead of treating every question in isolation.
    history: list[dict] | None = None


def _detect_question_language(text: str) -> str:
    """Return the answer language expected by the user.

    Greek-script input gets a Greek answer; everything else defaults to English.
    """
    if any("\u0370" <= char <= "\u03ff" or "\u1f00" <= char <= "\u1fff" for char in text):
        return "Greek"
    return "English"


def _detect_transcript_language(text: str) -> str:
    """Prefer Greek when the transcript contains Greek script."""
    if any("\u0370" <= char <= "\u03ff" or "\u1f00" <= char <= "\u1fff" for char in text):
        return "Greek"
    return "English"


def _is_summary_request(text: str) -> bool:
    lowered = text.lower()
    return any(
        phrase in lowered
        for phrase in (
            "summarize",
            "summary",
            "overview",
            "what is this video about",
            "τι δείχνει",
            "περίληψη",
            "σύνοψη",
        )
    )


def _is_chapter_continue(text: str) -> bool:
    """A reader asking for the next chapter, not a new topic.

    The answer has to start where the last one stopped, so it needs the whole
    document in front of the model and the previous chapter in the history.
    """
    lowered = (text or "").lower().strip()
    if len(lowered) > 90:
        return False
    return any(
        phrase in lowered
        for phrase in (
            "continue",
            "go on",
            "carry on",
            "next chapter",
            "next section",
            "keep going",
            "συνέχισε",
            "συνεχισε",
            "συνέχεια",
            "συνεχεια",
            "συνέχισέ",
            "συνεχισε παρακαλω",
            "επόμενο κεφάλαιο",
            "επομενο κεφαλαιο",
            "παρακάτω",
            "παρακατω",
            "προχώρα",
            "προχωρα",
        )
    )


def _summary_query_for_language(language: str) -> str:
    if language == "Greek":
        return "δώσε μια περίληψη του βίντεο με τα βασικά σημεία"
    return "give a summary of the video with the main points"


def _expand_with_neighbors(candidates, all_segments, window=1):
    """Pull in each matched segment's immediate chronological neighbors.

    Semantic search scores each transcript segment independently, but a
    coherent explanation (e.g. walking through an automaton's states, or a
    data structure's operations) is often spread across several consecutive
    segments where only one or two individually score high enough to be
    retrieved. Without their neighbors, the LLM only sees isolated sentences
    and has to guess at the missing states/transitions -- expanding the
    context to include what comes immediately before/after each match keeps
    the example grounded in what the video actually says.
    """
    if not all_segments:
        return candidates

    id_to_index = {seg.id: i for i, seg in enumerate(all_segments)}
    selected_indices = set()

    for cand in candidates:
        idx = id_to_index.get(cand.id)
        if idx is None:
            continue
        for offset in range(-window, window + 1):
            neighbor_idx = idx + offset
            if 0 <= neighbor_idx < len(all_segments):
                selected_indices.add(neighbor_idx)

    if not selected_indices:
        return candidates

    return [all_segments[i] for i in sorted(selected_indices)]


_INLINE_TIMESTAMP_RE = re.compile(r"`(\d{1,2}):(\d{2})`")


_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _bm25_scores(question: str, points) -> dict:
    """BM25 over the video's own segments.

    Vector similarity cannot separate "the string example" from "the integer
    example": each such segment is prose saying "another example, I declare a
    variable", and the words that distinguish them are rare. BM25 weights
    exactly those rare terms -- "string.py", "is_pretty", "number1".
    """
    def tokenize(text):
        return [t for t in _TOKEN_RE.findall((text or "").lower()) if len(t) >= 2]

    docs = []
    for point in points:
        payload = getattr(point, "payload", None) or {}
        docs.append((str(point.id), tokenize(payload.get("text"))))
    if not docs:
        return {}

    total = len(docs)
    average_len = sum(len(tokens) for _, tokens in docs) / max(total, 1)

    document_frequency = {}
    for _, tokens in docs:
        for term in set(tokens):
            document_frequency[term] = document_frequency.get(term, 0) + 1

    scores = {}
    for point_id, tokens in docs:
        if not tokens:
            continue
        score = 0.0
        for term in tokenize(question):
            frequency = document_frequency.get(term)
            if not frequency:
                continue
            idf = math.log(1 + (total - frequency + 0.5) / (frequency + 0.5))
            appearances = tokens.count(term)
            if not appearances:
                continue
            k1, b = 1.5, 0.75
            denominator = appearances + k1 * (1 - b + b * len(tokens) / average_len)
            score += idf * (appearances * (k1 + 1)) / denominator
        if score > 0:
            scores[point_id] = score
    return scores


class _Ranked:
    """Minimal stand-in for a Qdrant scored point."""

    __slots__ = ("id", "payload", "score")

    def __init__(self, point_id, payload, score):
        self.id = point_id
        self.payload = payload
        self.score = score


def _quote_time(quote: str, words, min_match: float = 0.55):
    """Exact start time of a quoted phrase, found in the word stream.

    Token-set overlap over a sliding window, so a quote survives Whisper's
    punctuation and casing without needing an exact string match.
    """
    if not quote or not words:
        return None

    wanted = [t for t in _TOKEN_RE.findall(str(quote).lower()) if len(t) >= 2]
    if not wanted:
        return None

    windows = []
    for word in words:
        windows.append(set(t for t in _TOKEN_RE.findall(str(word.get("w") or "").lower()) if len(t) >= 2))
    if len(windows) < len(wanted):
        return None

    wanted_set = set(wanted)
    best_start = None
    best_score = 0.0
    span = len(wanted)
    for index in range(len(windows) - span + 1):
        combined = set()
        for part in windows[index:index + span]:
            combined |= part
        if not combined:
            continue
        score = len(wanted_set & combined) / len(wanted_set)
        if score > best_score:
            best_score = score
            best_start = words[index].get("start")

    if best_score < min_match or best_start is None:
        return None
    return float(best_start)


def _transcript_words(video_id=None):
    """Word timings for the current video, or [] when unavailable."""
    if not TRANSCRIPTS_PATH.exists():
        return []
    try:
        with open(TRANSCRIPTS_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    return data.get("words") or []


_EXAMPLE_BLOCK_RE = re.compile(
    r"(?i)(?=^[^\n]*?(?:Παράδειγμα|ΠΑΡΑΔΕΙΓΜΑ|Example)\s*\d*)", re.MULTILINE
)


_OCR_EXAMPLE_RE = re.compile(
    r"(?i)(?:Παράδειγμα|Example)\s*\d|string\.py|integer\.py|float\.py|boolean\.py"
)


def _mmss(seconds) -> str:
    try:
        total = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        return "0:00"
    return f"{total // 60}:{total % 60:02d}"


def _excerpt_time(label: str, segments):
    """Turn an excerpt label into the real segment start it refers to."""
    if not label or not segments:
        return None
    match = re.match(r"\s*(\d{1,2}):(\d{2})", label)
    if not match:
        return None
    wanted = int(match.group(1)) * 60 + int(match.group(2))

    best, best_gap = None, 30.0
    for segment in segments:
        payload = getattr(segment, "payload", None) or {}
        start = payload.get("start")
        if not isinstance(start, (int, float)):
            continue
        gap = abs(start - wanted)
        if gap <= best_gap:
            best, best_gap = float(start), gap
    return best


def _cached_examples(video_id, points, limit=8):
    """Model-found examples for a video, cached on disk per video.

    The regex path is a fast guess; this is the answer. It costs one call per
    video, not per question, because the examples a lesson contains do not
    change between questions.
    """
    cache = FRAMES_DIR / str(video_id) / "examples.json"
    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except (OSError, ValueError):
            pass

    on_screen = "\n\n".join(
        (p.payload.get("text") or "").strip()
        for p in sorted(points, key=lambda x: x.payload.get("start") or 0)
        if (p.payload.get("text") or "").lstrip().startswith("[on screen]")
    )
    if not on_screen.strip():
        return []

    try:
        examples = extract_examples(on_screen, limit=limit)
    except Exception as error:  # noqa: BLE001 - never fail an answer over this
        print(f"[Cite] example extraction failed: {error}")
        return []

    if examples:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(examples, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    print(f"[Cite] {len(examples)} examples found on screen")
    return examples


def _example_chunks(points, limit=8):
    """The labelled on-screen example chunks, one per heading.

    Two shapes exist in the wild: a slide that labels each example
    ("Παράδειγμα 2: integer.py") and an IDE that simply opens the files
    (string.py, boolean.py). Keying on the filename covers both, so the Greek
    heading is a bonus rather than a requirement.
    """
    found = []
    seen = set()
    for point in points:
        payload = getattr(point, "payload", None) or {}
        text = payload.get("text") or ""
        if not text.lstrip().startswith("[on screen]"):
            continue

        # Generic on purpose. The first version listed string/integer/float/
        # boolean, i.e. the four file names of one specific lesson, and would
        # find nothing in any other course. A heading word or any source
        # filename now counts.
        heading = re.search(
            r"(?i)(?:Παράδειγμα|Παραδειγμα|Παραδείγματα|Άσκηση|Example|Examples|"
            r"Demo|Sample|Exercise)\s*#?\s*\d*[^\n]{0,50}",
            text,
        )
        filename = re.search(
            r"(?i)\b[\w\-]{1,40}\.(?:py|ipynb|js|jsx|ts|tsx|java|c|cpp|cs|rb|php|"
            r"go|rs|sql|html|css|json|sh|kt|swift|txt)\b",
            text,
        )
        if not heading and not filename:
            continue

        matched = heading or filename
        key = matched.group(0).lower().strip()
        if key in seen:
            continue
        seen.add(key)
        found.append((matched.group(0).strip(), point))
        if len(found) >= limit:
            break
    return found

def _frame_has_content(frame_path, min_std=6.0) -> bool:
    """False for a blank or near-blank frame, which must never be sent to OCR.

    A vision model asked to read a solid black frame does not answer "nothing":
    it invents plausible content. Measured here: a test clip with a plain dark
    frame produced a full Python solution ("class Solution: def
    suggestedProducts...") that was then indexed as on-screen text and quoted
    back in answers as if it came from the video. Any uniform frame -- a cut to
    black, a colour card, the first frame before the slides load -- has a
    luminance spread near zero, so the spread is a cheap and reliable gate.
    """
    try:
        import numpy as np
        from PIL import Image

        with Image.open(frame_path) as image:
            small = image.convert("L").resize((64, 36))
            values = np.asarray(small, dtype=np.float32)
    except Exception:
        return True  # never block OCR on a decoding problem
    return float(values.std()) >= min_std


def _frame_signature(frame_path, size=(64, 36)):
    """Coarse luminance signature of a frame, for spotting near-duplicates."""
    try:
        import numpy as np
        from PIL import Image

        with Image.open(frame_path) as image:
            small = image.convert("L").resize(size)
            return np.asarray(small, dtype=np.int16)
    except Exception:
        return None


def _signature_distance(left, right) -> float:
    """Fraction of pixels whose luminance changed noticeably, 0..1.

    Mean difference is the wrong measure: two different files open in the same
    IDE window differ only in the code area, so the average stays near zero and
    genuinely different screens get discarded. Counting changed pixels catches
    a localized edit even when most of the frame is identical.
    """
    if left is None or right is None:
        return 1.0
    changed = (abs(left - right) > 14).mean()
    return float(changed)


def _build_digests(segments, video_id, window_sec=300.0):
    """One structured digest per ~5-minute chunk, stored as a text segment.

    Built once at upload. Questions then retrieve a compact outline instead of
    dozens of raw segments, which is where the token saving comes from.
    """
    if not segments:
        return 0

    ordered = sorted(
        (s for s in segments if isinstance(s.get("start"), (int, float))),
        key=lambda s: s["start"],
    )
    if not ordered:
        return 0

    windows = {}
    for segment in ordered:
        bucket = int(float(segment["start"]) // window_sec)
        windows.setdefault(bucket, []).append(segment)

    digests = []
    for bucket in sorted(windows):
        chunk = windows[bucket]
        start = float(chunk[0]["start"])
        end = float(chunk[-1].get("end") or chunk[-1]["start"])
        label = f"[{_mmss(start)}-{_mmss(end)}]"
        transcript = "\n".join(
            f"[{_mmss(s['start'])}] {(s.get('text') or '').strip()}"
            for s in chunk
            if (s.get("text") or "").strip()
        )
        if len(transcript) < 200:
            continue
        data = digest_segment(transcript, label=label)
        if not data:
            continue

        parts = []
        for key in ("topics", "definitions", "key_points"):
            values = data.get(key) or []
            if values:
                parts.append(f"{key}: " + "; ".join(str(v) for v in values[:6]))
        for example in (data.get("examples") or [])[:6]:
            name = example.get("name")
            when = example.get("start")
            if name:
                parts.append(f"example {name}" + (f" @ {when}" if when else ""))
        if not parts:
            continue

        digests.append({
            "text": f"[digest {_mmss(start)}-{_mmss(end)}] " + " | ".join(parts),
            "timestamp": [start, end],
        })

    if not digests:
        return 0

    vectors = create_embeddings_from_transcript({"segments": digests})
    store_text_embeddings(video_id, vectors, id_prefix="digest")
    print(f"[Digest] {len(digests)} segment digests stored")
    return len(digests)


def _asks_for_examples(question: str) -> bool:
    """True when the question is about the worked examples."""
    return bool(
        re.search(r"(?i)παραδείγμα|παραδειγμ|examples?|παραδειγματ", question or "")
    )


def _append_on_screen_examples(candidates, segments, limit=8):
    """Fold the indexed on-screen example chunks into the model's context.

    The transcript never names the examples -- the lecturer says "another
    example, I declare a variable" -- so an answer built from speech alone lists
    only whichever ones happened to be talked about and silently drops the rest.
    The on-screen chunks carry all of them, verbatim.
    """
    existing = {str(getattr(r, "id", "")) for r in candidates}

    # Clean single-example chunks only. An unsplit slide chunk also matches the
    # pattern, but it holds several examples at once, so adding it makes the
    # model repeat itself.
    usable = []
    for point in segments:
        payload = getattr(point, "payload", None) or {}
        text = payload.get("text") or ""
        if not text.lstrip().startswith("[on screen]"):
            continue
        if not _OCR_EXAMPLE_RE.search(text):
            continue
        headings = len(re.findall(r"(?i)(?:Παράδειγμα|Example)\s*\d", text))
        if headings > 1 or len(text) > 420:
            continue
        if str(getattr(point, "id", "")) in existing:
            continue
        usable.append((text, point))

    # Prefer chunks that actually name an example. Terminal screenshots of the
    # same code also match, and they crowd out the labelled ones.
    headed = [
        item for item in usable
        if re.search(r"(?i)(?:Παράδειγμα|Example)\s*\d", item[0])
    ]
    if len(headed) >= 2:
        usable = headed

    usable.sort(key=lambda item: (item[1].payload.get("start") or 0, len(item[0])))
    added = 0
    seen_headings = set()
    for text, point in usable:
        if added >= limit:
            break
        match = re.search(r"(?i)(?:Παράδειγμα|Example)\s*\d[^\n]{0,40}", text)
        key = re.sub(r"\s+", " ", match.group(0)).strip().lower() if match else None
        if key and key in seen_headings:
            continue
        if key:
            seen_headings.add(key)
        candidates.append(point)
        existing.add(str(getattr(point, "id", "")))
        added += 1
    return added


def _example_timestamps(frames_dir, points, answer, refine_sec=120.0):
    """One timestamp per worked example, from speech and screen together.

    Speech locates WHICH example is being discussed and roughly when; the frames
    pin down exactly when it is highlighted, which the transcript cannot show
    because the examples share one slide. Each audio estimate is refined to the
    nearest screen highlight within the window, and left alone when there is
    none -- so a missing highlight degrades to the audio time instead of
    inventing one.
    """
    audio_times = _example_moments(answer, points)
    if not audio_times:
        return []

    highlights = []
    try:
        highlights = sorted(_underline_moments(frames_dir, limit=60))
    except Exception as highlight_error:
        print(f"[Cite] highlight detection failed: {highlight_error}")

    fused = []
    for moment in audio_times:
        near = [h for h in highlights if abs(h - moment) <= refine_sec]
        fused.append(near[0] if near else moment)
        if near:
            print(f"[Cite] {int(moment)}s refined to {int(near[0])}s by frame highlight")
    return fused


def _underline_moments(frames_dir, segments=10, min_step=1.2, limit=4):
    """When each example starts being underlined on screen.

    All four examples share one slide, so their text and their frame times are
    identical. What differs is the red underline the lecturer draws under each
    in turn. Splitting the frame into vertical slices and looking for the
    largest jump in each slice's red share recovers the order and the timing --
    which no text-based method can see.

    Calibrated against hand-marked times on a real lecture: three of four
    examples landed within 12s. The fourth (12:37) was missed because the video
    cuts to black seconds later, so its underline has almost no frames.
    """
    manifest = Path(frames_dir) / "frames.json"
    if not manifest.exists():
        return []
    try:
        entries = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []

    entries = sorted(entries, key=lambda entry: entry.get("t") or 0)
    if len(entries) < 4:
        return []

    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return []

    def profile(path):
        try:
            with Image.open(path) as image:
                arr = np.asarray(image.convert("RGB"), dtype=np.int16)
        except Exception:
            return None
        red, green, blue = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
        mask = (red > 120) & (red - green > 50) & (red - blue > 50)
        total = int(mask.sum())
        if total < 200:
            return None  # blank or near-blank frame
        rows = mask.sum(axis=1)
        height = arr.shape[0]
        return [
            float(rows[height * i // segments:height * (i + 1) // segments].sum()) / total * 100.0
            for i in range(segments)
        ]

    series = []
    for entry in entries:
        values = profile(Path(frames_dir) / entry["file"])
        if values is not None:
            series.append((float(entry.get("t") or 0), values))
    if len(series) < 4:
        return []

    # Largest positive step per slice, and when it happened. A step means "red
    # appeared here that was not here before", which is the underline starting.
    steps = {}
    for index in range(1, len(series)):
        moment, values = series[index]
        _, previous = series[index - 1]
        changes = [
            slice_index for slice_index in range(segments)
            if abs(values[slice_index] - previous[slice_index]) > 1.0
        ]
        # A slide change rewrites most of the frame and produces enormous
        # deltas that would drown out the underlines. An underline touches one
        # or two slices, so anything broader is a transition, not a highlight.
        if len(changes) > 3:
            continue
        for slice_index in changes:
            delta = values[slice_index] - previous[slice_index]
            if delta < min_step:
                continue
            if slice_index not in steps or delta > steps[slice_index][1]:
                steps[slice_index] = (moment, delta)

    ordered = sorted(steps.values(), key=lambda item: item[1], reverse=True)[:limit]
    return sorted(moment for moment, _ in ordered)


def _ocr_example_timestamps(points, limit=8):
    """Timestamps of the on-screen example chunks that were retrieved.

    The examples are the OCR segments themselves, so their frame times ARE the
    answer. This does not read the model's answer at all, which is why it cannot
    be thrown off by how the answer happens to be formatted.
    """
    found = []
    for point in points:
        payload = getattr(point, "payload", None) or {}
        text = payload.get("text") or ""
        start = payload.get("start")
        if not isinstance(start, (int, float)):
            continue
        if not text.lstrip().startswith("[on screen]"):
            continue
        if not _OCR_EXAMPLE_RE.search(text):
            continue
        # A properly split chunk is one example: short, and carrying code. An
        # unsplit chunk holds a whole slide -- several examples plus prose -- and
        # matches every query, which is what produced a row of times from the
        # first two minutes.
        if len(text) > 420:
            continue
        if "=" not in text and "print" not in text:
            continue
        if any(abs(start - existing) < 0.5 for existing in found):
            continue
        found.append(float(start))
    return sorted(found)[:limit]


def _example_moments(answer: str, points) -> list:
    """One moment per worked example, in the order the answer presents them.

    The code identifies the example: "is_pretty" or "number1" appears in exactly
    one place on screen, so BM25 against the indexed segments resolves it
    without guessing. This is the version that is deterministic -- matching on
    prose paraphrases is not.
    """
    if not answer or not points:
        return []

    chunks = [
        chunk.strip()
        for chunk in _EXAMPLE_BLOCK_RE.split(answer)
        if chunk.strip() and _EXAMPLE_BLOCK_RE.search(chunk)
    ]
    if not chunks:
        return []

    by_id = {str(getattr(p, "id", "")): p for p in points}
    moments = []
    for chunk in chunks:
        scores = _bm25_scores(chunk, points)
        if not scores:
            continue
        top_id, top_score = max(scores.items(), key=lambda item: item[1])
        if top_score <= 0:
            continue
        holder = by_id.get(top_id)
        payload = (holder.payload if holder else None) or {}
        start_value = payload.get("start")
        if isinstance(start_value, (int, float)):
            moments.append(float(start_value))

    return moments


_CITATION_TOLERANCE_SEC = 1.0


def _context_segment_starts(segments) -> list[float]:
    """Start times of the segments the model was actually given."""
    starts = []
    for segment in segments or []:
        payload = getattr(segment, "payload", None) or {}
        start = payload.get("start")
        if isinstance(start, (int, float)):
            starts.append(float(start))
    return sorted(set(starts))


def _enforce_citations(
    answer: str,
    segments,
    fallback_start=None,
    tolerance: float = _CITATION_TOLERANCE_SEC,
):
    """Keep only the inline `mm:ss` markers that point at a real excerpt.

    The old behaviour snapped every marker to the nearest segment start, which
    always succeeded -- so a timestamp the model invented was silently "fixed"
    into a different, equally plausible moment, and the user clicked through to
    the wrong part of the video. A citation that is close to an excerpt it was
    given is accepted (and rewritten to that excerpt's exact start, so the jump
    is exact); anything further away is a fabricated time and is removed.

    When nothing survives, one citation is attached to the first prose
    paragraph, taken from the best-scoring excerpt, so no answer is uncited.

    Returns (answer, kept, dropped, used_fallback).
    """
    starts = _context_segment_starts(segments)
    kept = 0
    dropped = 0

    def _rewrite(outside: str) -> str:
        nonlocal kept, dropped

        def _replace(match):
            nonlocal kept, dropped
            requested = int(match.group(1)) * 60 + int(match.group(2))
            if starts:
                nearest = min(starts, key=lambda value: abs(value - requested))
                if abs(nearest - requested) <= tolerance:
                    kept += 1
                    return f"`{_mmss(nearest)}`"
            dropped += 1
            return ""

        text = _INLINE_TIMESTAMP_RE.sub(_replace, outside)
        # Removing a marker can leave "()" or a double space behind.
        text = re.sub(r"\(\s*[,;]?\s*\)", "", text)
        text = re.sub(r"(?<=\S)[ \t]{2,}", " ", text)
        text = re.sub(r"[ \t]+\n", "\n", text)
        return text

    # A fenced block is code: a `mm:ss` inside it is not a citation.
    parts = answer.split("```")
    for index in range(0, len(parts), 2):
        parts[index] = _rewrite(parts[index])
    result = "```".join(parts)

    used_fallback = False
    if kept == 0 and starts:
        anchor = fallback_start if isinstance(fallback_start, (int, float)) else starts[0]
        marker = f"`{_mmss(anchor)}`"
        paragraphs = result.split("\n\n")
        for index, block in enumerate(paragraphs):
            stripped = block.strip()
            # Only prose paragraphs: a heading, list, quote or fence is not a
            # place to hang the answer's first citation.
            if not stripped or stripped.startswith(("```", "#", "|", ">", "-", "*")):
                continue
            paragraphs[index] = block.rstrip() + " " + marker
            used_fallback = True
            break
        if used_fallback:
            result = "\n\n".join(paragraphs)
        else:
            result = result.rstrip() + "\n\n" + marker
            used_fallback = True

    return result, kept, dropped, used_fallback



def _initialize_current_video_id() -> str | None:
    uploads = [path for path in UPLOAD_DIR.iterdir() if path.is_file()]
    if not uploads:
        return None
    latest_upload = max(uploads, key=lambda path: path.stat().st_mtime)
    return latest_upload.stem


def _load_transcript_text(video_id: str | None) -> str:
    if not video_id or not TRANSCRIPTS_PATH.exists():
        return ""

    try:
        with open(TRANSCRIPTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return ""

    transcript_data = data.get(video_id) if isinstance(data, dict) else None
    if transcript_data is None and isinstance(data, dict) and "segments" in data:
        transcript_data = data

    if not isinstance(transcript_data, dict):
        return ""

    segments = transcript_data.get("segments") or []
    texts = []
    for segment in segments:
        if isinstance(segment, dict):
            text = segment.get("text")
            if text:
                texts.append(text)

    return " ".join(texts)


def _load_transcript_record(video_id: str | None):
    if not TRANSCRIPTS_PATH.exists():
        return None

    try:
        with open(TRANSCRIPTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    if isinstance(data, dict):
        if video_id and isinstance(data.get(video_id), dict):
            return data[video_id]
        if "segments" in data:
            return data

    return None


def _find_uploaded_video(video_id: str | None):
    if not video_id:
        return None

    matches = [path for path in UPLOAD_DIR.iterdir() if path.is_file() and path.stem == video_id]
    if not matches:
        return None

    return max(matches, key=lambda path: path.stat().st_mtime)


def _ensure_text_artifacts(video_id: str | None):
    transcript_data = _load_transcript_record(video_id)
    transcript_has_text = bool(
        transcript_data
        and any(
            isinstance(segment, dict) and (segment.get("text") or "").strip()
            for segment in (transcript_data.get("segments") or [])
        )
    )

    embeddings_present = False
    if EMBEDDINGS_PATH.exists():
        try:
            with open(EMBEDDINGS_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                # The store is keyed by video stem, so only this video's entry
                # counts -- another video's embeddings must not satisfy ours.
                embeddings_present = bool((loaded.get(video_id or "current") or {}).get("segments") or loaded.get(video_id or "current"))
            else:
                embeddings_present = bool(loaded)
        except Exception:
            embeddings_present = False

    if transcript_has_text and not embeddings_present:
        embeddings = create_embeddings_from_transcript(transcript_data)
        _update_shared_json(EMBEDDINGS_PATH, embeddings, video_id or "current")
        store_text_embeddings(video_id or "current", embeddings)
        return transcript_data, embeddings

    if transcript_has_text:
        return transcript_data, None

    uploaded_video = _find_uploaded_video(video_id)
    if not uploaded_video:
        return None, None

    output_audio = AUDIO_DIR / f"{uploaded_video.stem}.wav"
    transcript_for_json, embeddings, _ = _run_audio_pipeline(uploaded_video, output_audio)

    if transcript_for_json.get("segments"):
        _update_shared_json(TRANSCRIPTS_PATH, transcript_for_json, uploaded_video.stem)
    if embeddings:
        _update_shared_json(EMBEDDINGS_PATH, embeddings, uploaded_video.stem)

    return transcript_for_json, embeddings

# Runtime folder layout used by this API:
# - uploads/: original uploaded video files
# - audio/: extracted WAV audio files (same stem as video)
# - frames/: extracted image frames grouped by video stem
# - normalized/: re-encoded MP4s produced when a video needs format
#   normalization or its audio stream turns out to be corrupted
#   (the local-flow normalize fallback in _run_audio_pipeline)
#
# Using Path(__file__).parent keeps paths stable regardless of where the
# process is started from.
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

print("UPLOAD_DIR EXISTS:", UPLOAD_DIR.exists())

AUDIO_DIR = Path(__file__).resolve().parent
AUDIO_DIR = BASE_DIR / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

FRAMES_DIR = Path(__file__).resolve().parent
FRAMES_DIR = BASE_DIR / "frames"
FRAMES_DIR.mkdir(parents=True, exist_ok=True)

NORMALIZED_DIR = BASE_DIR / "normalized"
NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)

# Shared JSON stores: every uploaded video's data is merged into these single
# fixed files (keyed by video stem) instead of writing a new JSON file named
# after each video's title.
TRANSCRIPTS_PATH = AUDIO_DIR / "output.json"
EMBEDDINGS_PATH = AUDIO_DIR / "output_embeddings.json"

CURRENT_VIDEO_ID = _initialize_current_video_id()

app = FastAPI()

ensure_collections()  # Create Qdrant collections if they don't exist


def _warm_models():
    """Load the embedding models on a background thread at boot.

    Both load lazily on first use, so without this the first upload after every
    restart pays the text model inside the request. Measured on this machine:
    39.3s to load MiniLM against 0.29s to actually embed 52 segments.

    Sequential, not parallel: they are memory-heavy and running them at once
    just makes both slower.
    """
    try:
        warm_text_model()
        print("[Warmup] text embedding model ready")
    except Exception as exc:
        print(f"[Warmup] text embedding model failed: {exc}")



# Blocking on purpose. The first upload used to compete with a background
# warmup for the same 28s of model loading, so it looked like the upload itself
# was slow. Paying it before the server binds makes startup honest: when the
# log says ready, it is ready.
_warm_models()

# Registered before CORS on purpose: the last middleware added ends up
# outermost, and a 401 has to carry CORS headers too or the browser reports a
# network failure instead of "sign in first".
app.add_middleware(auth_guard.AuthGateMiddleware)

# CORS is open here to simplify local frontend/backend integration.
# In production this should be restricted to known frontend origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

# API answers are JSON and text, which is exactly what compresses well. Caddy
# proxies straight to this app, so nginx's gzip never sees these responses;
# compressing here saves the bandwidth anyway, on every question.
app.add_middleware(GZipMiddleware, minimum_size=800)

# Static mounts expose generated files directly over HTTP, so the frontend can
# render videos and access derived assets without a separate download endpoint.
# Example: /uploads/demo.mp4 maps to backend/uploads/demo.mp4 on disk.
app.mount(
    "/uploads",
    StaticFiles(directory=str(UPLOAD_DIR)),
    name="uploads"
) 

# Example: /audio/demo.wav maps to backend/audio/demo.wav.
app.mount(
    "/audio",
    StaticFiles(directory=str(AUDIO_DIR)),
    name="audio"
) 

# Example: /frames/demo/frame000001.jpg maps to backend/frames/demo/frame000001.jpg.
app.mount(
     "/frames",
     StaticFiles(directory=str(FRAMES_DIR)),
     name="frames"
) 

def _require_debug() -> None:
    """Debug routes dump other people's transcripts: off unless explicitly enabled."""
    if os.getenv("ENABLE_DEBUG_ENDPOINTS", "").strip() != "1":
        raise HTTPException(status_code=404, detail="Not found")


@app.get('/debug/segments')
def debug_segments(video_id: str | None = None):
    """Dump the indexed segments so retrieval can be inspected directly."""
    _require_debug()
    target = video_id or CURRENT_VIDEO_ID
    try:
        points = scroll_all_text(target)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    rows = []
    for point in points:
        payload = getattr(point, "payload", None) or {}
        rows.append({
            "start": payload.get("start"),
            "end": payload.get("end"),
            "text": (payload.get("text") or "")[:300],
            "on_screen": (payload.get("text") or "").lstrip().startswith("[on screen]"),
        })
    rows.sort(key=lambda row: row["start"] if isinstance(row["start"], (int, float)) else 0)
    return {"video_id": target, "count": len(rows), "segments": rows}


@app.get('/debug/qdrant-counts')
async def debug_qdrant_counts():
    _require_debug()
    return {
        "text_points": client.count(collection_name=TEXT_COLLECTION).count,
        "frame_points": client.count(collection_name=FRAME_COLLECTION).count,
    }


@app.get('/metrics')
async def metrics_snapshot():
    """Citation quality counters: how often an answer is jumpable, and how many
    timestamps the model invented and had to be dropped."""
    return metrics.snapshot()


@app.post('/metrics/citation-click')
async def metrics_citation_click():
    """Called by the UI when a jump-to-time citation is clicked."""
    metrics.bump("citation_clicks")
    return {"ok": True}

@app.get('/video-frames/{video_id}')
async def video_frames(video_id: str):
    """Timestamped thumbnails for a processed video.

    Reads the manifest _run_frame_pipeline writes beside the JPEGs, so this is
    one small file read rather than a Qdrant query. Returns an empty list when
    a video has no frames yet, which the UI treats as "no previews available"
    rather than as an error.
    """
    # video_id arrives straight from the URL and is used to build a path, so
    # keep it to a plain name and refuse anything that could traverse.
    if not video_id or not all(ch.isalnum() or ch in "-_" for ch in video_id):
        raise HTTPException(status_code=400, detail="Invalid video id")

    manifest = FRAMES_DIR / video_id / "frames.json"
    if not manifest.exists():
        return {"video_id": video_id, "frames": []}

    try:
        entries = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"video_id": video_id, "frames": []}

    return {
        "video_id": video_id,
        "frames": [
            {"t": entry["t"], "url": f"/frames/{video_id}/{entry['file']}"}
            for entry in entries
            if entry.get("file")
        ],
    }


JOBS = {}

# Heavy jobs (a video or a document being analysed) are the only thing on this
# machine that can exhaust it: two ffmpeg decodes plus two embedding passes on
# two cores and ~1 GB of headroom is the practical ceiling. Letting a third
# start anyway does not add throughput, it makes every one of them slower and
# can push the box into swap, where the whole backend (and every job in it)
# dies. Queued here instead, politely, at the upload endpoint.
# Uploads used to share one two-slot gate, so a video decode held every PDF
# upload behind it even though a PDF is API-bound and costs this box almost
# nothing. Each kind now has its own gate: three documents at a time, two videos.
MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "2") or "2")
MAX_CONCURRENT_DOC_JOBS = int(
    os.getenv("MAX_CONCURRENT_DOC_JOBS", "3") or "3"
)
MAX_CONCURRENT_VIDEO_JOBS = int(
    os.getenv("MAX_CONCURRENT_VIDEO_JOBS", os.getenv("MAX_CONCURRENT_JOBS", "2")) or "2"
)
_JOB_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_VIDEO_JOBS)
_DOC_JOB_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_DOC_JOBS)

# Figure descriptions are independent vision calls. Done one after another they
# dominated an upload (35s of a 55s job for a 23-page handout); they are network
# bound, so several at a time costs this box nothing.
FIGURE_WORKERS = int(os.getenv("DOCUMENT_FIGURE_WORKERS", "5") or "5")

# Cloudflare Stream transcode: when the token really has Stream access, a remote
# video is transcoded and served by Cloudflare and handed to Groq as a URL, so
# this box never downloads the file and never runs ffmpeg on it. Off unless the
# operator asks for it, and it fails back to the local path on its own.
_STREAM_TRANSCODE = (os.getenv("STREAM_TRANSCODE", "0") or "0").strip().lower() not in (
    "0", "false", "no", "off",
)

# The edge route: Cloudflare turns the R2 object into audio-only slices that Groq
# fetches, so neither the download nor ffmpeg happens here. Bounded by the edge's
# own limits (<=100 MB, <=10 min per source).
_MEDIA_TRANSFORM = (os.getenv("MEDIA_TRANSFORM_ENABLED", "0") or "0").strip().lower() not in (
    "0", "false", "no", "off",
)


def _media_transform_transcript(file_key, video_path, job_id=None):
    """Audio via Cloudflare's edge, or None when this route does not apply."""
    if not (file_key and cloudflare_media.configured()):
        return None

    duration = _probe_duration_seconds(video_path)
    if not duration:
        print("[Media] could not read the duration; using the local path")
        return None
    if duration > cloudflare_media.MAX_SECONDS:
        print(
            f"[Media] {duration:.0f}s exceeds the edge limit of "
            f"{cloudflare_media.MAX_SECONDS}s; using the local path"
        )
        return None

    if job_id:
        # 25% used to be the last word until the whole first slice came back; the
        # stage now says what it is waiting for.
        _set_job_status(job_id, stage="transcribing_audio", progress=25)

    def progress(done, total):
        if job_id and total:
            _set_job_status(
                job_id,
                stage="transcribing_audio",
                progress=25 + int(50 * done / total),
            )

    try:
        return cloudflare_media.transcribe_media(
            file_key, duration, on_progress=progress
        )
    except Exception as error:
        print(f"[Media] edge route failed ({error}); using the local path")
        return None


def _compact_transcript_for_json(transcript):
    """Persist only timestamped text segments instead of raw chunk metadata."""
    if isinstance(transcript, dict):
        data = transcript
    elif hasattr(transcript, "model_dump"):
        data = transcript.model_dump()
    elif hasattr(transcript, "dict"):
        data = transcript.dict()
    elif hasattr(transcript, "__dict__"):
        data = vars(transcript)
    else:
        data = {}

    def to_dict(item):
        if isinstance(item, dict):
            return item
        if hasattr(item, "model_dump"):
            return item.model_dump()
        if hasattr(item, "dict"):
            return item.dict()
        if hasattr(item, "__dict__"):
            return vars(item)
        return None

    raw_chunks = data.get("segments") or data.get("chunks") or []
    segments = []

    for item in raw_chunks:
        item_dict = to_dict(item)
        if not isinstance(item_dict, dict):
            continue

        start = item_dict.get("start")
        end = item_dict.get("end")
        timestamp = item_dict.get("timestamp")

        if isinstance(timestamp, (list, tuple)) and len(timestamp) == 2:
            if start is None:
                start = timestamp[0]
            if end is None:
                end = timestamp[1]

        segments.append(
            {
                "start": start,
                "end": end,
                "text": (item_dict.get("text") or "").strip(),
            }
        )

    compact = {"segments": segments}

    # Word timings drive citation precision: a quoted phrase is placed by
    # locating it in this list, so dropping it here would cap accuracy back at
    # the ~7s segment boundary.
    words = []
    for item in data.get("words") or []:
        item_dict = to_dict(item)
        if not isinstance(item_dict, dict):
            continue
        text = item_dict.get("w") or item_dict.get("word") or item_dict.get("text")
        word_start = item_dict.get("start")
        word_end = item_dict.get("end")
        if not text or not isinstance(word_start, (int, float)):
            continue
        words.append({
            "w": text,
            "start": word_start,
            "end": word_end if isinstance(word_end, (int, float)) else word_start,
        })
    if words:
        compact["words"] = words

    # Keep the language Whisper was pinned to, so answers don't have to re-derive
    # it from the transcript's script on every question.
    language = data.get("language")
    if language:
        compact["language"] = language

    return compact


_JSON_WRITE_LOCK = threading.Lock()


def _update_shared_json(path: Path, data, video_id: str | None = None):
    """Merge this video's data into the shared JSON store under its video_id.

    The store is a dict keyed by video stem ({video_id: {segments, ...}}) so
    concurrent uploads never overwrite each other's transcript. Writes are
    serialized with a lock and replaced atomically, so two pipelines finishing
    at the same time cannot corrupt the file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with _JSON_WRITE_LOCK:
        existing = {}
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    existing = loaded
            except Exception:
                existing = {}
        if video_id:
            existing[video_id] = data
        else:
            # Legacy callers without a video_id: keep their payload under a
            # top-level shape the readers already understand.
            existing.update(data if isinstance(data, dict) else {})
        # A fixed temp name collided when two workers finished at once: one
        # renamed the other's file away and the loser died with FileNotFoundError.
        tmp_path = path.with_name(
            f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:6]}.tmp"
        )
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
        tmp_path.replace(path)



def _set_job_status(job_id, status=None, stage=None, progress=None, error=None, result=None):
    # The worker is a separate process: the status file is the shared truth, the
    # dict below is only this process's cache of it.
    try:
        job_store.update(
            job_id,
            status=status,
            stage=stage,
            progress=progress,
            error=error,
            result=result,
        )
    except Exception as store_error:
        print(f"[Jobs] status write failed for {job_id}: {store_error}")

    job = JOBS.get(job_id, {})
    if status is not None:
        job["status"] = status
    if stage is not None:
        job["stage"] = stage
    if progress is not None:
        job["progress"] = int(max(0, min(100, progress)))
    if error is not None:
        job["error"] = error
    if result is not None:
        job["result"] = result
    JOBS[job_id] = job


# --- chunked video (browser-side split) --------------------------------------
# A long recording is cut by the browser into ten-minute pieces, which keeps every
# piece inside the edge audio route's window. Each piece is an ordinary video job;
# this section remembers the pieces of one video and merges them in order.

CHUNKS_DIR = BASE_DIR / "audio" / "chunks"


def _chunk_path(video_id: str, index: int) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "", str(video_id)) or "video"
    return CHUNKS_DIR / safe / f"{int(index):04d}.json"


def _chunk_dir(video_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "", str(video_id)) or "video"
    return CHUNKS_DIR / safe


def merge_chunks(video_id: str, chunk_count: int, offsets: dict | None = None) -> dict | None:
    """Merge the pieces of one video, in order, with their offsets.

    Idempotent: it only runs when every piece is present, and the merged file is
    what the rest of the pipeline reads.
    """
    directory = _chunk_dir(video_id)
    parts = []
    for index in range(int(chunk_count)):
        path = _chunk_path(video_id, index)
        if not path.exists():
            return None
        try:
            parts.append((index, json.loads(path.read_text(encoding="utf-8"))))
        except Exception as error:
            print(f"[Chunks] {video_id} piece {index} unreadable: {error}")
            return None

    segments = []
    texts = []
    for index, payload in sorted(parts, key=lambda item: item[0]):
        offset = float((offsets or {}).get(index, payload.get("offset") or 0) or 0)
        for segment in payload.get("segments") or []:
            item = dict(segment)
            for key in ("start", "end"):
                if isinstance(item.get(key), (int, float)):
                    item[key] = item[key] + offset
            segments.append(item)
        piece_text = (payload.get("text") or "").strip()
        if piece_text:
            texts.append(piece_text)

    merged = {"segments": segments, "text": " ".join(texts).strip()}
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "merged.json").write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
    _update_shared_json(TRANSCRIPTS_PATH, merged, video_id)

    try:
        embeddings = create_embeddings_from_transcript(merged)
        store_text_embeddings(video_id, embeddings)
        print(f"[Chunks] {video_id}: merged {len(parts)} pieces, {len(segments)} segments indexed")
    except Exception as error:
        print(f"[Chunks] {video_id}: merged but not indexed: {error}")

    return merged


def _run_audio_pipeline(video_path, output_audio: Path, job_id=None, video_id: str | None = None, file_key: str | None = None):
    """Extract audio, transcribe it, and create/store text embeddings.

    Runs with detailed progress tracking. When job_id is given, pushes
    granular stage/progress updates as each step advances -- without this,
    the frontend's progress bar sat frozen at "extracting_audio" for the
    entire (often multi-minute) transcription pass, since that was the only
    status update between the start and the final "finalizing" jump.

    video_path may also be an http(s) URL: ffmpeg streams it directly, which is
    how R2-hosted videos are processed without the file ever landing on this
    server. In that case a video_id must be supplied (a URL has no usable stem)
    and the normalize fallback is skipped -- re-encoding needs a local file, so
    the caller downloads one if it wants that path.
    """
    vid = video_id or Path(video_path).stem
    transcript_error = None
    transcript_for_json = {"segments": []}
    embeddings = []

    # A short local video goes to Groq exactly as uploaded: the endpoint takes the
    # container and downsamples internally, so the ffmpeg audio pass -- the
    # heaviest CPU step on this box -- is skipped and no WAV is written. A longer
    # file, an unsupported container, or a remote URL keeps extract-and-chunk.
    media_direct = can_transcribe_directly(video_path)
    audio_source = str(video_path) if media_direct else None
    if media_direct:
        print(f"[Whisper] {Path(video_path).name}: sending the media straight to Groq")
        output_audio = None

    # Cloudflare Stream can transcode the media and serve it, which removes the
    # download and the ffmpeg pass entirely: the worker becomes a courier that
    # hands URLs to Groq. Only for remote media (Cloudflare has to fetch it) and
    # only when the token actually reaches Stream; otherwise None and the local
    # path below runs as before.
    # Edge audio first: it costs no CPU here and beats both other remote routes.
    media_transcript = None
    if not media_direct and _MEDIA_TRANSFORM:
        media_transcript = _media_transform_transcript(file_key, video_path, job_id)

    stream_transcript = None
    if not media_direct and stream_transcript is None and media_transcript is None and _STREAM_TRANSCODE:
        source = str(video_path)
        if source.lower().startswith(("http://", "https://")):
            if job_id:
                _set_job_status(job_id, stage="transcoding_remote", progress=25)
            # Stream normalises the container and produces a much smaller H.264
            # copy. If it lands under the direct limit, no ffmpeg runs at all;
            # otherwise the existing decode runs on this copy, not the original.
            streamed = cloudflare_stream.transcode_to_file(
                source, Path(output_audio).parent, name=vid
            )
            if streamed is not None:
                if can_transcribe_directly(streamed):
                    media_direct = True
                    audio_source = str(streamed)
                    print(f"[Stream] {streamed.name} is small enough for a direct Groq call")
                else:
                    video_path = str(streamed)
                    print(f"[Stream] decoding the transcoded copy instead of the original")

    try:
        t_audio = time.perf_counter()
        if not media_direct and stream_transcript is None and media_transcript is None:
            extract_audio(video_path, output_audio)
        print(f"✓ Audio extraction complete for {vid}  [{time.perf_counter()-t_audio:.1f}s]")
    except RuntimeError as e:
        print(f"✗ Direct audio extraction failed for {vid}: {e}")
        if str(video_path).lower().startswith(("http://", "https://")):
            # Re-encoding needs a local file; let the caller fall back to
            # downloading the object from R2 and processing it like an upload.
            raise
        try:
            normalized_video = normalize_video(video_path, NORMALIZED_DIR, force=True)
            print(f"↻ Retrying audio extraction from normalized video: {normalized_video}")
            extract_audio(normalized_video, output_audio)
        except Exception as normalize_error:
            transcript_error = f"Could not extract audio: {normalize_error}"
            print(transcript_error)
            output_audio = None

    try:
        if not audio_source and output_audio and Path(output_audio).exists():
            audio_source = str(output_audio)
        if audio_source:
            import time as _time
            t0 = _time.perf_counter()
            print(f"✓ Starting transcription for {vid}...")

            if job_id:
                _set_job_status(job_id, stage="transcribing_audio", progress=30)

            def _on_transcribe_progress(completed, total):
                if job_id and total:
                    _set_job_status(
                        job_id,
                        stage="transcribing_audio",
                        progress=30 + int(45 * completed / total),
                    )

            if media_transcript is not None:
                transcript = media_transcript
                print(f"[Media] transcription served by the Cloudflare edge for {vid}")
            elif stream_transcript is not None:
                transcript = stream_transcript
                print(f"[Stream] transcription served from Cloudflare for {vid}")
            elif media_direct:
                transcript = transcribe_media_direct(audio_source)
                if job_id:
                    _set_job_status(job_id, stage="transcribing_audio", progress=75)
            else:
                transcript = transcribe_audio_chunks(
                    audio_source, on_progress=_on_transcribe_progress
                )
            transcript_for_json = _compact_transcript_for_json(transcript)
            print(f"✓ Transcription complete: {len(transcript_for_json.get('segments', []))} segments  [{_time.perf_counter()-t0:.1f}s]")

            if job_id:
                _set_job_status(job_id, stage="embedding_text", progress=80)

            t1 = _time.perf_counter()
            print(f"↻ Creating text embeddings...")
            embeddings = create_embeddings_from_transcript(transcript_for_json)
            store_text_embeddings(vid, embeddings)
            print(f"✓ Embeddings stored: {len(embeddings)} vectors  [{_time.perf_counter()-t1:.1f}s]")

            # Compact outline per 5-minute chunk, so questions do not have to
            # re-read the whole transcript every time.
            try:
                _build_digests(transcript_for_json.get("segments") or [], vid)
            except Exception as digest_error:
                print(f"[Digest] skipped: {digest_error}")

            if job_id:
                _set_job_status(job_id, stage="embedding_text", progress=90)
    except Exception as e:
        transcript_error = str(e)
        print(f"✗ Transcription/embedding failed for {vid}: {e}")
        import traceback
        traceback.print_exc()

    return transcript_for_json, embeddings, transcript_error


# A lecture announces a concept before it explains one: "τι είναι X", "δηλαδή",
# "για παράδειγμα", "θα δούμε". Those phrases mark the moments a learner would
# want a still for, which is a different set from the frames a pixel-difference
# detector picks -- on a slide lecture the biggest visual change is usually an
# annotation appearing, so scene selection reliably keeps the red underlines and
# drops the definitions.
_CONCEPT_MARKERS = [
    r"\bτι ε(ί|ι)ναι\b", r"\bορίζετ", r"\bορισμ", r"\bδηλαδ(ή|η)\b",
    r"\bγια παράδειγμα\b", r"\bπαράδειγμα\b", r"\bας πούμε\b",
    r"\bθα δούμε\b", r"\bτώρα θα\b", r"\bμάθαμε\b", r"\bπρόσεξ",
    r"\bwhat is\b", r"\bdefinition\b", r"\bfor example\b",
]
_CONCEPT_PATTERN = re.compile("|".join(_CONCEPT_MARKERS), re.IGNORECASE)


def _concept_moments(segments, min_gap_sec=20.0, limit=40):
    """Timestamps of announced definitions and worked examples.

    Deliberately falls back to nothing rather than guessing: if a transcript has
    no markers this returns [], and the video simply keeps its scene frames.
    """
    moments = []

    for segment in segments or []:
        start = segment.get("start")
        if start is None:
            continue
        if not _CONCEPT_PATTERN.search(segment.get("text") or ""):
            continue
        # One still per moment: markers cluster within a sentence or two.
        if moments and (start - moments[-1]) < min_gap_sec:
            continue
        moments.append(float(start))
        if len(moments) >= limit:
            break

    return moments


_EXAMPLE_HEADING_RE = re.compile(
    r"(?i)(?=^\s*#?\s*(?:Παράδειγμα|Example|ΠΑΡΑΔΕΙΓΜΑ)\s+\d+)", re.MULTILINE
)


def _example_key(chunk: str):
    """Stable identity for an example chunk: its heading line.

    OCR returns slightly different text for the same slide on every frame, so
    exact-text dedupe never fires and a 56-frame video yields a hundred
    near-identical chunks. The heading names the example, and only four of those
    exist.
    """
    first_line = (chunk or "").strip().split("\n", 1)[0].strip()
    if _OCR_EXAMPLE_RE.search(first_line):
        return re.sub(r"\s+", " ", first_line).strip().lower()
    return None


def _split_on_example_headings(text: str):
    """One chunk per worked example within a slide.

    A single slide can carry four examples. Stored as one segment they share
    one timestamp, so every example resolves to the same moment and none can be
    cited individually. Splitting on the headings keeps each example its own
    retrievable unit, all at the time that slide is on screen.
    """
    parts = [part.strip() for part in _EXAMPLE_HEADING_RE.split(text or "") if part.strip()]
    return parts or [(text or "").strip()]


def _add_concept_frames(
    video_path,
    transcript,
    frames_dir,
    lookahead_sec=2.0,
    coverage_interval_sec=20.0,
    max_width=0,
    coverage_stamps=None,
):
    """Extract a still for each concept moment and add it to the manifest.

    Named frame9NNNNN.jpg so they sort after, and cannot collide with,
    ffmpeg's own frame000001-style numbering.
    """
    frames_dir = Path(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = frames_dir / "frames.json"

    entries = []

    # Coverage pass runs FIRST, because extract_frames globs frame*.jpg from the
    # directory and would otherwise count the concept frames as its own. A slide
    # can sit on screen through an example whose name is never spoken, so
    # concept moments alone leave gaps: on a 12-minute lecture they produced 16
    # frames and captured only one of four code examples.
    coverage = {}
    if coverage_stamps:
        # The visual thread already extracted the coverage pass; reusing its
        # stamps skips a full serial re-seek of every interval frame against
        # the (remote) source, which used to dominate the pipeline.
        coverage = dict(coverage_stamps)
        for name, moment in coverage.items():
            if moment is None:
                continue
            entries.append({"file": name, "t": float(moment)})
        print(f"[Frames] reusing {len(coverage)} coverage frames already extracted")
    elif coverage_interval_sec and float(coverage_interval_sec) > 0:
        try:
            _, coverage = extract_frames(
                video_path,
                frames_dir,
                interval_seconds=float(coverage_interval_sec),
                extraction_mode="interval",
                scene_threshold=0.12,
                keyframes_only=False,
                max_width=max_width,
                # Dedupe off for coverage: two code slides share a layout and
                # differ only in a few lines, so an 8x8 perceptual hash calls
                # them identical and drops the very frame that names the
                # example. Uniform sampling has nothing to dedupe anyway.
                min_gap_sec=0.0,
                max_hash_distance=0,
            )
            for name, moment in (coverage or {}).items():
                if moment is None:
                    continue
                entries.append({"file": name, "t": float(moment)})
            print(f"[Frames] {len(coverage or {})} coverage frames every {coverage_interval_sec}s")
        except Exception as coverage_error:
            print(f"[Frames] coverage pass failed for {video_path.stem}: {coverage_error}")

    moments = _concept_moments((transcript or {}).get("segments"))
    if not moments:
        if entries:
            entries.sort(key=lambda entry: entry["t"])
            manifest_path.write_text(json.dumps(entries), encoding="utf-8")
        return 0

    added = 0
    moments = list(moments)
    if moments:
        # The stills are independent ffmpeg seeks against the same source (a
        # presigned R2 URL in production); serially, connection setup plus the
        # moov parse per seek dominated the whole pipeline. Names come from
        # the index, not completion order, and gaps from failures are
        # harmless: frame9* sorts after ffmpeg's frame0* either way, and the
        # manifest is sorted by timestamp below.
        def _grab(index, moment):
            at = float(moment) + max(0.0, float(lookahead_sec))
            target = frames_dir / f"frame9{index + 1:05d}.jpg"
            return index, at, target, extract_frame_at(video_path, at, target)

        with ThreadPoolExecutor(max_workers=min(4, len(moments))) as seek_pool:
            futures = [seek_pool.submit(_grab, i, m) for i, m in enumerate(moments)]
            for future in futures:
                try:
                    index, at, target, ok = future.result()
                except Exception as seek_error:
                    print(f"[Frames] concept seek failed: {seek_error}")
                    continue
                if not ok:
                    continue
                entries.append({"file": target.name, "t": at})
                added += 1

    if entries:
        entries.sort(key=lambda entry: entry["t"])
        manifest_path.write_text(json.dumps(entries), encoding="utf-8")

    return added


def _nearest_frame(frames_dir, moment, max_gap_sec=45.0):
    """The frame closest in time to `moment`, or None when nothing is close."""
    manifest = Path(frames_dir) / "frames.json"
    if not manifest.exists():
        return None
    try:
        entries = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    best = None
    best_gap = max_gap_sec
    for entry in entries:
        try:
            gap = abs(float(entry["t"]) - float(moment))
        except (KeyError, TypeError, ValueError):
            continue
        if gap <= best_gap:
            best, best_gap = entry, gap
    return best


def _frame_data_url(frame_path):
    """Inline a JPEG so a hosted model can see it.

    A URL will not do: the frames are served from the dev machine, which the
    OpenAI servers cannot reach. Inlining costs roughly 1k tokens per still.
    """
    try:
        import base64

        payload = base64.b64encode(Path(frame_path).read_bytes()).decode("ascii")
    except Exception:
        return None
    return f"data:image/jpeg;base64,{payload}"


# Sampling interval for the frames that get OCR'd. Independent of the scrubber
# thumbnail interval, which can afford to be much denser.
#
# 30s instead of 20s: a slide that matters stays up far longer than that, and the
# wider spacing means a third fewer ffmpeg seeks, a third fewer images through
# the vision reader and a third fewer bytes on disk per lecture. This is the
# cheapest way to make an upload lighter without losing anything a student would
# search for.
COVERAGE_INTERVAL_SEC = float(os.getenv("COVERAGE_INTERVAL_SEC", "30") or "30")

# Frames are read by a vision model and written to disk, so their pixel count is
# a direct cost. A 1080p lecture still is unreadable as a thumbnail and costs
# four times what a 960px one does; the text the model needs survives the
# downscale. 0 keeps the video's own resolution.
FRAME_MAX_WIDTH = int(os.getenv("FRAME_MAX_WIDTH", "960") or "0")


def _frame_halves_data_urls(frame_path, scale=3):
    """The left and right halves of a frame, upscaled, as data URLs.

    Half the width upscaled three times gives the vision model roughly six times
    the pixels per character compared with the whole frame. On a 640x360 lecture
    capture the whole frame read "x = 3+5" as "x = 345" -- the plus sign vanished
    into the space around it. Reading the halves costs one extra call per frame
    and recovers the punctuation, which is the whole point of indexing code.
    """
    try:
        from PIL import Image
        import io

        with Image.open(frame_path) as image:
            image = image.convert("RGB")
            width, height = image.size
            boxes = [
                (0, 0, width // 2, height),
                (width // 2, 0, width, height),
            ]
            urls = []
            for index, box in enumerate(boxes):
                piece = image.crop(box)
                if scale != 1:
                    piece = piece.resize(
                        (piece.width * scale, piece.height * scale),
                        Image.LANCZOS,
                    )
                buffer = io.BytesIO()
                piece.save(buffer, format="JPEG", quality=92)
                encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
                urls.append(
                    (index, f"data:image/jpeg;base64,{encoded}")
                )
            return urls
    except Exception as error:  # noqa: BLE001 - fall back to the whole frame
        print(f"[OCR] half-crop failed for {frame_path.name}: {error}")
        return []


def _ocr_frames(frames_dir, video_id, stamps=None, workers=4):
    """Read the on-screen text of every frame and index it.

    Independent of the transcript, so the upload can run it alongside
    transcription instead of after it -- OCR is the slowest stage.

    `stamps` maps filename -> seconds and comes straight from extract_frames.
    It has to be passed in: frames.json is written later, by the concept-frame
    pass, so relying on it here silently returned zero OCR segments and the
    answers lost every example but the one that happened to be spoken about.
    """
    if stamps:
        entries = [
            {"file": name, "t": float(moment)}
            for name, moment in stamps.items()
            if moment is not None
        ]
    else:
        manifest = Path(frames_dir) / "frames.json"
        if not manifest.exists():
            print(f"[OCR] no frames manifest in {frames_dir}; nothing to read")
            return 0
        try:
            entries = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
    if not entries:
        return 0

    # Skip frames that are visually the same as the previous one, measured by the
    # FRACTION of pixels that changed rather than the average difference. The
    # average stays near zero when only the code area changes inside an
    # otherwise identical IDE window, which is exactly the case that matters.
    prepared = []
    previous = None
    blank = 0
    for entry in entries:
        frame_path = Path(frames_dir) / entry["file"]
        if not _frame_has_content(frame_path):
            blank += 1
            continue
        signature = _frame_signature(frame_path)
        if signature is not None and previous is not None:
            if _signature_distance(signature, previous) < 0.04:
                continue
        if signature is not None:
            previous = signature
        data_url = _frame_data_url(frame_path)
        if data_url:
            prepared.append((entry, data_url))
    if blank:
        print(f"[OCR] skipped {blank} blank/near-blank frame(s)")

    # Vision calls are the slowest, most expensive stage of an upload, and they
    # are the ones that multiply hardest when several people upload at once.
    # Beyond this many frames the extra ones add little: a slide that matters
    # stays up for more than one sample anyway. Kept as an env knob because it
    # trades detail for speed and cost.
    ocr_cap = int(os.getenv("OCR_MAX_FRAMES", "24") or "24")
    if len(prepared) > ocr_cap:
        step = len(prepared) / ocr_cap
        prepared = [prepared[int(i * step)] for i in range(ocr_cap)]
        print(f"[OCR] capped to {ocr_cap} frames (OCR_MAX_FRAMES)")
    print(f"[OCR] reading {len(prepared)} of {len(entries)} frames (visually distinct)")

    ocr_segments = []
    if prepared:
        def _read_frame(item):
            entry, whole = item
            halves = _frame_halves_data_urls(Path(frames_dir) / entry["file"])
            if not halves:
                return transcribe_image(whole)
            # Both halves, joined in reading order.
            parts = [transcribe_image(url) for _, url in halves]
            return "\n".join(part for part in parts if part)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            texts_read = list(pool.map(_read_frame, prepared))
        seen_examples, seen_slides = set(), set()
        for (entry, _), visible in zip(prepared, texts_read):
            if not visible:
                continue
            moment = entry.get("t")
            for chunk in _split_on_example_headings(visible):
                key = _example_key(chunk)
                if key:
                    if key in seen_examples:
                        continue
                    seen_examples.add(key)
                else:
                    slug = re.sub(r"\W+", " ", chunk).strip().lower()[:120]
                    if slug in seen_slides:
                        continue
                    seen_slides.add(slug)
                ocr_segments.append({
                    "text": f"[on screen] {chunk}",
                    "timestamp": [moment, moment],
                })

    if not ocr_segments:
        return 0

    vectors = create_embeddings_from_transcript({"segments": ocr_segments})
    store_text_embeddings(video_id, vectors, id_prefix="ocr")
    print(f"[OCR] {len(ocr_segments)} on-screen texts indexed")
    return len(ocr_segments)


def _fallback_frame_interval(video_path, ceiling=60.0, minimum=2.0, target_frames=8):
    """Sampling interval for the "nothing was announced" fallback pass.

    A fixed 60s is right for an hour-long lecture and wrong for a short clip:
    on a 10s video fps=1/60 selects nothing, ffmpeg exits with "Nothing was
    written into output file", and the frame pass aborted with no visual index
    at all. Scaling to the duration keeps the ceiling for long videos and still
    produces frames for short ones.
    """
    try:
        from video_processing import _probe_duration_seconds

        duration = _probe_duration_seconds(video_path)
    except Exception:
        duration = None

    if not duration or duration <= 0:
        return ceiling
    return max(minimum, min(ceiling, float(duration) / target_frames))


# A video's frame pass is the most expensive thing this box does: ffmpeg decodes
# the file twice and CLIP embeds every still on CPU. FRAME_EMBEDDINGS=0 keeps it
# out of the pipeline entirely -- answers then come from the transcript alone,
# which is what the API-backed path (Groq for speech, OpenAI for vectors) needs
# anyway. Set it to 1 to bring visual search back.
_FRAME_PIPELINE = (os.getenv("FRAME_EMBEDDINGS", "0") or "0").strip().lower() not in (
    "0", "false", "no", "off",
)


def _sync_concept_frames(video_path, transcript, frames_dir, base_count=0, max_width=0, coverage_stamps=None):
    """Add frames chosen from the transcript, then index everything in the dir.

    Used by both orderings: in audio-first mode base_count is 0 and these are
    the only frames; in the parallel mode they supplement the scene pass.
    """
    if not _FRAME_PIPELINE:
        return base_count

    try:
        added = _add_concept_frames(
            video_path, transcript, frames_dir, max_width=max_width,
            coverage_stamps=coverage_stamps,
        )

        if added == 0 and not base_count:
            # Nothing was announced: no speech at all, or a language this
            # heuristic misses. Fall back to sparse uniform frames so the video
            # still has a visual index instead of none, which would also empty
            # the frame collection and silently disable visual search.
            count, stamps = extract_frames(
                video_path,
                Path(frames_dir),
                interval_seconds=_fallback_frame_interval(video_path),
                extraction_mode="interval",
                scene_threshold=0.12,
                keyframes_only=False,
                max_width=max_width,
            )
            entries = [
                {"file": name, "t": float(moment)}
                for name, moment in stamps.items()
                if moment is not None
            ]
            entries.sort(key=lambda item: item["t"])
            if entries:
                (Path(frames_dir) / "frames.json").write_text(
                    json.dumps(entries), encoding="utf-8"
                )
            print(
                f"[Frames] no concepts announced; using {count} interval frames instead"
            )

        manifest_path = Path(frames_dir) / "frames.json"
        if not manifest_path.exists():
            return base_count

        entries = json.loads(manifest_path.read_text(encoding="utf-8"))
        print(f"[Frames] {len(entries)} frames on disk ({added} chosen from what was said)")
        return len(entries)
    except Exception as frame_error:
        print(f"[Frames] concept pass failed for {video_path.stem}: {frame_error}")
        return base_count


class YoutubeRequest(BaseModel):
    url: str
    frame_interval_sec: float = 5.0
    frame_strategy: str = "audio"
    scene_threshold: float = 0.12
    keyframes_only: bool = False
    frame_max_width: int = 0  # 0 = keep the video's own resolution


class SignupRequest(BaseModel):
    email: str
    password: str
    full_name: str | None = None


@app.post('/auth/signup')
async def auth_signup(req: SignupRequest):
    """Create an account that is already confirmed.

    Supabase's own sign-up mails a confirmation link, and this project has no
    mailer configured, so an account created that way could never be activated.
    The service key can create the user with email_confirm already set -- that
    is the whole reason this endpoint exists. It issues no token: the browser
    still signs in with the public key afterwards, so nothing is trusted here
    that was not proven there.
    """
    import requests as http

    base = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    secret = os.environ.get("SUPABASE_SECRET_KEY") or ""
    if not base or not secret:
        raise HTTPException(status_code=503, detail="Sign-up is not configured on this server")

    email = (req.email or "").strip().lower()
    password = req.password or ""
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=400, detail="Enter a valid email address")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="The password needs at least 8 characters")

    payload = {
        "email": email,
        "password": password,
        "email_confirm": True,
        "user_metadata": {
            "full_name": (req.full_name or email.split("@")[0]).strip()[:80],
        },
    }

    def _create():
        return http.post(
            f"{base}/auth/v1/admin/users",
            json=payload,
            headers={"apikey": secret, "Authorization": f"Bearer {secret}"},
            timeout=25,
        )

    response = await run_in_threadpool(_create)

    if response.status_code in (200, 201):
        print(f"[Auth] account created: {email}")
        return {"status": "created", "email": email}

    detail = "Could not create the account"
    try:
        body = response.json()
        detail = (
            body.get("msg")
            or body.get("error_description")
            or body.get("message")
            or detail
        )
    except Exception:
        pass

    if "already" in str(detail).lower() or "exists" in str(detail).lower():
        raise HTTPException(status_code=409, detail="That account already exists")
    raise HTTPException(status_code=400, detail=str(detail))


@app.post('/download-youtube/')
async def download_youtube(
    req: YoutubeRequest, request: Request, background_tasks: BackgroundTasks
):
    """Download a YouTube video via yt-dlp, push it to R2, then process it
    through the same R2 pipeline as every other video."""
    import re as _re
    import subprocess
    import sys

    start_time = time.perf_counter()

    try:
        owner_id = _current_user(request)
        video_prefix = user_scope.directory("videos", owner_id)
    except (ValueError, RuntimeError) as scope_error:
        raise HTTPException(status_code=503, detail=str(scope_error))

    url = (req.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="No URL provided")

    if not _re.search(r"(youtube\.com|youtu\.be)", url):
        raise HTTPException(status_code=400, detail="URL does not look like a YouTube link")

    job_id = str(uuid.uuid4())
    JOBS[job_id] = {
        "job_id": job_id,
        "status": "processing",
        "stage": "downloading",
        "progress": 3,
        "error": None,
        "result": None,
    }

    def _download_and_process():
        import youtube_ingest

        try:
            _set_job_status(job_id, stage="reading_metadata", progress=4)
            imported = youtube_ingest.import_to_r2(
                url,
                on_status=lambda stage=None, progress=None, error=None, **_:
                    _set_job_status(job_id, stage=stage, progress=progress, error=error),
                prefix=video_prefix,
            )

            # The pipeline keys everything (audio WAV, frames, Qdrant points) by
            # video_id, and reads the video back from R2 -- never from disk.
            video_id = video_registry.scoped_id(owner_id, f"yt_{uuid.uuid4().hex[:12]}")
            video_registry.register(video_id, owner_id, imported["file_key"])
            display_name = f"{(imported.get('title') or video_id)[:120]}.mp4"
            print(f"[YouTube] {imported.get('reason')}: {imported['file_key']}")
            _set_job_status(job_id, stage="processing_audio_and_frames", progress=15)
            _process_r2_video_job(
                job_id,
                imported["file_key"],
                display_name,
                video_id,
                start_time,
            )
        except Exception as exc:
            _set_job_status(job_id, status="failed", stage="failed", progress=100, error=str(exc))

    background_tasks.add_task(_download_and_process)

    return {
        "job_id": job_id,
        "status": "processing",
        "stage": "downloading",
        "progress": 3,
        "status_url": f"/upload-status/{job_id}",
    }


@app.post('/uploadfile/')
async def create_upload_file(
    request: Request,
    background_tasks: BackgroundTasks,
    file_upload: UploadFile,
    video_id: str | None = Form(None),
    chunk_index: int | None = Form(None),
    chunk_count: int | None = Form(None),
    chunk_offset: float | None = Form(None),
):
    """Stream the upload into R2 and kick off analysis -- no local copy.

    The body is forwarded to R2 in multipart chunks (8 MiB, sequential reads),
    so the video is never written to this server's disk. The pipeline then
    reads it back from R2 over a presigned URL, exactly like the direct
    browser-to-R2 flow; the response shape stays the one the frontend expects.
    """
    global CURRENT_VIDEO_ID

    start_time = time.perf_counter()
    user_id = _current_user(request)

    if not file_upload.filename:
        raise HTTPException(status_code=400, detail="Missing uploaded filename")

    content_type = (file_upload.content_type or "video/mp4").lower()
    try:
        video_prefix = user_scope.directory("videos", user_id)
    except (ValueError, RuntimeError) as scope_error:
        raise HTTPException(status_code=503, detail=str(scope_error))

    try:
        # FastAPI has fully spooled the multipart body by the time this runs,
        # so the underlying file object is complete and readable.
        file_upload.file.seek(0)
        uploaded = await run_in_threadpool(
            r2_service.upload_stream,
            file_upload.file,
            file_upload.filename,
            content_type,
            8 * 1024 * 1024,
            video_prefix,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error))

    file_key = uploaded["file_key"]
    # A chunked upload sends its own video_id so every piece lands under the same
    # name; a single-file upload keeps deriving it from the filename.
    video_id = video_registry.scoped_id(
        user_id,
        (video_id or "").strip()
        or (Path(r2_service.sanitize_file_name(file_upload.filename)).stem or "video"),
    )
    video_registry.register(video_id, user_id, file_key)
    print(f"[Upload] {file_upload.filename} -> R2 {file_key} ({uploaded['size'] / 1024 / 1024:.1f} MB)")

    job_id = str(uuid.uuid4())
    job_store.create(
        job_id,
        status="processing",
        stage="queued",
        progress=5,
        kind="video",
        video_id=video_id,
    )
    JOBS[job_id] = {
        "job_id": job_id,
        "status": "processing",
        "stage": "queued",
        "progress": 5,
        "error": None,
        "result": None,
    }
    job_store.enqueue(
        {
            "kind": "video",
            "job_id": job_id,
            "owner_id": user_id,
            "file_key": file_key,
            "display_name": file_upload.filename,
            "video_id": video_id,
            "chunk_index": chunk_index,
            "chunk_count": chunk_count,
            "chunk_offset": chunk_offset,
        }
    )
    print(f"[Upload] queued video job {job_id} ({file_upload.filename})")

    CURRENT_VIDEO_ID = video_id

    return {
        "job_id": job_id,
        "status": "processing",
        "stage": "queued",
        "progress": 5,
        "status_url": f"/upload-status/{job_id}",
        "video_id": video_id,
        "file_key": file_key,
    }


@app.get('/upload-status/{job_id}')
async def get_upload_status(job_id: str):
    # The worker owns the progress; this process may only have the first entry.
    job = job_store.read(job_id) or JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job.get("job_id"),
        "status": job.get("status"),
        "stage": job.get("stage"),
        "progress": job.get("progress", 0),
        "error": job.get("error"),
        "result": job.get("result"),
    }


# ---------------------------------------------------------------------------
# Direct-to-R2 uploads: the browser PUTs the file to Cloudflare R2 with a
# presigned URL, so video bytes never pass through this server. Only the signed
# URLs and the processing metadata flow through the API.
# ---------------------------------------------------------------------------

class ProcessVideoRequest(BaseModel):
    file_key: str


@app.get('/api/get-upload-url')
async def api_get_upload_url(
    request: Request, file_name: str, content_type: str = "video/mp4"
):
    """A one-time PUT URL the frontend uploads the video to, straight to R2."""
    try:
        return generate_presigned_upload_url(
            file_name,
            content_type,
            prefix=user_scope.directory("videos", _current_user(request)),
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error))


@app.post('/api/process-video')
async def api_process_video(
    req: ProcessVideoRequest, request: Request, background_tasks: BackgroundTasks
):
    """Kick off analysis for a video that already sits in R2.

    The pipeline reads the file straight from a presigned URL with ffmpeg, so
    the upload itself stays browser -> R2. The result carries a stable
    /api/video-stream/{file_key} address for the player, which hands out a
    fresh presigned URL per request instead of an expiring one.
    """
    global CURRENT_VIDEO_ID

    user_id = _current_user(request)

    try:
        file_key = r2_service.validate_file_key(req.file_key)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    # An upload URL is issued to one account. Processing a key from another
    # account's directory would read a file this user cannot even see.
    if not user_scope.owns("videos", user_id, file_key):
        raise HTTPException(status_code=403, detail="That file is not in your library")

    display_name = r2_service.display_name_for_key(file_key)
    stem = r2_service.sanitize_file_name(display_name)
    video_id = video_registry.scoped_id(user_id, Path(stem).stem or "video")
    video_registry.register(video_id, user_id, file_key)

    start_time = time.perf_counter()
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {
        "job_id": job_id,
        "status": "processing",
        "stage": "queued",
        "progress": 5,
        "error": None,
        "result": None,
    }

    background_tasks.add_task(
        _process_r2_video_job,
        job_id,
        file_key,
        display_name,
        video_id,
        start_time,
    )

    # The player may ask for this video before it says anything else, and /ask
    # without an explicit video_id must hit the same video.
    CURRENT_VIDEO_ID = video_id

    return {
        "job_id": job_id,
        "status": "processing",
        "stage": "queued",
        "progress": 5,
        "status_url": f"/upload-status/{job_id}",
        "video_id": video_id,
        "file_key": file_key,
    }


@app.get('/api/video-stream/{file_key:path}')
async def api_video_stream(file_key: str):
    """302 to a fresh presigned URL, so the player never holds an expired one."""
    try:
        key = r2_service.validate_file_key(file_key)
        download_url = generate_presigned_download_url(key, expires_in=3600)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error))
    # Every player load counts as "someone is watching", which also cancels a
    # release sent moments before (e.g. the pagehide of a refresh).
    _touch_video_presence(key, active=True)
    return RedirectResponse(download_url, status_code=302)


# --- Storage retention --------------------------------------------------------
# R2 holds the file that was just uploaded, not a library. Keeping every handout
# and every recording forever is how a bucket fills and a bill arrives, so two
# rules apply, in this order:
#
#   1. Nothing stays longer than R2_MAX_AGE_HOURS (3 hours). The file is the one
#      part of an analysis that can be replaced by uploading it again; the
#      reading cannot, so the reading is what survives.
#   2. If the bucket still grows past R2_MAX_GB, objects are evicted oldest first
#      inside a priority order: a video nobody is watching goes before a video
#      leaving a player, and any video goes before a document.
#
# Videos keep their session rule as well, which frees space long before four
# hours: 30 seconds after the player is closed, or VIDEO_RETENTION_MINUTES
# without a heartbeat from a tab that died.
#
# Never deleted: the extracted page texts (backend/documents), the vectors in
# Qdrant and the conversations in backend/chats. A document whose file has aged
# out still answers every question and keeps its chat history for its owner; the
# API reports the file as gone and the viewer says so instead of drawing a
# broken frame.
R2_MAX_AGE_HOURS = float(os.getenv("R2_MAX_AGE_HOURS", "3") or "3")
R2_MAX_BYTES = int(float(os.getenv("R2_MAX_GB", "8") or "8") * 1024 ** 3)
R2_SWEEP_SECONDS = float(os.getenv("R2_SWEEP_SECONDS", "120") or "120")

VIDEO_RETENTION_MINUTES = float(os.environ.get("VIDEO_RETENTION_MINUTES", "60") or "60")
_RELEASE_GRACE_SECONDS = 30.0

_VIDEO_LAST_SEEN = {}
_VIDEO_RELEASED_AT = {}
_PRESENCE_LOCK = threading.Lock()


def _touch_video_presence(file_key: str, active: bool = True) -> None:
    now = time.time()
    with _PRESENCE_LOCK:
        if active:
            _VIDEO_LAST_SEEN[file_key] = now
            _VIDEO_RELEASED_AT.pop(file_key, None)
        else:
            _VIDEO_RELEASED_AT[file_key] = now


def _documents_by_file_key() -> dict:
    """file_key -> document record, so a deleted object can be marked gone."""
    index = {}
    for path in DOCS_DIR.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                document = json.load(handle)
        except Exception:
            continue
        key = document.get("file_key")
        if key:
            index[key] = document
    return index


def _expire(entry: dict, reason: str, documents: dict) -> bool:
    """Delete one object; if it was a document, record that its file is gone."""
    key = entry["key"]
    if not r2_service.delete_object(key):
        return False
    print(f"[R2] retention: deleted {key} ({reason})")
    document = documents.pop(key, None)
    if document is not None:
        document["file_available"] = False
        document["file_expired_at"] = time.time()
        try:
            _save_document(document)
        except Exception as error:
            print(f"[R2] could not mark {document.get('doc_id')} as expired: {error}")
    with _PRESENCE_LOCK:
        _VIDEO_LAST_SEEN.pop(key, None)
        _VIDEO_RELEASED_AT.pop(key, None)
    return True


def _r2_retention_sweeper():
    # Objects already in the bucket when this starts begin their clock at their
    # upload time, so an old pile ages out instead of living forever.
    seeded = False
    while True:
        time.sleep(R2_SWEEP_SECONDS)
        try:
            objects = r2_service.list_objects()
        except Exception as error:
            print(f"[R2] retention listing failed (retrying): {error}")
            continue

        if not seeded:
            with _PRESENCE_LOCK:
                for entry in objects:
                    if entry["key"].startswith(r2_service.UPLOAD_KEY_PREFIX):
                        _VIDEO_LAST_SEEN.setdefault(entry["key"], entry["last_modified"])
            seeded = True
            print(
                f"[R2] retention read {len(objects)} object(s), "
                f"max age {R2_MAX_AGE_HOURS:g}h"
            )

        now = time.time()
        documents = _documents_by_file_key()
        alive = []

        # 1. the hard cap
        for entry in objects:
            age = now - entry["last_modified"]
            if R2_MAX_AGE_HOURS > 0 and age > R2_MAX_AGE_HOURS * 3600:
                if _expire(entry, f"uploaded {age / 3600:.1f}h ago", documents):
                    continue
            alive.append(entry)

        # 2. a video whose player has gone
        for entry in list(alive):
            key = entry["key"]
            if not key.startswith(r2_service.UPLOAD_KEY_PREFIX):
                continue
            with _PRESENCE_LOCK:
                seen = _VIDEO_LAST_SEEN.get(key, entry["last_modified"])
                released_at = _VIDEO_RELEASED_AT.get(key)
            if released_at is not None and now - released_at >= _RELEASE_GRACE_SECONDS:
                reason = f"the player left {int(now - released_at)}s ago"
            elif now - seen > VIDEO_RETENTION_MINUTES * 60:
                reason = f"no viewer for {int((now - seen) / 60)} min"
            else:
                continue
            if _expire(entry, reason, documents):
                alive.remove(entry)

        # 3. the ceiling, in priority order
        total = sum(entry["size"] for entry in alive)
        if R2_MAX_BYTES > 0 and total > R2_MAX_BYTES:

            def priority(entry):
                if not entry["key"].startswith(r2_service.UPLOAD_KEY_PREFIX):
                    return 2
                with _PRESENCE_LOCK:
                    return 1 if entry["key"] in _VIDEO_LAST_SEEN else 0

            reason = f"storage over {R2_MAX_BYTES / 1024 ** 3:.1f} GB"
            for entry in sorted(alive, key=lambda e: (priority(e), e["last_modified"])):
                if total <= R2_MAX_BYTES:
                    break
                if _expire(entry, reason, documents):
                    total -= entry["size"]


def _start_retention_sweeper():
    if not r2_service.R2_BUCKET_NAME:
        return
    threading.Thread(
        target=_r2_retention_sweeper, name="r2-retention", daemon=True
    ).start()


_start_retention_sweeper()



# --- Derived-artifact retention ----------------------------------------------
# A video leaves its WAV (about 8 MB per 13 minutes) and its frames (a few MB)
# on this disk forever, even though the video itself lives in R2. Nothing reads
# them again once the student has moved on, so they age out. The video currently
# open is skipped by name, and anything newer than the cutoff is skipped too, so
# an upload in progress can never be deleted.
ARTIFACT_RETENTION_DAYS = float(os.getenv("ARTIFACT_RETENTION_DAYS", "7") or "0")
_ARTIFACT_SWEEP_INTERVAL = 6 * 3600


def _artifact_cleanup_sweeper():
    import shutil

    while True:
        time.sleep(_ARTIFACT_SWEEP_INTERVAL)
        if ARTIFACT_RETENTION_DAYS <= 0:
            continue
        cutoff = time.time() - ARTIFACT_RETENTION_DAYS * 86400
        removed = 0
        freed = 0
        try:
            for wav in AUDIO_DIR.glob("*.wav"):
                try:
                    if wav.stem == CURRENT_VIDEO_ID:
                        continue
                    stat = wav.stat()
                    if stat.st_mtime >= cutoff:
                        continue
                    freed += stat.st_size
                    wav.unlink(missing_ok=True)
                    removed += 1
                except OSError:
                    continue

            for folder in FRAMES_DIR.iterdir():
                try:
                    if not folder.is_dir() or folder.name == CURRENT_VIDEO_ID:
                        continue
                    if folder.stat().st_mtime >= cutoff:
                        continue
                    size = sum(
                        item.stat().st_size for item in folder.rglob("*") if item.is_file()
                    )
                    shutil.rmtree(folder, ignore_errors=True)
                    freed += size
                    removed += 1
                except OSError:
                    continue
        except Exception as error:
            print(f"[Retention] sweep skipped: {error}")
            continue

        if removed:
            print(
                f"[Retention] removed {removed} artifact(s) older than "
                f"{ARTIFACT_RETENTION_DAYS:.0f} days, freed {freed / 1024 / 1024:.1f} MB"
            )


if ARTIFACT_RETENTION_DAYS > 0:
    threading.Thread(
        target=_artifact_cleanup_sweeper, name="artifact-retention", daemon=True
    ).start()


@app.get('/api/video-presence/{file_key:path}')
async def api_video_presence(file_key: str, active: bool = True):
    """Presence beacon from the video page.

    The frontend calls this once a minute while the page is open (active=1)
    and once when the user leaves or closes the tab (active=0). GET on
    purpose: a simple request needs no CORS preflight, so it also survives
    page unload via fetch keepalive.
    """
    try:
        key = r2_service.validate_file_key(file_key)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    _touch_video_presence(key, active=active)
    return {
        "file_key": key,
        "active": active,
        "retention_minutes": VIDEO_RETENTION_MINUTES,
    }


def _process_r2_video_job(job_id, file_key, display_name, video_id, start_time, job_context=None):
    """Analyze an R2-hosted video without storing it on this server.

    Pass 1 streams the file into ffmpeg straight from a presigned URL: audio is
    extracted to a local WAV (the transcript APIs need local audio chunks) and
    frames land in frames/<video_id>/ -- derived artifacts, not the video. Pass
    2 is the fallback for files ffmpeg cannot stream: download the object once
    with boto3 and process it like a classic upload.
    """
    # Same slot queue as documents: two decodes on two cores is the ceiling, and
    # a third upload waiting a little beats three uploads fighting.
    if not _JOB_SLOTS.acquire(timeout=1800):
        _set_job_status(
            job_id,
            status="failed",
            stage="failed",
            progress=100,
            error="The server is busy with other uploads. Please try again in a few minutes.",
        )
        return
    try:
        _set_job_status(job_id, status="processing", stage="preparing", progress=5)
        # Multi-video mode: nothing is wiped. Every video owns
        # audio/<video_id>.wav, frames/<video_id>/ and its own Qdrant points
        # (keyed by video_id), so concurrent uploads coexist.

        output_audio = AUDIO_DIR / f"{video_id}.wav"
        output_frames_dir = FRAMES_DIR / video_id

        # Signed now, used within minutes; 1h comfortably covers processing.
        try:
            source_url = generate_presigned_download_url(file_key, expires_in=3600)
        except (ValueError, RuntimeError) as r2_error:
            raise RuntimeError(f"R2 download URL failed: {r2_error}") from r2_error

        def _visual_only_task(from_source):
            if not _FRAME_PIPELINE:
                return 0, {}
            try:
                count, coverage_stamps = extract_frames(
                    from_source,
                    output_frames_dir,
                    interval_seconds=COVERAGE_INTERVAL_SEC,
                    extraction_mode="interval",
                    scene_threshold=0.12,
                    keyframes_only=False,
                    max_width=FRAME_MAX_WIDTH,
                    min_gap_sec=0.0,
                    max_hash_distance=0,
                )
                print(f"[Frames] {count} coverage frames every {COVERAGE_INTERVAL_SEC:.0f}s")
                _ocr_frames(output_frames_dir, video_id, coverage_stamps)
                return count, coverage_stamps
            except Exception as visual_error:
                print(f"[Frames] coverage pass failed: {visual_error}")
                return 0, {}

        _set_job_status(job_id, stage="extracting_audio", progress=10)
        coverage_stamps = {}
        with ThreadPoolExecutor(max_workers=2) as pool:
            visual_future = pool.submit(_visual_only_task, source_url)
            try:
                transcript_for_json, embeddings, transcript_error = _run_audio_pipeline(
                    source_url, output_audio, job_id=job_id, video_id=video_id, file_key=file_key
                )
            except RuntimeError as stream_error:
                # ffmpeg could not read the URL (codec/container/network).
                transcript_for_json, embeddings, transcript_error = None, [], str(stream_error)
            try:
                _visual_count, visual_stamps = visual_future.result()
                if visual_stamps:
                    coverage_stamps = dict(visual_stamps)
            except Exception as visual_error:
                print(f"[Frames] visual pass failed: {visual_error}")

        local_copy = None
        audio_ok = output_audio is not None and Path(output_audio).exists()
        if transcript_error or not audio_ok or not transcript_for_json.get("segments"):
            # Fallback: pull the object from R2 once and process it locally,
            # exactly like a classic upload. The copy goes to the system temp
            # dir and is deleted in the finally below -- the video itself never
            # takes up permanent space on this machine (R2 is the store).
            _set_job_status(job_id, stage="downloading_from_r2", progress=15)
            ext = Path(display_name).suffix or ".mp4"
            handle = tempfile.NamedTemporaryFile(prefix=f"chronomark-{video_id}-", suffix=ext, delete=False)
            local_copy = Path(handle.name)
            handle.close()
            try:
                try:
                    r2_service.download_to_file(file_key, local_copy)
                    print(f"[R2] fallback download complete: {local_copy.name}")
                except RuntimeError as download_error:
                    raise RuntimeError(f"Streaming failed and R2 download failed: {download_error}") from download_error

                with ThreadPoolExecutor(max_workers=2) as pool:
                    # The first visual pass already produced coverage frames
                    # and OCR'd them; only re-run it when it produced nothing.
                    visual_future = (
                        pool.submit(_visual_only_task, local_copy)
                        if not coverage_stamps
                        else None
                    )
                    transcript_for_json, embeddings, transcript_error = _run_audio_pipeline(
                        local_copy, output_audio, job_id=job_id, video_id=video_id, file_key=file_key
                    )
                    if visual_future is not None:
                        try:
                            _visual_count, visual_stamps = visual_future.result()
                            if visual_stamps:
                                coverage_stamps = dict(visual_stamps)
                        except Exception as visual_error:
                            print(f"[Frames] visual pass failed: {visual_error}")
            finally:
                try:
                    local_copy.unlink(missing_ok=True)
                except OSError as cleanup_error:
                    print(f"[R2] temp copy cleanup failed: {cleanup_error}")
            local_copy = None  # processed and deleted; concept frames use the URL

        frame_count = _sync_concept_frames(
            source_url, transcript_for_json, output_frames_dir, max_width=FRAME_MAX_WIDTH,
            coverage_stamps=coverage_stamps,
        )

        _set_job_status(job_id, status="processing", stage="finalizing", progress=95)

        _update_shared_json(TRANSCRIPTS_PATH, transcript_for_json, video_id)
        _update_shared_json(EMBEDDINGS_PATH, embeddings, video_id)

        total_time_sec = time.perf_counter() - start_time

        result = {
            "filename": display_name,
            # Stable address for the player; resolves to a fresh presigned URL.
            "file_url": f"/api/video-stream/{file_key}",
            "file_key": file_key,
            # No WAV is produced when the media went to Groq directly.
            "audio_url": (
                f"/audio/{video_id}.wav"
                if (Path("audio") / f"{video_id}.wav").exists()
                else None
            ),
            "video_id": video_id,
            "transcript_url": "/audio/output.json",
            "embeddings_url": "/audio/output_embeddings.json",
            "transcript": transcript_for_json,
            "transcript_error": transcript_error,
            "frame_count": frame_count,
            "total_time_sec": round(total_time_sec, 1),
        }
        _set_job_status(job_id, status="completed", stage="completed", progress=100, result=result)
        print(f"[Pipeline] R2 video processed for {video_id} in {total_time_sec:.1f}s")

        # Chunked upload: every piece stores its own transcript, and the merge runs
        # as soon as the last one is present.
        chunk_index = (job_context or {}).get("chunk_index")
        chunk_count = (job_context or {}).get("chunk_count")
        if chunk_index is not None and chunk_count:
            path = _chunk_path(video_id, chunk_index)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "offset": (job_context or {}).get("chunk_offset") or 0,
                        "text": transcript_for_json.get("text") or "",
                        "segments": transcript_for_json.get("segments") or [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            print(f"[Chunks] {video_id}: stored piece {chunk_index + 1}/{chunk_count}")
            merged = merge_chunks(video_id, chunk_count)
            if merged is not None:
                print(f"[Chunks] {video_id}: all {chunk_count} pieces merged")
    except Exception as e:
        total_time_sec = time.perf_counter() - start_time
        _set_job_status(job_id, status="failed", stage="failed", progress=100, error=str(e))
        print(f"[Pipeline] R2 pipeline failed after {total_time_sec:.1f}s: {e}")
    finally:
        try:
            _JOB_SLOTS.release()
        except ValueError:
            pass


@app.post("/ask")
async def ask(req: Question, request: Request):
    # A video is only ever answered for the account that analysed it.
    user_id = _current_user(request)
    if not req.video_id or not video_registry.is_owner(req.video_id, user_id):
        raise HTTPException(status_code=404, detail="Video not found")
    # Blocking retrieval and model call: off the event loop, in a thread.
    payload = await run_in_threadpool(_ask_impl, req)
    if req.conversation_id and payload.get("answer"):
        try:
            # Store it in the conversation that asked, so a recording and a
            # document live in the same history as everything else.
            await run_in_threadpool(
                conversations.append_turn,
                req.conversation_id,
                user_id,
                req.question,
                payload["answer"],
            )
        except Exception as chat_error:
            print(f"[Chats] could not store the video turn: {chat_error}")
    return payload


def _ask_impl(req: Question):
    try:
        question = req.question
        requested_video_id = req.video_id
        history = (req.history or [])[-6:]

        current_video_id = requested_video_id

        _ensure_text_artifacts(current_video_id)

        summary_mode = _is_summary_request(question)
        answer_language = _detect_question_language(question)

        if summary_mode:
            # For summaries, fetch ALL stored segments in chronological order
            # instead of doing a single semantic search — that way the LLM
            # sees the whole video, not just segments close to the word
            # "summary" in embedding space.
            all_segments = scroll_all_text(video_id=current_video_id)
            transcript_text = " ".join(
                (p.payload.get("text") or "").strip()
                for p in all_segments
                if (p.payload.get("text") or "").strip()
            )
            if transcript_text:
                answer_language = _detect_transcript_language(transcript_text)

            # Cap at 120 segments so we stay within context window; they are
            # already sorted chronologically so even-spacing gives coverage.
            if len(all_segments) > 120:
                step = len(all_segments) / 120
                all_segments = [all_segments[int(i * step)] for i in range(120)]

            text_results = all_segments
            sorted_results = all_segments
            context_candidates = all_segments
        else:
            query_embedding = embed_query(question)
            all_points = []
            text_results = search_text(query_embedding, limit=12, video_id=current_video_id)

            # Hybrid rerank: vector search alone cannot separate the examples --
            # every segment reads "another example, I declare a variable" -- and
            # the terms that distinguish them are rare.
            try:
                all_points = scroll_all_text(current_video_id)
                lexical = _bm25_scores(question, all_points)
                peak = max(lexical.values(), default=0.0)
                payloads = {str(p.id): (p.payload or {}) for p in all_points}

                merged = {}
                for result in text_results:
                    point_id = str(result.id)
                    vector_score = float(getattr(result, "score", 0.0) or 0.0)
                    lexical_score = (lexical.get(point_id, 0.0) / peak) if peak else 0.0
                    merged[point_id] = 0.45 * vector_score + 0.55 * lexical_score

                for point_id, raw in lexical.items():
                    if point_id in merged or peak <= 0:
                        continue
                    normalized = raw / peak
                    if normalized < 0.40:
                        continue
                    merged[point_id] = 0.55 * normalized

                ranked = sorted(merged.items(), key=lambda item: item[1], reverse=True)[:24]
                text_results = [
                    _Ranked(point_id, payloads.get(point_id, {}), score)
                    for point_id, score in ranked
                    if payloads.get(point_id)
                ]
                print(f"[Retrieval] hybrid ranked {len(ranked)} candidates")
            except Exception as hybrid_error:
                print(f"[Retrieval] hybrid rerank failed: {hybrid_error}")

            CONTEXT_MIN_SCORE = 0.15
            context_candidates = [
                r for r in text_results if r.score >= CONTEXT_MIN_SCORE
            ] or text_results[:4]

            # Include each match's immediate chronological neighbors so the
            # LLM sees full, continuous explanations (e.g. an automaton's
            # states, a data structure's operations) instead of isolated
            # sentences that happened to score highest individually.
            all_video_segments = scroll_all_text(video_id=current_video_id)

            if _asks_for_examples(question):
                added_examples = _append_on_screen_examples(
                    context_candidates, all_video_segments
                )
                if added_examples:
                    print(f"[Context] {added_examples} on-screen example chunks added")
            expanded_candidates = _expand_with_neighbors(context_candidates, all_video_segments, window=1)
            sorted_results = sorted(expanded_candidates, key=lambda r: r.payload.get("start") or 0)

        def _format_ts(seconds):
            if seconds is None:
                return "?"
            minutes, secs = divmod(int(seconds), 60)
            return f"{minutes}:{secs:02d}"

        # On-screen text is labelled WITHOUT a time on purpose. Its timestamp is
        # when the slide appeared, not when the lecturer explained the thing, and
        # a bare [mm:ss] label invited the model to cite 0:20 for every example on
        # a slide that was visible from the start.
        context = "\n".join(
            (
                # Already carries the label from _ocr_frames; re-adding it produced
                # "[on screen] [on screen] ..." in the model's context.
                text
                if text.lstrip().startswith("[on screen]")
                else f"[{_format_ts(r.payload.get('start'))}-{_format_ts(r.payload.get('end'))}] {text}"
            )
            for r in sorted_results
            for text in [(r.payload.get("text") or "").strip()]
            if text
        )
        print("Context:", context)

        if summary_mode and context:
            answer_language = _detect_transcript_language(context)

        transcript_available = bool(context.strip())

        try:
            # Stills of the moments the answer is about to point at, so the model
            # can read what is on screen -- code, a diagram, a slide -- rather
            # than only what was said. Gated on the transcript being weak: when
            # retrieval already scores well, images add cost without adding
            # answer.
            vision_images = []
            top_context_score = max(
                (getattr(r, "score", 0.0) for r in context_candidates), default=0.0
            )
            if not summary_mode and current_video_id and top_context_score < 0.55:
                frames_dir = FRAMES_DIR / current_video_id
                ranked = sorted(
                    context_candidates,
                    key=lambda r: getattr(r, "score", 0.0),
                    reverse=True,
                )[:2]
                for candidate in ranked:
                    start_sec = (candidate.payload or {}).get("start")
                    if start_sec is None:
                        continue
                    frame = _nearest_frame(frames_dir, start_sec)
                    if not frame:
                        continue
                    data_url = _frame_data_url(frames_dir / frame["file"])
                    if data_url:
                        vision_images.append(data_url)

            if vision_images:
                print(f"[Vision] sending {len(vision_images)} stills with the question")

            answer = ask_llama(
                question=question,
                context=context,
                images=vision_images or None,
                history=history,
                answer_language=answer_language,
                summary_mode=summary_mode,
                transcript_available=transcript_available,
            )
        except Exception as e:
            print(f"LLM error: {e}")
            raise HTTPException(status_code=502, detail=f"LLM provider error: {e}")

        # The LLM writes inline `mm:ss` markers (in backticks) citing the
        # excerpts it was given. It paraphrases those "[mm:ss-mm:ss]" tags and
        # can drift to a plausible-sounding time that is not an actual moment,
        # so every marker is checked against the starts of the segments that
        # were really in `context`: close enough is rewritten to the exact
        # start, anything else is a fabricated citation and is dropped.
        best_context = max(
            sorted_results, key=lambda r: getattr(r, "score", 0) or 0, default=None
        )
        fallback_start = ((best_context.payload or {}).get("start") if best_context else None)
        answer, kept, dropped, used_fallback = _enforce_citations(
            answer, sorted_results, fallback_start=fallback_start
        )
        metrics.record_answer(kept, dropped, used_fallback)
        print(
            f"[Cite] {kept} citation(s) kept, {dropped} dropped"
            + (", 1 fallback added" if used_fallback else "")
        )

        print(answer)

        max_response_timestamps = 8  # hard cap so a very long tail of similar scores can't return everything

        if summary_mode:
            # Summaries intentionally cover the whole video; just cap count.
            top_matches = sorted_results[:max_response_timestamps]
        else:
            # Same score-filtered set used to build the LLM's context, so
            # badges always match what the answer was actually grounded in.
            RELEVANT_TS_MIN_SCORE = 0.30
            relevant_for_timestamps = [
                r for r in context_candidates if getattr(r, "score", 0) >= RELEVANT_TS_MIN_SCORE
            ]
            if not relevant_for_timestamps:
                # Nothing cleared the bar -- fall back to the single best match
                # instead of showing no timestamps at all.
                best = max(context_candidates, key=lambda r: getattr(r, "score", 0), default=None)
                relevant_for_timestamps = [best] if best is not None else []

            # Adaptive cutoff instead of a fixed top-N: keep every match whose
            # score is within a relative band of the single best score. A pure
            # "largest gap" cutoff was too fragile -- one standout top match
            # (e.g. a near word-for-word segment) creates a huge first gap and
            # wrongly discards a whole cluster of other equally relevant hits
            # sitting just below it.
            by_score = sorted(relevant_for_timestamps, key=lambda r: getattr(r, "score", 0), reverse=True)
            RELATIVE_SCORE_BAND = 0.85  # keep anything scoring >= 85% of the top score
            top_score = getattr(by_score[0], "score", 0) if by_score else 0
            by_score = [r for r in by_score if getattr(r, "score", 0) >= top_score * RELATIVE_SCORE_BAND]
            top_matches = sorted(
                by_score[:max_response_timestamps],
                key=lambda r: r.payload.get("start") or 0,
            )

        seen_starts = set()
        answer_timestamps = []

        def _dedupe_timestamps(items, tolerance=2.0):
            """Drop pills that point at the same moment."""
            kept = []
            for item in sorted(items, key=lambda x: x.get("start") or 0):
                start = item.get("start")
                if start is None:
                    continue
                if any(abs(start - other["start"]) < tolerance for other in kept):
                    continue
                kept.append(item)
            return kept

        # Best source when the question is about examples: match each known
        # example to the excerpt that discusses it, then snap that label to a
        # real segment. The examples are already identified from the slides, so
        # this only asks "where is this one explained?" -- a far narrower
        # question than "find the example in the video".
        if not summary_mode and all_points and _asks_for_examples(question):
            try:
                labelled = _example_chunks(all_points)
                if len(labelled) < 2:
                    # The regex only recognises headings and file names it has
                    # seen. Ask the model what the screen actually shows: that
                    # works for any language, any file type, and for lessons
                    # with inline code and no files at all.
                    found_examples = _cached_examples(current_video_id, all_points)
                    labelled = [(item["name"], None) for item in found_examples]
                    print(f"[Cite] using {len(labelled)} model-found examples")
                if len(labelled) >= 2:
                    # Both kinds of excerpt are needed, for different reasons:
                    # the on-screen chunks say which examples exist (code on a
                    # slide is never spoken aloud), and the speech says when each
                    # one is explained. Only the speech carries a time now, so the
                    # model cannot answer "it is shown at 0:20" any more.
                    #
                    # Measured on a 13-minute Greek lecture: 4 of 4 examples
                    # mapped to 4 distinct speech moments (3:07, 11:08, 11:19,
                    # 12:39), which is exactly what was asked for.
                    # The whole timeline, not the retrieved context. A retrieved
                    # window is a dozen segments around the question, and the
                    # moment that explains a given example is usually elsewhere:
                    # the examples sit on one slide while the lecturer explains
                    # them minutes later. Against the full timeline this mapped
                    # 4 of 4 examples to 4 distinct moments; against the retrieved
                    # window it mapped none.
                    timeline_lines = []
                    for point in sorted(
                        all_points, key=lambda p: p.payload.get("start") or 0
                    ):
                        text = (point.payload.get("text") or "").strip()
                        if not text:
                            continue
                        if text.lstrip().startswith("[on screen]"):
                            timeline_lines.append(text)
                        else:
                            timeline_lines.append(
                                f"[{_mmss(point.payload.get('start'))}-"
                                f"{_mmss(point.payload.get('end'))}] {text}"
                            )
                    mapping = map_examples_to_excerpts(
                        [name for name, _ in labelled], "\n".join(timeline_lines)
                    )
                    resolved = []
                    for name, _ in labelled:
                        label = mapping.get(name)
                        # Resolve against every point, not the retrieved window:
                        # the moment that explains an example is usually outside
                        # it, and a mapped label pointing there returned None.
                        moment = _excerpt_time(label, all_points) if label else None
                        if moment is not None and all(abs(moment - x) > 1.0 for x in resolved):
                            resolved.append(moment)
                            print(f"[Cite] {name} -> {label} -> {int(moment)}s")
                    if len(resolved) >= 2:
                        answer_timestamps = [
                            {"start": moment, "end": moment + 9.0}
                            for moment in sorted(resolved)
                        ]
                        print(f"[Cite] {len(resolved)} example timestamps from mapping")
            except Exception as mapping_error:
                print(f"[Cite] example mapping skipped: {mapping_error}")

        if not summary_mode and not answer_timestamps and all_points and current_video_id:
            try:
                example_times = _example_timestamps(
                    FRAMES_DIR / current_video_id, all_points, answer
                )
                if not example_times:
                    example_times = _example_moments(answer, all_points)
                # Deliberately NOT falling back to _ocr_example_timestamps: the
                # on-screen timestamp of an example is when its slide appeared,
                # which for a slide visible from the start is the same for every
                # example (0:20 four times). Showing that is worse than showing
                # nothing, because it looks authoritative and is wrong.
                if len(example_times) >= 2:
                    answer_timestamps = [
                        {"start": moment, "end": moment + 9.0}
                        for moment in example_times
                    ]
                    print(
                        f"[Cite] {len(example_times)} examples -> "
                        f"{[int(t) for t in example_times]}"
                    )
            except Exception as example_error:
                print(f"[Cite] example matching failed: {example_error}")
        if not summary_mode and not answer_timestamps:
            for r in top_matches:
                start = r.payload.get("start")
                if start is None or start in seen_starts:
                    continue
                seen_starts.add(start)
                answer_timestamps.append({"start": start, "end": r.payload.get("end")})
            answer_timestamps.sort(key=lambda item: item["start"])

        answer_timestamps = _dedupe_timestamps(answer_timestamps)

        return {
            "answer": answer,
            "timestamps": answer_timestamps,
            "text_results": [
                {
                    "text": r.payload.get("text"),
                    "start": r.payload.get("start"),
                    "end": r.payload.get("end"),
                    "score": getattr(r, 'score', None),
                }
                for r in text_results
            ],
        }
    except HTTPException:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Documents: PDF, PowerPoint and Word analysis.
#
# Same shape as a video: extract -> chunk -> embed -> index -> ask with
# citations. What changes is the unit (a page instead of a second) and therefore
# the citation format (`p. 12` instead of `12:40`). Everything downstream --
# the MiniLM embeddings, the Qdrant collection, the hybrid rerank -- is shared,
# so a document is just another `video_id` whose points carry a page number.
# ---------------------------------------------------------------------------

DOCS_DIR = BASE_DIR / "documents"
DOCS_DIR.mkdir(parents=True, exist_ok=True)

# The uploaded file itself, kept beside the text it produced. R2 is where the
# bytes are served from while they are there; this is what makes a conversation
# still show its pages after the sweeper has emptied the bucket.
DOC_FILES_DIR = DOCS_DIR / "files"
DOC_FILES_DIR.mkdir(parents=True, exist_ok=True)


def _kept_document_path(doc_id: str, suffix: str = "") -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "", str(doc_id or ""))
    return DOC_FILES_DIR / f"{safe}{suffix or ''}"


def _kept_document(doc_id: str):
    for candidate in DOC_FILES_DIR.glob(f"{re.sub(r'[^A-Za-z0-9._-]', '', str(doc_id or ''))}.*"):
        return candidate
    return None

# Conversation history, per document. One JSON file per document holding every
# chat and its messages, so reopening a document shows the conversations the
# student actually had instead of a blank panel. Same shape as the other stores:
# a dict at the top, replaced atomically, guarded by a lock.
CHATS_DIR = BASE_DIR / "chats"
CHATS_DIR.mkdir(parents=True, exist_ok=True)

MAX_DOCUMENT_BYTES = 40 * 1024 * 1024

_DOCUMENT_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class ChatRequest(BaseModel):
    question: str
    history: list[dict] | None = None
    # When set, the exchange is stored in that conversation; when absent, a new
    # one is created, so a reader who asks something before uploading anything
    # still finds it in the sidebar tomorrow.
    chat_id: str | None = None


class ConversationUpdate(BaseModel):
    title: str | None = None
    document_id: str | None = None
    video_id: str | None = None
    pinned: bool | None = None


# What the model is told when the composer has no material behind it. The point
# is that it answers *the reader*, not a template: it can apologise, ask which
# file they meant, or point out that a phrase is not a file -- but it must never
# answer a content question from thin air.
_NO_MATERIAL_PROMPT = (
    "You are ChronoMark, a reading assistant: people upload a document or a recording "
    "and you answer from what is inside it.\n\n"
    "In this conversation nothing has been uploaded yet. There is no document and no "
    "recording, so you genuinely do not know anything about their material, their work, "
    "their course or their life -- and you must never invent it, never invent sources or "
    "page numbers, and never answer a content question out of thin air.\n\n"
    "How to reply: answer the person, not a template. One or two sentences. Read what "
    "they actually wrote and respond to that specific thing with a little personality -- "
    "dry, warm, a touch of wit, like a colleague who has not been given the file yet. "
    "Say plainly that you cannot know it because nothing has been uploaded, and turn it "
    "into an invitation: a PDF, a deck or a recording would give you something real to "
    "talk about. If they ask who they are, do not guess a name back at them -- tell them "
    "you are not a directory and that the interesting answer is in a file they have not "
    "sent yet. Do not lecture, do not list every format, do not repeat the same wording "
    "twice, and do not ask more than one question back.\n\n"
    "One more rule, and it is absolute: do not answer questions of knowledge either. "
    "Arithmetic, a fact, a definition, a translation, a date, a name -- you do not "
    "answer any of it here, even when you are certain. You are not a general assistant "
    "in this state; you are the person who has not been given the file yet. Say you are "
    "not going to guess, and ask for one.\n\n"
    "Reply in the language of their message. If the message is not in a recognisable "
    "language (a typo, random characters), answer in English."
)


class DocumentQuestion(BaseModel):
    question: str
    doc_id: str
    history: list[dict] | None = None
    # When the question comes from a conversation, the turn is stored there --
    # one history for the reader, whatever the answer was made of.
    conversation_id: str | None = None
    # When set, the turn is stored in that conversation so the sidebar can list
    # and reopen it later.
    chat_id: str | None = None


class DocumentStudyRequest(BaseModel):
    doc_id: str
    count: int | None = None
    language: str | None = None


def _origin_matches(origin: str, patterns: list) -> bool:
    """Does this site origin appear in the bucket's AllowedOrigins?

    R2 accepts two wildcard shapes and both are in use: a bare "*" and a
    subdomain pattern such as "https://*.pages.dev". Comparing the strings alone
    silently misses the second one.
    """
    for raw in patterns:
        pattern = str(raw or "").strip().rstrip("/")
        if not pattern:
            continue
        if pattern == "*" or pattern == origin:
            return True
        if pattern.startswith("https://*.") and origin.startswith("https://"):
            suffix = pattern[len("https://*"):]  # ".pages.dev"
            host = origin[len("https://"):].split("/")[0]
            if host.endswith(suffix) and host != suffix.lstrip("."):
                return True
    return False


def _document_cors_available() -> bool:
    """Whether the browser may read PDFs straight from R2.

    Checked once and cached: if the bucket has a GET rule for this site, the
    viewer takes a presigned URL and the VPS never touches the bytes. If not,
    the API relays them. The check is retried every ten minutes so granting the
    permission in Cloudflare takes effect without a redeploy.

    R2_DOCUMENT_DIRECT overrides the check, because a token with only object
    permissions cannot call GetBucketCors and would always fall back to the
    relay even when the policy is correct:
      auto   (default) trust the bucket policy when it can be read
      always skip the check, serve documents straight from R2
      never  always relay through the API
    """
    mode = (os.getenv("R2_DOCUMENT_DIRECT") or "auto").strip().lower()
    if mode == "never":
        return False
    if mode == "always":
        return True

    global _DOC_CORS_CACHE
    now = time.time()
    cached = _DOC_CORS_CACHE
    if cached and now - cached[0] < 600:
        return cached[1]

    origin = os.getenv("PUBLIC_SITE_ORIGIN", "https://chronomark.0digital.xyz").rstrip("/")
    available = False
    rules = r2_service.bucket_cors_rules()
    for rule in rules or []:
        methods = [str(method).upper() for method in (rule.get("AllowedMethods") or [])]
        origins = list(rule.get("AllowedOrigins") or [])
        if "GET" in methods and _origin_matches(origin, origins):
            available = True
            break
    if available:
        print(f"[R2] CORS allows {origin} to read documents directly")

    _DOC_CORS_CACHE = (now, available)
    return available


_DOC_CORS_CACHE = (0.0, False)


def _document_language(document: dict) -> str:
    """The language the document itself is written in.

    Stored at ingest when possible; older records fall back to reading the first
    pages. Answers, quizzes and flashcards follow this, so a Greek handout is
    always explained in Greek even when the student types the question in
    English.
    """
    stored = str(document.get("language") or "").strip()
    if stored:
        return stored
    sample = " ".join(
        (page.get("text") or "")[:800] for page in (document.get("pages") or [])[:3]
    )
    if not sample.strip():
        return ""
    return _detect_transcript_language(sample)


def _document_meta_path(doc_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "", str(doc_id or ""))
    if not safe:
        raise HTTPException(status_code=400, detail="invalid doc_id")
    return DOCS_DIR / f"{safe}.json"


def _load_document(doc_id: str) -> dict:
    path = _document_meta_path(doc_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Document metadata unreadable: {error}")


def _save_document(document: dict) -> None:
    path = _document_meta_path(document["doc_id"])
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False)
    tmp.replace(path)


# How far back a re-upload counts as the same file. Ten minutes is longer
# than any double submit and shorter than a reader's second look.
_DUPLICATE_WINDOW_SECONDS = 90


def _recent_duplicate(user_id: str, file_name: str) -> dict | None:
    """The document this file already became, if it was uploaded moments ago."""
    wanted = str(file_name or "").strip()
    if not wanted:
        return None
    cutoff = time.time() - _DUPLICATE_WINDOW_SECONDS
    for path in DOCS_DIR.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                document = json.load(handle)
        except Exception:
            continue
        if str(document.get("owner_id") or "") != str(user_id):
            continue
        if str(document.get("file_name") or "").strip() != wanted:
            continue
        if float(document.get("created_at") or 0) >= cutoff:
            return document
    return None


def _current_user(request) -> str:
    """The verified user id, or a 401 -- never an empty string.

    The gate middleware already refused a tokenless request on every guarded
    route; this is the other half. The route has to know *whose* library it is
    looking at, and a missing subject here means the middleware let something
    through that it should not have.
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to use this feature.")
    return str(user_id)


def _owned_document(doc_id: str, user_id: str, allow_purged: bool = False) -> dict:
    """The document, but only if this account uploaded it.

    Someone else's document answers exactly like a document that does not
    exist: 404, not 403. A 403 would confirm the id is real, which is the one
    bit an enumerating client is after.
    """
    document = _load_document(doc_id)
    if str(document.get("owner_id") or "") != str(user_id):
        raise HTTPException(status_code=404, detail="Document not found")
    if document.get("purged_at") and not allow_purged:
        raise HTTPException(
            status_code=410,
            detail="This file was deleted after the retention period. Your chat history is still available.",
        )
    return document


# --- pre-analysed study summary ----------------------------------------------
# The summary is the one question every reader asks, and it is also the most
# expensive one: the whole handout goes into the model at once. So it is
# generated once, inside the upload job, right after indexing -- while the
# progress bar still says the document is being prepared -- and the ask endpoint
# serves the summary button from it instead of rebuilding the same 90k-character
# prompt on demand. Anything else is still answered at the moment it is asked.
#
# Held in memory and mirrored to a sidecar file beside the document, so a
# container restart does not throw the work away. Sidecars live in their own
# directory: the document listing reads every *.json in DOCS_DIR.

_SUMMARY_CACHE: dict[str, dict] = {}
_SUMMARY_LOCK = threading.Lock()
SUMMARY_DIR = DOCS_DIR / "summaries"


def _summary_path(doc_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "", str(doc_id or ""))
    return SUMMARY_DIR / f"{safe}.json"


def _load_cached_summary(doc_id: str) -> dict | None:
    with _SUMMARY_LOCK:
        cached = _SUMMARY_CACHE.get(doc_id)
    if cached:
        return cached
    path = _summary_path(doc_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            cached = json.load(handle)
    except Exception as error:
        print(f"[Docs] cached summary unreadable: {error}")
        return None
    if not isinstance(cached, dict) or not cached.get("answer"):
        return None
    with _SUMMARY_LOCK:
        _SUMMARY_CACHE[doc_id] = cached
    return cached


# --- chapters ----------------------------------------------------------------
# The walkthrough needs the document's own structure, and it needs the same
# structure every time: a model asked to "continue" from memory answered with
# four sections in one reply on Monday and repeated itself on Tuesday. The
# outline is therefore read once from the pages, stored next to the document and
# reused, and each reply is given exactly the pages of one chapter.

_CHAPTERS_CACHE: dict[str, list] = {}
_CHAPTERS_LOCK = threading.Lock()
CHAPTERS_DIR = DOCS_DIR / "chapters"


def _chapters_path(doc_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "", str(doc_id or ""))
    return CHAPTERS_DIR / f"{safe}.json"


def _payload_page(payload: dict | None):
    payload = payload or {}
    page = payload.get("page")
    if page is None:
        start = payload.get("start")
        page = int(start) if isinstance(start, (int, float)) else None
    return page


def _document_chapters_cached(doc_id: str, context: str, language: str) -> list:
    with _CHAPTERS_LOCK:
        cached = _CHAPTERS_CACHE.get(doc_id)
    if cached:
        return cached
    path = _chapters_path(doc_id)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as handle:
                stored = json.load(handle)
            if isinstance(stored, list) and stored:
                with _CHAPTERS_LOCK:
                    _CHAPTERS_CACHE[doc_id] = stored
                return stored
        except Exception as error:
            print(f"[Docs] chapter outline unreadable: {error}")
    try:
        chapters = document_chapters(context, language)
    except Exception as error:  # noqa: BLE001 - a walkthrough without an outline still works
        print(f"[Docs] could not read the chapter structure: {error}")
        return []
    if not chapters:
        return []
    with _CHAPTERS_LOCK:
        _CHAPTERS_CACHE[doc_id] = chapters
    try:
        CHAPTERS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(chapters, handle, ensure_ascii=False)
        tmp.replace(path)
    except Exception as error:
        print(f"[Docs] could not store the chapter outline: {error}")
    return chapters


def _chapter_index(chapters: list, question: str, history: list) -> int:
    """Which chapter this message is about."""

    def which(text, headings_only=False):
        lowered = " ".join(str(text or "").lower().split())
        if headings_only:
            # Only what the answer actually covered: its closing paragraph names
            # the chapter that comes after it, and matching that would skip one.
            lowered = " ".join(
                " ".join(line.split()).lower()
                for line in str(text or "").splitlines()
                if line.lstrip().startswith("#")
            )
        found = None
        for position, chapter in enumerate(chapters):
            title = " ".join(str(chapter.get("title") or "").lower().split())
            if title and title in lowered:
                found = position
        return found

    named = which(question)
    if named is not None:
        return named
    lowered = str(question or "").lower()
    if any(
        word in lowered
        for word in (
            "continue",
            "go on",
            "next",
            "συνέχ",
            "συνεχ",
            "επόμεν",
            "επομεν",
            "παρακάτω",
            "παρακατω",
        )
    ):
        for turn in reversed(history or []):
            if turn.get("role") != "assistant":
                continue
            position = which(turn.get("content"), headings_only=True)
            if position is not None:
                return min(position + 1, len(chapters) - 1)
        return 1 if len(chapters) > 1 else 0
    return 0


def _store_cached_summary(
    doc_id: str,
    answer: str,
    truncated: bool,
    next_chapter: str | None = None,
    at_end: bool = False,
) -> None:
    payload = {
        "answer": answer,
        "truncated": bool(truncated),
        "next_chapter": next_chapter,
        "at_end": bool(at_end),
        "created_at": time.time(),
    }
    with _SUMMARY_LOCK:
        _SUMMARY_CACHE[doc_id] = payload
    try:
        SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
        path = _summary_path(doc_id)
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        tmp.replace(path)
    except Exception as error:
        print(f"[Docs] could not persist summary: {error}")


def _page_of_payload(payload: dict):
    page = (payload or {}).get("page")
    if page is None:
        start = (payload or {}).get("start")
        page = int(start) if isinstance(start, (int, float)) else None
    return page


def _document_summary_context(chunks):
    """The whole handout in page order, thinned only when it will not fit."""
    total_chars = sum(len((r.payload.get("text") or "")) for r in chunks)
    if total_chars <= 90_000:
        selected = list(chunks)
    else:
        budget = max(20, int(len(chunks) * 90_000 / total_chars))
        step = len(chunks) / budget
        selected = [chunks[int(i * step)] for i in range(budget)]
    ordered = sorted(
        selected,
        key=lambda r: (
            (r.payload or {}).get("page") or 0,
            (r.payload or {}).get("chunk_index") or 0,
        ),
    )
    lines = []
    for item in ordered:
        text = (item.payload.get("text") or "").strip()
        if not text:
            continue
        # Figure chunks already carry their page ("[figure p.7]").
        lines.append(text if text.startswith("[figure") else f"[p.{_page_of_payload(item.payload)}] {text}")
    pages = {_page_of_payload(item.payload) for item in ordered}
    return "\n".join(lines), {page for page in pages if page is not None}, len(selected), total_chars


def _warm_document_summary(document: dict) -> None:
    """Generate the study summary now, so the button answers instantly."""
    doc_id = document.get("doc_id")
    if not doc_id:
        return
    chunks = _document_context_chunks(doc_id)
    if not chunks:
        return
    context, available_pages, selected, total_chars = _document_summary_context(chunks)
    if not context.strip():
        return

    answer_language = _document_language(document) or "English"
    question = (
        "δώσε μια περίληψη του εγγράφου με τα βασικά σημεία"
        if answer_language == "Greek"
        else "give a summary of the document with the main points"
    )
    print(
        f"[Docs] pre-analysis: {selected}/{len(chunks)} chunks, {total_chars} chars, "
        f"answering in {answer_language}"
    )
    # The upload is also when the chapter structure is read, so the first click
    # on Summarize knows what chapter two is called and does not pay for it.
    chapters = _document_chapters_cached(doc_id, context, answer_language)
    chapter_title = chapters[0]["title"] if chapters else None
    next_title = chapters[1]["title"] if len(chapters) > 1 else None
    at_end = bool(chapters) and next_title is None
    if chapters:
        chapter = chapters[0]
        start_page, end_page = chapter["start_page"], chapter["end_page"]
        context = "\n".join(
            text
            for r in chunks
            if _payload_page(r.payload) is None
            or start_page <= (_payload_page(r.payload) or 0) <= end_page
            for text in [((r.payload or {}).get("text") or "").strip()]
            if text
        ) or context
    answer, truncated = ask_document(
        question=question,
        context=context,
        history=[],
        answer_language=answer_language,
        summary_mode=True,
        transcript_available=True,
        chapter_title=chapter_title,
        next_chapter=next_title,
    )
    answer, marker_next, marker_end = split_chapter_marker(answer)
    if marker_next:
        next_title, at_end = marker_next, False
    elif marker_end:
        next_title, at_end = None, True
    answer, kept, _dropped, _fallback = _enforce_page_citations(
        answer, available_pages, fallback_page=None
    )
    print(f"[Docs] pre-analysis summary ready: {len(answer)} chars, {kept} citation(s)")
    _store_cached_summary(doc_id, answer, truncated, next_title, at_end)


# --- conversations -----------------------------------------------------------

_CHAT_LOCK = threading.Lock()


class ChatCreate(BaseModel):
    title: str | None = None


def _chats_path(doc_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "", str(doc_id or ""))
    if not safe:
        raise HTTPException(status_code=400, detail="invalid doc_id")
    return CHATS_DIR / f"{safe}.json"


def _load_chats(doc_id: str) -> dict:
    path = _chats_path(doc_id)
    if not path.exists():
        return {"chats": []}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {"chats": []}
    if not isinstance(data, dict) or not isinstance(data.get("chats"), list):
        return {"chats": []}
    return data


def _save_chats(doc_id: str, data: dict) -> None:
    path = _chats_path(doc_id)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)
    tmp.replace(path)


def _find_chat(data: dict, chat_id: str):
    for chat in data.get("chats") or []:
        if chat.get("id") == chat_id:
            return chat
    return None


def _ensure_chat(doc_id: str, chat_id: str | None, question: str = "") -> dict:
    """Return the conversation, creating it on first use.

    The title comes from the first question, which is how every chat list in
    this class of product names a conversation, and it is truncated so the
    sidebar cannot break.
    """
    with _CHAT_LOCK:
        data = _load_chats(doc_id)
        chat = _find_chat(data, chat_id) if chat_id else None
        if chat is not None:
            return chat

        identifier = chat_id or f"chat_{uuid.uuid4().hex[:10]}"
        title = (question or "New chat").strip()
        title = (title[:60] + "…") if len(title) > 60 else (title or "New chat")
        chat = {
            "id": identifier,
            "title": title,
            "created_at": time.time(),
            "updated_at": time.time(),
            "messages": [],
        }
        data.setdefault("chats", []).insert(0, chat)
        _save_chats(doc_id, data)
        return chat


def _append_turn(doc_id: str, chat_id: str | None, question: str, answer: str, pages: list) -> None:
    if not chat_id:
        return
    with _CHAT_LOCK:
        data = _load_chats(doc_id)
        chat = _find_chat(data, chat_id)
        if chat is None:
            return
        messages = chat.setdefault("messages", [])
        # The first question names the conversation, the way a chat app titles a
        # thread, instead of leaving every entry as "New chat".
        if not messages and (chat.get("title") or "New chat") in ("New chat", ""):
            title = (question or "New chat").strip()
            chat["title"] = (title[:60] + "…") if len(title) > 60 else (title or "New chat")
        messages.append({"role": "user", "content": question, "at": time.time()})
        messages.append(
            {
                "role": "assistant",
                "content": answer,
                "pages": pages,
                "at": time.time(),
            }
        )
        chat["updated_at"] = time.time()
        # Keep the list ordered like a chat app: most recent conversation first.
        data["chats"].sort(key=lambda item: item.get("updated_at") or 0, reverse=True)
        _save_chats(doc_id, data)


def _ocr_page_bytes(data: bytes, mime: str) -> str:
    """Vision OCR for a scanned page's embedded image.

    Reuses the frame reader: a scanned handout page and a lecture slide are the
    same problem, and the model already reads one reliably.
    """
    encoded = base64.b64encode(data).decode("ascii")
    return transcribe_image(f"data:{mime};base64,{encoded}")


def _process_document_job(
    job_id: str,
    doc_id: str,
    temp_path: str,
    file_name: str,
    file_key: str,
    start_time: float,
    owner_id: str = "",
):
    """Parse a document, chunk it, embed the chunks and index them by page."""
    # Waits for a slot rather than starting a third heavy job: a queued upload
    # that finishes slowly is better than three that all thrash the box.
    if not _DOC_JOB_SLOTS.acquire(timeout=900):
        _set_job_status(
            job_id,
            status="failed",
            stage="failed",
            progress=100,
            error="The server is busy with other uploads. Please try again in a few minutes.",
        )
        Path(temp_path).unlink(missing_ok=True)
        return
    try:
        _set_job_status(job_id, status="processing", stage="parsing", progress=20)
        extracted = document_tools.extract_document(
            Path(temp_path), file_name=file_name, image_ocr=_ocr_page_bytes
        )
        print(
            f"[Docs] {file_name}: {extracted['page_count']} pages, "
            f"{sum(len(p['text']) for p in extracted['pages'])} chars extracted"
        )

        _set_job_status(job_id, status="processing", stage="chunking", progress=40)
        chunks = document_tools.chunk_pages(extracted["pages"])
        if not chunks:
            raise ValueError("no readable text found in this document")
        print(f"[Docs] {len(chunks)} chunks from {len(extracted['pages'])} pages")

        # Figures are invisible to text extraction, so each page's image is read
        # once and indexed as a chunk. A question about "the tree in Figure 14"
        # then has the tree itself to reason about, and the answer can draw it.
        _set_job_status(job_id, status="processing", stage="reading_figures", progress=52)
        figure_blocks = []
        try:
            figures = document_tools.extract_figure_images(Path(temp_path))
            if figures:
                print(f"[Docs] reading {len(figures)} figure(s)")

            def _read_figure(figure):
                """One vision call. executor.map keeps the pages in order."""
                try:
                    encoded = base64.b64encode(figure["data"]).decode("ascii")
                    description = describe_figure(f"data:{figure['mime']};base64,{encoded}")
                except Exception as figure_error:
                    print(f"[Docs] figure p.{figure['page']} skipped: {figure_error}")
                    return None
                if not description:
                    return None
                print(f"[Docs] figure p.{figure['page']}: {len(description)} chars")
                return {
                    "page": figure["page"],
                    "heading": f"figure p.{figure['page']}",
                    "text": f"[figure p.{figure['page']}] {description}",
                }

            if figures:
                started = time.perf_counter()
                with ThreadPoolExecutor(
                    max_workers=min(FIGURE_WORKERS, len(figures))
                ) as pool:
                    described = list(pool.map(_read_figure, figures))
                figure_blocks = [block for block in described if block]
                print(
                    f"[Docs] {len(figure_blocks)}/{len(figures)} figure(s) read in "
                    f"{time.perf_counter() - started:.1f}s"
                )
        except Exception as figure_error:
            print(f"[Docs] figure pass skipped: {figure_error}")

        chunks.extend(figure_blocks)

        _set_job_status(job_id, status="processing", stage="embedding", progress=65)
        segments = [
            {"text": chunk["text"], "timestamp": [chunk["page"], chunk["page"]], "page": chunk["page"]}
            for chunk in chunks
        ]
        embeddings = create_embeddings_from_transcript({"segments": segments})

        # Re-indexing the same document replaces its points instead of
        # duplicating them.
        ensure_collections()
        client.delete(
            collection_name=TEXT_COLLECTION,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="video_id", match=qmodels.MatchValue(value=doc_id)
                        )
                    ]
                )
            ),
        )
        store_text_embeddings(
            doc_id,
            embeddings,
            id_prefix="doc",
            extra_payload={"source_type": "document", "file_key": file_key, "file_name": file_name},
        )
        print(f"[Docs] indexed {len(embeddings)} page chunks for {doc_id}")

        _set_job_status(job_id, status="processing", stage="finalizing", progress=90)
        document = {
            "doc_id": doc_id,
            # Whose library this belongs to. Every read is checked against it.
            "owner_id": owner_id,
            "file_name": file_name,
            "file_key": file_key,
            "kind": extracted["kind"],
            "page_count": extracted["page_count"],
            "indexed_pages": sorted({p["page"] for p in extracted["pages"]}),
            "chunk_count": len(chunks),
            "figure_count": len(figure_blocks),
            "created_at": time.time(),
            # Stored once here so every later answer, quiz and flashcard follows
            # the document's own language instead of the question's.
            "language": _detect_transcript_language(
                " ".join((page.get("text") or "")[:800] for page in extracted["pages"][:3])
            ),
            "pages": extracted["pages"],
        }
        _save_document(document)

        # No pre-analysis: the upload used to run a whole-document summary here
        # so the "Summarize" button could answer from a cache, and it cost 20-40
        # seconds on every upload. The button asks the model at the moment it is
        # pressed now, and the document is announced as ready as soon as its
        # pages are indexed.

        total_time = time.perf_counter() - start_time
        _set_job_status(
            job_id,
            status="completed",
            stage="completed",
            progress=100,
            result={
                "doc_id": doc_id,
                "file_name": file_name,
                "file_key": file_key,
                "kind": extracted["kind"],
                "page_count": extracted["page_count"],
                "indexed_pages": document["indexed_pages"],
                "chunk_count": len(chunks),
                "figure_count": len(figure_blocks),
                "total_time_sec": round(total_time, 1),
            },
        )
        print(f"[Docs] {file_name} ready in {total_time:.1f}s")
    except Exception as error:
        _set_job_status(job_id, status="failed", stage="failed", progress=100, error=str(error))
        print(f"[Docs] pipeline failed: {error}")
    finally:
        try:
            Path(temp_path).unlink(missing_ok=True)
        except OSError:
            pass
        try:
            _JOB_SLOTS.release()
        except ValueError:
            pass


@app.post("/api/upload-document")
async def api_upload_document(
    request: Request, background_tasks: BackgroundTasks, file_upload: UploadFile
):
    """Accept a PDF/PPTX/DOCX, store it in R2, then parse and index it."""
    user_id = _current_user(request)
    try:
        document_prefix = user_scope.directory("documents", user_id)
    except (ValueError, RuntimeError) as scope_error:
        raise HTTPException(status_code=503, detail=str(scope_error))

    if not file_upload.filename:
        raise HTTPException(status_code=400, detail="Missing uploaded filename")

    suffix = Path(file_upload.filename).suffix.lower()
    if suffix not in _DOCUMENT_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Only PDF, PPTX and DOCX files are supported",
        )

    # The id comes before the upload now: the local copy is named after it, so
    # the pages are readable even if the bucket is empty by the time the reader
    # comes back.
    doc_id = f"doc_{uuid.uuid4().hex[:10]}"
    kept_path = _kept_document_path(doc_id, suffix)

    # A second submit of the same file -- a double click, a retried fetch -- is
    # not a second document, and used to become one: two doc_ids with the same
    # name, two copies in R2, two rows in the library.
    duplicate = _recent_duplicate(user_id, file_upload.filename)
    if duplicate is not None:
        print(f"[Upload] duplicate of {duplicate['doc_id']}: {file_upload.filename}")
        return {
            "job_id": None,
            "doc_id": duplicate["doc_id"],
            "status": "completed",
            "stage": "completed",
            "progress": 100,
            "duplicate": True,
            "file_name": duplicate.get("file_name"),
        }

    start_time = time.perf_counter()

    # The temp copy lives in the shared uploads directory: the worker is a
    # different process (and container) and has to be able to open it.
    handle = tempfile.NamedTemporaryFile(
        prefix="chronomark-doc-", suffix=suffix, dir=str(job_store.UPLOAD_DIR), delete=False
    )
    temp_path = Path(handle.name)
    size = 0
    try:
        file_upload.file.seek(0)
        while True:
            chunk = file_upload.file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_DOCUMENT_BYTES:
                raise HTTPException(status_code=413, detail="Document is larger than 40 MB")
            handle.write(chunk)
        handle.close()
        if size == 0:
            raise HTTPException(status_code=400, detail="Empty upload")

        # The original stays in R2 so the viewer can render the real PDF.
        # Keep the file itself: shutil.copy so the worker still gets its temp
        # path, and the reader keeps the pages forever (until they delete it).
        try:
            import shutil

            shutil.copyfile(temp_path, kept_path)
        except Exception as keep_error:
            print(f"[Upload] could not keep a local copy of {kept_path.name}: {keep_error}")

        with open(temp_path, "rb") as source:
            try:
                uploaded = await run_in_threadpool(
                    r2_service.upload_stream,
                    source,
                    file_upload.filename,
                    _DOCUMENT_CONTENT_TYPES[suffix],
                    8 * 1024 * 1024,
                    document_prefix,
                )
            except (ValueError, RuntimeError) as error:
                raise HTTPException(status_code=502, detail=f"Document storage failed: {error}")
    except HTTPException:
        try:
            Path(temp_path).unlink(missing_ok=True)
        except OSError:
            pass
        raise
    except Exception as error:
        try:
            Path(temp_path).unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(status_code=500, detail=f"Upload failed: {error}")
    finally:
        try:
            handle.close()
        except Exception:
            pass

    job_id = str(uuid.uuid4())
    job_store.create(
        job_id,
        status="processing",
        stage="queued",
        progress=5,
        doc_id=doc_id,
        kind="document",
    )
    JOBS[job_id] = {
        "job_id": job_id,
        "status": "processing",
        "stage": "queued",
        "progress": 5,
        "error": None,
        "result": None,
    }
    # The answer to the uploader is this line: the worker does the slow part.
    job_store.enqueue(
        {
            "kind": "document",
            "job_id": job_id,
            "doc_id": doc_id,
            "owner_id": user_id,
            "temp_path": str(temp_path),
            "file_name": file_upload.filename,
            "file_key": uploaded["file_key"],
        }
    )
    print(f"[Upload] queued document job {job_id} ({file_upload.filename})")

    return {
        "job_id": job_id,
        "doc_id": doc_id,
        "status": "processing",
        "stage": "queued",
        "progress": 5,
        "status_url": f"/upload-status/{job_id}",
        "file_key": uploaded["file_key"],
        "size": size,
    }


@app.get("/api/documents")
async def api_list_documents(request: Request):
    """This account's documents, newest first, without the page texts."""
    user_id = _current_user(request)
    items = []
    for path in DOCS_DIR.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                document = json.load(handle)
        except Exception:
            continue
        if str(document.get("owner_id") or "") != user_id:
            continue
        items.append(
            {
                "doc_id": document.get("doc_id"),
                "file_name": document.get("file_name"),
                "kind": document.get("kind"),
                "page_count": document.get("page_count"),
                "chunk_count": document.get("chunk_count"),
                "created_at": document.get("created_at"),
                "purged": bool(document.get("purged_at")),
            }
        )
    items.sort(key=lambda item: item.get("created_at") or 0, reverse=True)
    return {"documents": items}


def _document_file_url(document: dict):
    """Where the viewer iframe reads the PDF from, or None once it has aged out.

    Straight from R2 when the bucket allows this origin, relayed by the API
    otherwise. The relay is a fallback for the bucket, not for the reader: an
    iframe sends no Authorization header, so the relayed URL carries the
    expiring signature this authenticated request just minted.
    """
    kept = _kept_document(document.get("doc_id"))
    key = document.get("file_key")
    if kept is not None:
        # The copy on this machine is the document. The bucket copy only ever
        # served it faster. An iframe sends no Authorization header, so the
        # relayed URL carries the expiring signature this authenticated request
        # just minted -- without it the frame rendered a 401 as its content.
        return (
            f"/api/document-file/{document['doc_id']}"
            f"?{auth_guard.sign_media(document['doc_id'])}"
        )
    if document.get("file_available") is False:
        return None
    if key and not r2_service.object_exists(key):
        # The sweeper removed it while this process was not looking: record it,
        # so every later open in the conversation is a sentence instead of a
        # blank frame.
        document["file_available"] = False
        document["file_expired_at"] = time.time()
        try:
            _save_document(document)
        except Exception as error:
            print(f"[Docs] could not mark {document.get('doc_id')} expired: {error}")
        return None
    if _document_cors_available():
        return f"/api/document-stream/{document.get('file_key')}"
    return (
        f"/api/document-file/{document['doc_id']}"
        f"?{auth_guard.sign_media(document['doc_id'])}"
    )


def _authorise_media(request, document: dict, expires=None, sig: str = "") -> None:
    """A header proves the account; a signature proves the URL came from us.

    Either one is enough. A document belonging to someone else is a 401 here
    rather than a 404: the caller already named the document, so there is no id
    left to hide.
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id and str(document.get("owner_id") or "") == str(user_id):
        return
    if auth_guard.media_signature_valid(document.get("doc_id"), expires, sig):
        return
    raise HTTPException(status_code=401, detail="Sign in to use this feature.")


@app.post("/api/chat")
async def api_chat(req: ChatRequest, request: Request):
    """Reply to a message that has no file behind it.

    One canned sentence answered every message before a file was loaded, which
    ignored what the reader wrote and said the same thing again and again. The
    model answers now, under instructions that keep it honest about having
    nothing to read.
    """
    user_id = _current_user(request)
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    record = conversations.get(req.chat_id, user_id) if req.chat_id else None
    if record is None:
        record = conversations.create(user_id)
    first_turn = not (record.get("messages") or [])

    claims = getattr(request.state, "user", None) or {}
    metadata = claims.get("user_metadata") or {}
    reader = (
        (metadata.get("name") or metadata.get("full_name") or "")
        or str(claims.get("email") or "").split("@")[0]
    ).strip()
    system = _NO_MATERIAL_PROMPT
    if reader:
        # Their name, if the account carries one -- one small thing that makes the
        # answer land as written for this person and not for anybody.
        system += f'\n\nThe reader goes by "{reader}"; you may use it once, naturally, not as a greeting.'

    messages = [{"role": "system", "content": system}]
    for turn in (req.history or [])[-8:]:
        if not isinstance(turn, dict):
            continue
        text = str(turn.get("content") or "").strip()
        if not text:
            continue
        role = "assistant" if turn.get("role") == "assistant" else "user"
        messages.append({"role": role, "content": text})
    messages.append({"role": "user", "content": question})

    try:
        # complete_with_continuation returns (text, truncated) -- the truncation
        # flag matters to a cited answer, not to a two-sentence greeting.
        result = await run_in_threadpool(complete_with_continuation, messages, 220, 0.75)
        answer = result[0] if isinstance(result, tuple) else result
    except Exception as error:  # noqa: BLE001 - a dead model must not dead-end the page
        print(f"[Chat] no-material reply failed: {error}")
        answer = (
            "I have nothing to read yet, so I cannot answer that. Send a PDF, PPTX or "
            "DOCX, or a recording (MP4, MKV, MOV, WEBM, M4A, MP3) and ask me again."
        )

    answer = (answer or "").strip()
    try:
        conversations.append_turn(record["id"], user_id, question, answer)
        if first_turn:
            # A name from the answer, not from the question: "hi" is not a title,
            # but what the assistant said back is.
            title = await run_in_threadpool(
                suggest_title, question, answer, question[:60] or "Conversation"
            )
            conversations.set_generated_title(record["id"], user_id, title)
        stored = conversations.get(record["id"], user_id) or record
    except Exception as error:  # noqa: BLE001 - storage must not eat the answer
        print(f"[Chat] could not store the turn: {error}")
        stored = record

    return {"answer": answer, "chat_id": record["id"], "title": stored.get("title")}


@app.get("/api/conversations")
async def api_conversations(request: Request):
    """Conversations that have no file behind them, newest first."""
    return {"conversations": conversations.list_for(_current_user(request))}


@app.post("/api/conversations")
async def api_conversation_create(request: Request):
    user_id = _current_user(request)
    record = conversations.create(user_id)
    return {"chat_id": record["id"], "title": record["title"]}


@app.get("/api/conversations/{chat_id}")
async def api_conversation(chat_id: str, request: Request):
    record = conversations.get(chat_id, _current_user(request))
    if record is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        "chat_id": record["id"],
        "title": record.get("title"),
        "messages": record.get("messages") or [],
        # Which file the conversation is about. Without this the page opened the
        # words and left the pages behind.
        "document_id": record.get("document_id"),
        "video_id": record.get("video_id"),
        "pinned": bool(record.get("pinned")),
    }


@app.patch("/api/conversations/{chat_id}")
async def api_conversation_update(chat_id: str, req: ConversationUpdate, request: Request):
    """Rename it, or bind the file it is about -- one route, because a rename and
    an upload both come from the same conversation that is open."""
    user_id = _current_user(request)
    record = None
    if req.title and req.title.strip():
        record = conversations.rename(chat_id, user_id, req.title)
    if req.document_id:
        record = conversations.attach(chat_id, user_id, "document", req.document_id) or record
    if req.video_id:
        record = conversations.attach(chat_id, user_id, "video", req.video_id) or record
    if req.pinned is not None:
        record = conversations.set_pinned(chat_id, user_id, req.pinned) or record
    if record is None:
        record = conversations.get(chat_id, user_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        "chat_id": record["id"],
        "title": record.get("title"),
        "document_id": record.get("document_id"),
        "video_id": record.get("video_id"),
        "pinned": bool(record.get("pinned")),
    }


@app.delete("/api/conversations/{chat_id}")
async def api_conversation_delete(chat_id: str, request: Request):
    if not conversations.remove(chat_id, _current_user(request)):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"deleted": chat_id}


class AutoTitleRequest(BaseModel):
    doc_id: str | None = None
    video_id: str | None = None


@app.post("/api/conversations/{chat_id}/auto-title")
async def api_conversation_auto_title(
    chat_id: str, req: AutoTitleRequest, request: Request
):
    """Name a conversation after what was uploaded into it.

    "hi" and "New conversation" are not names. The opening of the material is:
    the first pages of a document, the first lines of a transcript. A title the
    reader typed is never replaced.
    """
    user_id = _current_user(request)
    record = conversations.get(chat_id, user_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if record.get("renamed_by_user"):
        return {"chat_id": chat_id, "title": record.get("title"), "generated": False}

    excerpt = ""
    fallback = ""
    if req.doc_id:
        document = _owned_document(req.doc_id, user_id)
        fallback = Path(str(document.get("file_name") or "")).stem
        excerpt = " ".join(
            (page.get("text") or "") for page in (document.get("pages") or [])[:3]
        )
    elif req.video_id:
        if not video_registry.is_owner(req.video_id, user_id):
            raise HTTPException(status_code=404, detail="Video not found")
        entry = video_registry.get(req.video_id) or {}
        keys = entry.get("file_keys") or []
        fallback = (
            Path(r2_service.display_name_for_key(keys[-1])).stem if keys else "Recording"
        )
        try:
            transcript = json.loads(TRANSCRIPTS_PATH.read_text(encoding="utf-8"))
            segments = (transcript.get(req.video_id) or {}).get("segments") or []
            excerpt = " ".join((item.get("text") or "") for item in segments[:12])
        except Exception:
            excerpt = ""
    else:
        raise HTTPException(status_code=400, detail="Nothing to name")

    title = await run_in_threadpool(suggest_title_from_text, excerpt, fallback or "Conversation")
    conversations.set_generated_title(chat_id, user_id, title)
    return {"chat_id": chat_id, "title": title, "generated": True}


@app.get("/api/videos")
async def api_list_videos(request: Request):
    """Every video this account has analysed, newest first.

    The registry exists so a video_id can be proved to belong to someone; the
    same records are the only list of videos that exists, which is why the
    workspace had nothing to show before this endpoint.
    """
    user_id = _current_user(request)
    items = []
    for record in video_registry.records_for(user_id):
        keys = record.get("file_keys") or []
        original = r2_service.display_name_for_key(keys[-1]) if keys else ""
        title = Path(original).stem if original else str(record.get("video_id") or "")
        items.append(
            {
                "video_id": record.get("video_id"),
                "title": title or "Video",
                "created_at": record.get("created_at"),
                # The player needs the key to build its stream URL; it is the
                # caller's own key, and the retention sweeper deletes it after
                # three hours, so this is also how the client learns it is gone.
                "file_key": keys[-1] if keys else None,
                "kind": "video",
            }
        )
    items.sort(key=lambda item: item.get("created_at") or 0, reverse=True)
    return {"videos": items}


@app.get("/api/document/{doc_id}")
async def api_get_document(doc_id: str, request: Request):
    document = _owned_document(doc_id, _current_user(request))
    return {
        "doc_id": document["doc_id"],
        "file_name": document.get("file_name"),
        "file_key": document.get("file_key"),
        "kind": document.get("kind"),
        "page_count": document.get("page_count"),
        "indexed_pages": document.get("indexed_pages") or [],
        "pages": document.get("pages") or [],
        # Lets the chat label things in the document's own language ("Απάντηση:"
        # for a Greek handout) instead of hard-coding English.
        "language": _document_language(document),
        # Direct from R2 when the bucket allows this origin, relayed by the API
        # otherwise. The relay works everywhere but every byte crosses the VPS.
        "file_url": _document_file_url(document),
    }


@app.get("/api/document-stream/{file_key:path}")
async def api_document_stream(file_key: str):
    """302 to a fresh presigned URL so the PDF viewer never holds an expired one."""
    try:
        key = r2_service.validate_file_key(file_key)
        if not key.startswith(r2_service.DOCUMENT_KEY_PREFIX):
            raise ValueError("not a document key")
        download_url = generate_presigned_download_url(key, expires_in=3600)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error))
    return RedirectResponse(download_url, status_code=302)


@app.get("/api/document-file/{doc_id}")
async def api_document_file(
    doc_id: str, request: Request, expires: int | None = None, sig: str = ""
):
    """Stream the original file through this API, same-origin.

    A presigned R2 URL would be cross-origin, and the browser's fetch of it
    needs a bucket CORS policy. R2 tokens created for object access cannot set
    one (PutBucketCors is AccessDenied), so the viewer reads the bytes from here
    instead: one origin, no CORS, and the credentials never leave the server.
    """
    document = _load_document(doc_id)
    _authorise_media(request, document, expires, sig)
    kept = _kept_document(doc_id)
    file_key = document.get("file_key")
    if kept is not None:
        suffix = kept.suffix.lower()
        media_type = _DOCUMENT_CONTENT_TYPES.get(suffix, "application/octet-stream")

        def _iter_kept():
            with open(kept, "rb") as handle:
                while True:
                    chunk = handle.read(256 * 1024)
                    if not chunk:
                        break
                    yield chunk

        headers = {
            "Content-Disposition": f'inline; filename="{Path(document.get("file_name") or kept.name).name}"',
            "Content-Length": str(kept.stat().st_size),
        }
        return StreamingResponse(_iter_kept(), media_type=media_type, headers=headers)

    if not file_key:
        raise HTTPException(status_code=404, detail="Document has no stored file")

    suffix = Path(document.get("file_name") or "").suffix.lower()
    media_type = _DOCUMENT_CONTENT_TYPES.get(suffix, "application/octet-stream")

    def _open():
        return r2_service.open_object(file_key)

    try:
        body, size = await run_in_threadpool(_open)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error))

    def _iter():
        try:
            for chunk in body.iter_chunks(chunk_size=256 * 1024):
                if chunk:
                    yield chunk
        finally:
            body.close()

    headers = {
        "Content-Disposition": f'inline; filename="{Path(document.get("file_name") or "document").name}"',
    }
    if size:
        headers["Content-Length"] = str(size)
    return StreamingResponse(_iter(), media_type=media_type, headers=headers)


@app.delete("/api/document/{doc_id}")
async def api_delete_document(doc_id: str, request: Request):
    """Forget a document: its points, its R2 object, its text and its summary.
    The conversations stay until the user deletes them from the chat list."""
    document = _owned_document(doc_id, _current_user(request), allow_purged=True)
    await run_in_threadpool(_purge_document, document, False)
    return {"deleted": doc_id}


# The model is asked for `` `p. 12` ``, but it also produces "[p. 12]" and
# "(p. 12)" -- the bracketed form is how the excerpts are labelled in its
# context, so it copies that shape. All three mean the same citation, and all
# three are normalised to the inline-code form the chat turns into a button.
_PAGE_CITATION_RE = re.compile(r"[`\[(]\s*p\.?\s*(\d{1,4})\s*[`\])]", re.IGNORECASE)


def _enforce_page_citations(
    answer: str, pages: set[int], fallback_page=None, fallback_allowed=True
):
    """Keep only `p. N` markers that point at a page the model was really given."""
    kept = 0
    dropped = 0

    def _rewrite(outside: str) -> str:
        nonlocal kept, dropped

        def _replace(match):
            nonlocal kept, dropped
            page = int(match.group(1))
            if page in pages:
                kept += 1
                return f"`p. {page}`"
            dropped += 1
            return ""

        text = _PAGE_CITATION_RE.sub(_replace, outside)
        text = re.sub(r"\(\s*[,;]?\s*\)", "", text)
        text = re.sub(r"(?<=\S)[ \t]{2,}", " ", text)
        text = re.sub(r"[ \t]+\n", "\n", text)
        return text

    parts = answer.split("```")
    for index in range(0, len(parts), 2):
        parts[index] = _rewrite(parts[index])
    result = "```".join(parts)

    used_fallback = False
    # A short reply to "thanks" or "wraia" is not an answer about the document, so
    # it does not need a page marker glued to it -- which is how a thank-you ended
    # in a citation of page 1.
    if kept == 0 and pages and fallback_allowed:
        anchor = fallback_page if fallback_page in pages else min(pages)
        marker = f"`p. {anchor}`"
        paragraphs = result.split("\n\n")
        for index, block in enumerate(paragraphs):
            stripped = block.strip()
            if not stripped or stripped.startswith(("```", "#", "|", ">", "-", "*")):
                continue
            paragraphs[index] = block.rstrip() + " " + marker
            used_fallback = True
            break
        if not used_fallback:
            result = result.rstrip() + "\n\n" + marker
            used_fallback = True
        else:
            result = "\n\n".join(paragraphs)

    return result, kept, dropped, used_fallback


def _document_context_chunks(doc_id: str) -> list:
    """All indexed chunks for a document, ordered by page then position."""
    points = scroll_all_text(doc_id)
    ordered = sorted(
        points,
        key=lambda p: (
            (p.payload or {}).get("page") or 0,
            (p.payload or {}).get("chunk_index") or 0,
        ),
    )
    return ordered


@app.get("/api/document/{doc_id}/chats")
async def api_document_chats(doc_id: str, request: Request):
    """The conversations held about this document, newest first."""
    _owned_document(doc_id, _current_user(request), allow_purged=True)
    data = _load_chats(doc_id)
    chats = sorted(
        data.get("chats") or [], key=lambda item: item.get("updated_at") or 0, reverse=True
    )
    return {
        "chats": [
            {
                "id": chat.get("id"),
                "title": chat.get("title") or "New chat",
                "updated_at": chat.get("updated_at"),
                "message_count": len(chat.get("messages") or []),
            }
            for chat in chats
        ]
    }


@app.post("/api/document/{doc_id}/chats")
async def api_document_chat_create(
    doc_id: str, request: Request, req: ChatCreate | None = None
):
    """Start a conversation. The title becomes the first question's text."""
    _owned_document(doc_id, _current_user(request))
    with _CHAT_LOCK:
        data = _load_chats(doc_id)
        chat = {
            "id": f"chat_{uuid.uuid4().hex[:10]}",
            "title": ((req.title if req else None) or "New chat").strip() or "New chat",
            "created_at": time.time(),
            "updated_at": time.time(),
            "messages": [],
        }
        data.setdefault("chats", []).insert(0, chat)
        _save_chats(doc_id, data)
    return {"id": chat["id"], "title": chat["title"], "messages": []}


@app.get("/api/document/{doc_id}/chats/{chat_id}")
async def api_document_chat(doc_id: str, chat_id: str, request: Request):
    _owned_document(doc_id, _current_user(request), allow_purged=True)
    data = _load_chats(doc_id)
    chat = _find_chat(data, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        "id": chat.get("id"),
        "title": chat.get("title") or "New chat",
        "messages": chat.get("messages") or [],
    }


@app.delete("/api/document/{doc_id}/chats/{chat_id}")
async def api_document_chat_delete(doc_id: str, chat_id: str, request: Request):
    _owned_document(doc_id, _current_user(request), allow_purged=True)
    with _CHAT_LOCK:
        data = _load_chats(doc_id)
        before = len(data.get("chats") or [])
        data["chats"] = [chat for chat in (data.get("chats") or []) if chat.get("id") != chat_id]
        _save_chats(doc_id, data)
    return {"deleted": chat_id, "removed": before - len(data["chats"])}


@app.post("/api/document/ask")
async def api_document_ask(req: DocumentQuestion, request: Request):
    # Everything below is blocking -- Qdrant, the embedding call, the model round
    # trip. On the event loop it froze the whole API for the length of an answer:
    # five questions took five times as long as one, and a healthcheck during the
    # burst waited 22 seconds. In a thread they run side by side.
    return await run_in_threadpool(_document_ask_impl, req, None, _current_user(request))


def _document_ask_impl(req: DocumentQuestion, emit=None, user_id: str = ""):
    """Ask about a document: retrieve pages, answer, cite `p. N`."""
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    document = _owned_document(req.doc_id, str(user_id))
    chunks = _document_context_chunks(req.doc_id)
    if not chunks:
        raise HTTPException(status_code=409, detail="This document has no indexed text yet")

    summary_mode = _is_summary_request(question) or _is_chapter_continue(question)
    # The chapter already covered lives in the conversation, not in the request:
    # reading it from there is what makes "continue" start at the next chapter
    # even after a reload.
    history = list(req.history or [])
    if not history and req.conversation_id:
        stored = None
        try:
            stored = conversations.get(req.conversation_id, str(user_id))
        except Exception as history_error:  # noqa: BLE001 - history is optional
            print(f"[Chats] could not read the turns of {req.conversation_id}: {history_error}")
        history = list((stored or {}).get("messages") or [])
    # A Greek document is answered in Greek, whatever language the question is
    # typed in: the material a student revises from has to match the material
    # they were given. For any other document the question's own language wins.
    document_language = _document_language(document)
    answer_language = document_language if document_language == "Greek" else _detect_question_language(question)
    if not any(character.isalpha() for character in question) and document_language:
        answer_language = document_language

    chapter_title = None
    plan_next = None
    plan_end = False
    if summary_mode:
        # The whole document goes in once, to read its structure; the reply then
        # gets one chapter of it. A document too large for one context is thinned
        # out evenly, so no chapter is missing from the outline.
        total_chars = sum(len((r.payload.get("text") or "")) for r in chunks)
        if total_chars <= 90_000:
            whole = chunks
        else:
            budget = max(20, int(len(chunks) * 90_000 / total_chars))
            step = len(chunks) / budget
            whole = [chunks[int(i * step)] for i in range(budget)]
        outline = "\n".join(
            text if text.startswith("[figure") else f"[p.{_payload_page(r.payload)}] {text}"
            for r in whole
            for text in [((r.payload.get("text") or "").strip())]
            if text
        )
        chapters = _document_chapters_cached(
            req.doc_id, outline, _document_language(document) or "English"
        )
        if chapters:
            position = _chapter_index(chapters, question, history)
            chapter = chapters[position]
            start_page = int(chapter["start_page"])
            end_page = int(chapter["end_page"])
            in_chapter = [
                r
                for r in chunks
                if _payload_page(r.payload) is None
                or start_page <= (_payload_page(r.payload) or 0) <= end_page
            ]
            selected = in_chapter or chunks
            chapter_title = chapter["title"]
            plan_next = chapters[position + 1]["title"] if position + 1 < len(chapters) else None
            plan_end = plan_next is None
            print(
                f"[Docs] chapter {position + 1}/{len(chapters)}: {chapter_title} "
                f"(p.{start_page}-{end_page}, {len(selected)} chunks)"
            )
        else:
            selected = whole
            print(
                f"[Docs] summary context: {len(selected)}/{len(chunks)} chunks, "
                f"{total_chars} chars"
            )
    else:
        query_embedding = embed_query(question)
        vector_hits = search_text(query_embedding, limit=12, video_id=req.doc_id)

        lexical = _bm25_scores(question, chunks)
        peak = max(lexical.values(), default=0.0)
        payloads = {str(p.id): (p.payload or {}) for p in chunks}
        merged = {}
        for hit in vector_hits:
            point_id = str(hit.id)
            vector_score = float(getattr(hit, "score", 0.0) or 0.0)
            lexical_score = (lexical.get(point_id, 0.0) / peak) if peak else 0.0
            merged[point_id] = 0.45 * vector_score + 0.55 * lexical_score
        for point_id, raw in lexical.items():
            if point_id in merged or peak <= 0:
                continue
            normalised = raw / peak
            if normalised >= 0.40:
                merged[point_id] = 0.55 * normalised

        ranked = sorted(merged.items(), key=lambda item: item[1], reverse=True)[:18]
        selected = [_Ranked(pid, payloads.get(pid, {}), score) for pid, score in ranked if payloads.get(pid)]
        if not selected:
            selected = list(vector_hits[:6])

    # Neighbours matter as much as for a video: a page explains a concept over
    # several chunks, and retrieving one of them alone reads like a fragment.
    by_id = {str(p.id): p for p in chunks}
    expanded = []
    seen = set()
    for item in selected:
        key = str(getattr(item, "id", ""))
        if key in seen:
            continue
        seen.add(key)
        expanded.append(item)
    if not summary_mode:
        positions = {str(p.id): index for index, p in enumerate(chunks)}
        neighbour_ids = set()
        for item in selected:
            index = positions.get(str(getattr(item, "id", "")))
            if index is None:
                continue
            for offset in (-1, 1):
                target = index + offset
                if 0 <= target < len(chunks):
                    neighbour_ids.add(str(chunks[target].id))
        for point_id in neighbour_ids:
            if point_id in seen:
                continue
            seen.add(point_id)
            point = by_id[point_id]
            expanded.append(_Ranked(point_id, point.payload or {}, 0.0))

    ordered = sorted(
        expanded,
        key=lambda r: (
            (r.payload or {}).get("page") or 0,
            (r.payload or {}).get("chunk_index") or 0,
        ),
    )

    def _page_of(payload):
        page = (payload or {}).get("page")
        if page is None:
            start = (payload or {}).get("start")
            page = int(start) if isinstance(start, (int, float)) else None
        return page

    # Figures are always part of the context, not only when retrieval happens to
    # pick them: a question about a tree can score badly against prose and would
    # otherwise be answered from memory.
    figure_points = [
        p for p in chunks if (p.payload.get("text") or "").lstrip().startswith("[figure")
    ]
    seen_figures = {str(p.id) for p in ordered}
    ordered_with_figures = [
        _Ranked(str(p.id), p.payload or {}, 0.0)
        for p in figure_points
        if str(p.id) not in seen_figures
    ] + ordered

    context = "\n".join(
        # Figure chunks already say which page they belong to ("[figure p.7]"),
        # so they are not labelled twice.
        text
        if text.startswith("[figure")
        else f"[p.{_page_of(r.payload)}] {text}"
        for r in ordered_with_figures
        for text in [(r.payload.get("text") or "").strip()]
        if text
    )

    pages_in_context = {_page_of(r.payload) for r in ordered if _page_of(r.payload) is not None}
    available_pages = pages_in_context or {int(p.get("page") or 0) for p in document.get("pages") or []}
    transcript_available = bool(context.strip())

    marker_stream = None
    try:
        if summary_mode and not history:
            # The summary written at upload is chapter one of the whole document;
            # it is only the right answer when nothing has been discussed yet.
            cached_summary = _load_cached_summary(req.doc_id)
        else:
            cached_summary = None

        if cached_summary:
            # Generated during upload, over the same pages: no round-trip.
            answer = cached_summary["answer"]
            truncated = bool(cached_summary.get("truncated"))
            plan_next = cached_summary.get("next_chapter") or plan_next
            plan_end = bool(cached_summary.get("at_end")) or plan_end
            print(f"[Docs] summary served from pre-analysis: {req.doc_id}")
        else:
            # The structure is a machine line at the end of the answer; the filter
            # keeps it out of what the reader sees while it arrives.
            marker_stream = ChapterMarkerStream(emit) if emit else None
            answer, truncated = ask_document(
                question=question,
                context=context,
                history=history[-6:],
                answer_language=answer_language,
                summary_mode=summary_mode,
                transcript_available=transcript_available,
                chapter_title=chapter_title,
                next_chapter=plan_next,
                # Streaming: the callback fires per token, so the reader watches
                # the answer being written instead of waiting for all of it.
                on_delta=(marker_stream.push if marker_stream else None),
            )
            if marker_stream is not None:
                answer, marker_next, marker_end = marker_stream.finish(answer)
            else:
                answer, marker_next, marker_end = split_chapter_marker(answer)
            if marker_next:
                plan_next, plan_end = marker_next, False
            elif marker_end:
                plan_next, plan_end = None, True
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"LLM provider error: {error}")

    best = max(selected, key=lambda r: getattr(r, "score", 0) or 0, default=None)
    fallback_page = _page_of(best.payload) if best is not None else None
    answer, kept, dropped, used_fallback = _enforce_page_citations(
        answer,
        available_pages,
        fallback_page=fallback_page,
        fallback_allowed=len(answer) > 240,
    )
    print(f"[Cite] document: {kept} citation(s) kept, {dropped} dropped")

    cited_pages = sorted({int(m) for m in _PAGE_CITATION_RE.findall(answer)})
    page_rows = []
    for page in cited_pages or sorted(available_pages)[:4]:
        entry = next(
            (p for p in document.get("pages") or [] if int(p.get("page") or 0) == page),
            None,
        )
        page_rows.append(
            {
                "page": page,
                "text": (entry or {}).get("text", "")[:600],
                "heading": (entry or {}).get("heading"),
            }
        )

    # Persist the turn so the conversation reappears when the student comes back.
    try:
        if req.conversation_id:
            conversations.append_turn(req.conversation_id, str(user_id), question, answer)
        else:
            _append_turn(req.doc_id, req.chat_id, question, answer, page_rows)
    except Exception as chat_error:
        print(f"[Chats] could not store turn: {chat_error}")

    payload = {
        "source": "document",
        "doc_id": req.doc_id,
        "chat_id": req.chat_id,
        "answer": answer,
        # True when the model ran out of output budget:
        # the chat asks for the rest in a new message instead of showing a cut.
        "truncated": truncated,
        # What the composer offers next: the chapter after this one, or nothing
        # when the walkthrough reached the end of the document.
        "next_chapter": plan_next,
        "at_end": plan_end,
        "pages": page_rows,
        "text_results": [
            {
                "page": _page_of(r.payload),
                "text": r.payload.get("text"),
                "score": getattr(r, "score", None),
            }
            for r in ordered
        ],
    }

    if emit is not None:
        # The streamed text has already gone out; this is the canonical answer
        # after citation enforcement, plus the page rows the client needs.
        emit("final", payload)
        return None
    return payload


def _document_figures(chunks: list) -> list:
    """The figure descriptions already indexed, as {page, text} rows."""
    rows = []
    for point in chunks:
        payload = point.payload or {}
        text = (payload.get("text") or "").strip()
        if not text.startswith("[figure"):
            continue
        page = payload.get("page")
        if page is None:
            start = payload.get("start")
            page = int(start) if isinstance(start, (int, float)) else None
        rows.append(
            {
                "page": page,
                # Drop the internal label: the chat prints its own heading.
                "text": text.split("]", 1)[-1].strip() if "]" in text else text,
            }
        )
    rows.sort(key=lambda row: row.get("page") or 0)
    return rows


def _study_context(chunks: list, limit: int) -> str:
    """Context for quiz / flashcards / study guide.

    Figures come first and are never truncated away: a question about a tree is
    only answerable if the tree's description is in the prompt, and that is
    exactly the material a student needs drawn for them.
    """
    figures = [
        r for r in chunks if (r.payload.get("text") or "").lstrip().startswith("[figure")
    ]
    rest = [r for r in chunks if r not in figures]
    selected = (figures + rest)[:limit]
    return "\n".join(
        text
        if text.startswith("[figure")
        else f"[p.{(r.payload or {}).get('page')}] {text}"
        for r in selected
        for text in [((r.payload or {}).get("text") or "").strip()]
        if text
    )


@app.post("/api/document/ask/stream")
async def api_document_ask_stream(req: DocumentQuestion, request: Request):
    """The same answer as /api/document/ask, delivered as it is written.

    The work is blocking and HTTP-bound, so it runs in a thread and hands its
    tokens to this event loop through a queue: the response starts in
    milliseconds, and a second reader is not queued behind the first.
    """
    user_id = _current_user(request)
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def emit(kind, payload):
        loop.call_soon_threadsafe(queue.put_nowait, (kind, payload))

    def work():
        try:
            _document_ask_impl(req, emit, user_id)
        except HTTPException as error:
            emit("error", {"message": str(error.detail)})
        except Exception as error:  # noqa: BLE001 - the client gets the reason
            print(f"[Docs] stream failed: {error}")
            emit("error", {"message": str(error)})
        finally:
            emit("end", {})

    threading.Thread(target=work, name="document-ask-stream", daemon=True).start()

    async def frames():
        while True:
            kind, payload = await queue.get()
            if kind == "end":
                break
            yield f"event: {kind}\ndata: {json.dumps(payload)}\n\n"

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.post("/api/document/quiz")
async def api_document_quiz(req: DocumentStudyRequest, request: Request):
    document = _owned_document(req.doc_id, _current_user(request))
    chunks = _document_context_chunks(req.doc_id)
    if not chunks:
        raise HTTPException(status_code=409, detail="This document has no indexed text yet")
    language = req.language or _document_language(document) or "English"
    context = _study_context(chunks, 80)
    questions = document_quiz(context, count=req.count or 6, language=language)
    return {
        "doc_id": req.doc_id,
        "questions": questions,
        # The figures the vision pass read, sent along so the chat can show the
        # diagram itself next to the questions. The model is asked to draw them
        # in its explanations, but showing the source description guarantees the
        # reader sees the structure even when it does not.
        "figures": _document_figures(chunks),
    }


@app.post("/api/document/flashcards")
async def api_document_flashcards(req: DocumentStudyRequest, request: Request):
    document = _owned_document(req.doc_id, _current_user(request))
    chunks = _document_context_chunks(req.doc_id)
    if not chunks:
        raise HTTPException(status_code=409, detail="This document has no indexed text yet")
    language = req.language or _document_language(document) or "English"
    context = _study_context(chunks, 80)
    cards = document_flashcards(context, count=req.count or 10, language=language)
    return {"doc_id": req.doc_id, "cards": cards}


@app.post("/api/document/notes")
async def api_document_notes(req: DocumentStudyRequest, request: Request):
    document = _owned_document(req.doc_id, _current_user(request))
    chunks = _document_context_chunks(req.doc_id)
    if not chunks:
        raise HTTPException(status_code=409, detail="This document has no indexed text yet")
    language = req.language or _document_language(document) or "English"
    context = _study_context(chunks, 120)
    notes, notes_truncated = document_notes(context, language=language)
    return {"doc_id": req.doc_id, "notes": notes, "truncated": notes_truncated}


# --- GDPR: consent, retention of derived data, export and erasure -------------
# The file itself leaves R2 after R2_MAX_AGE_HOURS (see the storage retention
# block above). The data derived from it -- extracted page text, the summary and
# the vectors in Qdrant -- used to stay forever; the privacy policy promises
# otherwise, so the same clock now removes them. What is left is a tombstone
# (id, owner, file name, date) so the owner can still open the chat history,
# which is the only content kept, until the user deletes it.

class ConsentUpdate(BaseModel):
    china_transfer: bool | None = None
    marketing: bool | None = None


class AccountDeleteRequest(BaseModel):
    confirm: str


def _purge_document(document: dict, drop_chats: bool = False) -> None:
    """Remove everything derived from one document. Chats go only on request."""
    doc_id = str(document.get("doc_id") or "")
    safe = re.sub(r"[^A-Za-z0-9._-]", "", doc_id)
    if not safe:
        return
    try:
        client.delete(
            collection_name=TEXT_COLLECTION,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="video_id", match=qmodels.MatchValue(value=safe)
                        )
                    ]
                )
            ),
        )
    except Exception as error:
        print(f"[Purge] vectors for {safe}: {error}")

    kept = _kept_document(safe)
    if kept is not None:
        try:
            kept.unlink(missing_ok=True)
        except OSError as error:
            print(f"[Purge] kept copy of {safe}: {error}")

    file_key = document.get("file_key")
    if file_key:
        try:
            r2_service.delete_object(file_key)
        except Exception as error:
            print(f"[Purge] R2 object {file_key}: {error}")

    try:
        _summary_path(safe).unlink(missing_ok=True)
        with _SUMMARY_LOCK:
            _SUMMARY_CACHE.pop(safe, None)
    except Exception:
        pass

    keep_tombstone = not drop_chats and _chats_path(safe).exists()
    if keep_tombstone:
        _save_document(
            {
                "doc_id": safe,
                "owner_id": document.get("owner_id"),
                "file_name": document.get("file_name"),
                "kind": document.get("kind"),
                "created_at": document.get("created_at"),
                "purged_at": time.time(),
            }
        )
    else:
        _document_meta_path(safe).unlink(missing_ok=True)
    if drop_chats:
        _chats_path(safe).unlink(missing_ok=True)


def _derived_data_sweeper():
    while True:
        time.sleep(R2_SWEEP_SECONDS)
        if R2_MAX_AGE_HOURS <= 0:
            continue
        cutoff = time.time() - R2_MAX_AGE_HOURS * 3600
        for path in list(DOCS_DIR.glob("*.json")):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    document = json.load(handle)
            except Exception:
                continue
            if document.get("purged_at"):
                continue
            created = float(document.get("created_at") or 0)
            if created > cutoff:
                continue
            try:
                # A document with no owner predates accounts: nobody can reach
                # its chats, so nothing of it is worth keeping.
                _purge_document(document, drop_chats=not document.get("owner_id"))
                print(f"[Purge] {document.get('doc_id')} past {R2_MAX_AGE_HOURS:g}h")
            except Exception as error:
                print(f"[Purge] {document.get('doc_id')} failed: {error}")


threading.Thread(target=_derived_data_sweeper, name="derived-retention", daemon=True).start()


def _purge_video(video_id: str) -> None:
    """Remove everything derived from one analysed video."""
    safe = re.sub(r"[^A-Za-z0-9_-]", "", str(video_id or ""))
    if not safe:
        return
    for collection in (TEXT_COLLECTION, FRAME_COLLECTION):
        try:
            client.delete(
                collection_name=collection,
                points_selector=qmodels.FilterSelector(
                    filter=qmodels.Filter(
                        must=[
                            qmodels.FieldCondition(
                                key="video_id", match=qmodels.MatchValue(value=safe)
                            )
                        ]
                    )
                ),
            )
        except Exception as error:
            print(f"[Purge] vectors for {safe} in {collection}: {error}")

    for store in (TRANSCRIPTS_PATH, EMBEDDINGS_PATH):
        try:
            with _JSON_WRITE_LOCK:
                if store.exists():
                    with open(store, "r", encoding="utf-8") as handle:
                        data = json.load(handle)
                    if isinstance(data, dict) and safe in data:
                        data.pop(safe, None)
                        tmp = store.with_name(f"{store.name}.{uuid.uuid4().hex[:6]}.tmp")
                        with open(tmp, "w", encoding="utf-8") as handle:
                            json.dump(data, handle, indent=2, ensure_ascii=False)
                        tmp.replace(store)
        except Exception as error:
            print(f"[Purge] transcript store for {safe}: {error}")

    shutil.rmtree(FRAMES_DIR / safe, ignore_errors=True)
    shutil.rmtree(CHUNKS_DIR / safe, ignore_errors=True)
    try:
        (AUDIO_DIR / f"{safe}.wav").unlink(missing_ok=True)
    except OSError:
        pass
    try:
        for path in UPLOAD_DIR.iterdir():
            if path.is_file() and path.stem == safe:
                path.unlink(missing_ok=True)
    except OSError:
        pass

    record = video_registry.get(safe)
    for key in (record or {}).get("file_keys", []):
        try:
            r2_service.delete_object(key)
        except Exception as error:
            print(f"[Purge] R2 object {key}: {error}")
    video_registry.remove(safe)


_SCOPED_VIDEO_RE = re.compile(r"^[0-9a-f]{12}_")


def _video_sweeper():
    while True:
        time.sleep(R2_SWEEP_SECONDS)
        if R2_MAX_AGE_HOURS <= 0:
            continue
        cutoff = time.time() - R2_MAX_AGE_HOURS * 3600
        try:
            known = set()
            for record in video_registry.all_records():
                known.add(record.get("video_id"))
                if float(record.get("created_at") or 0) < cutoff:
                    _purge_video(record["video_id"])
                    print(f"[Purge] video {record['video_id']} past {R2_MAX_AGE_HOURS:g}h")
            # Leftovers from before videos had owners: nobody can reach them.
            leftovers = set()
            for folder in FRAMES_DIR.iterdir():
                if folder.is_dir() and folder.stat().st_mtime < cutoff:
                    leftovers.add(folder.name)
            for wav in AUDIO_DIR.glob("*.wav"):
                if wav.stat().st_mtime < cutoff:
                    leftovers.add(wav.stem)
            for name in leftovers - known:
                if not _SCOPED_VIDEO_RE.match(name):
                    _purge_video(name)
                    print(f"[Purge] legacy video artifacts {name}")
        except Exception as error:
            print(f"[Purge] video sweep skipped: {error}")


threading.Thread(target=_video_sweeper, name="video-retention", daemon=True).start()


@app.get("/api/consent")
async def api_get_consent(request: Request):
    try:
        return await run_in_threadpool(
            compliance.get_consents, _current_user(request), fresh=True
        )
    except compliance.ConsentUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error))


@app.post("/api/consent")
async def api_set_consent(request: Request, req: ConsentUpdate):
    user_id = _current_user(request)
    try:
        for kind in ("china_transfer", "marketing"):
            value = getattr(req, kind)
            if value is not None:
                await run_in_threadpool(compliance.record_consent, user_id, kind, value)
        return await run_in_threadpool(compliance.get_consents, user_id, fresh=True)
    except compliance.ConsentUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error))


def _account_documents(user_id: str) -> list[dict]:
    out = []
    for path in DOCS_DIR.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                document = json.load(handle)
        except Exception:
            continue
        if str(document.get("owner_id") or "") == user_id:
            out.append(document)
    return out


@app.get("/api/account/export")
async def api_account_export(request: Request):
    """Everything we hold about the caller (GDPR Art. 15 and 20)."""
    user_id = _current_user(request)

    def _build():
        claims = getattr(request.state, "user", {}) or {}
        documents = []
        for document in _account_documents(user_id):
            doc_id = document.get("doc_id")
            chats = []
            try:
                chats = _load_chats(doc_id).get("chats", [])
            except Exception:
                pass
            documents.append(
                {
                    "doc_id": doc_id,
                    "file_name": document.get("file_name"),
                    "created_at": document.get("created_at"),
                    "file_still_stored": not document.get("purged_at"),
                    "chats": chats,
                }
            )
        return {
            "account": {"id": user_id, "email": claims.get("email")},
            "consents": compliance.get_consents(user_id, fresh=True),
            "documents": documents,
            "videos": [
                {"video_id": r.get("video_id"), "created_at": r.get("created_at")}
                for r in video_registry.records_for(user_id)
            ],
            "conversations": [
                conversations.get(item["chat_id"], user_id)
                for item in conversations.list_for(user_id)
            ],
            "note": "Uploaded files are deleted automatically; chat history is kept until you delete it.",
        }

    try:
        return await run_in_threadpool(_build)
    except compliance.ConsentUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error))


@app.delete("/api/account")
async def api_account_delete(request: Request, req: AccountDeleteRequest):
    """Delete the caller's documents, videos, conversations and account."""
    if (req.confirm or "").strip() != "DELETE":
        raise HTTPException(status_code=400, detail="Type DELETE to confirm")
    user_id = _current_user(request)

    def _erase():
        documents = _account_documents(user_id)
        for document in documents:
            _purge_document(document, drop_chats=True)
        for record in video_registry.records_for(user_id):
            _purge_video(record["video_id"])
        for item in conversations.list_for(user_id):
            conversations.remove(item["chat_id"], user_id)
        for kind in ("documents", "videos"):
            try:
                prefix = user_scope.directory(kind, user_id)
                for entry in r2_service.list_objects((prefix,)):
                    r2_service.delete_object(entry["key"])
            except Exception as error:
                print(f"[Account] R2 {kind}: {error}")
        compliance.delete_auth_user(user_id)
        return len(documents)

    try:
        count = await run_in_threadpool(_erase)
    except compliance.ConsentUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error))
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error))
    return {"deleted": True, "documents": count}
