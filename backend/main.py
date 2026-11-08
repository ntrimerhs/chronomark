from fastapi import FastAPI, UploadFile, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import re
import shutil
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from fastapi.staticfiles import StaticFiles
from video_processing import extract_audio
from video_processing import extract_frames, extract_frame_at, normalize_video
from whisper import transcribe_audio_chunks
import base64
import json
import math
import uuid
from bert import create_embeddings_from_transcript, embed_query, warm_up as warm_text_model
from qdrant_store import ensure_collections, store_text_embeddings, clear_collections
from qdrant_store import client, TEXT_COLLECTION, FRAME_COLLECTION, search_text, scroll_all_text

from llama import (
    ask_llama,
    extract_examples,
    map_examples_to_excerpts,
    transcribe_image,
)

from pydantic import BaseModel
import sys

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


def _snap_inline_timestamps(answer: str, segments) -> str:
    """Replace every inline `mm:ss` marker (the LLM writes one above each code
    snippet, see llama.py's system prompt) with the nearest REAL transcript
    segment start time from `segments` -- the LLM only paraphrases the
    "[mm:ss-mm:ss]" tags it was given and can drift to a plausible-looking
    time that isn't an actual moment in the video.
    """
    starts = sorted(
        start for start in (seg.payload.get("start") for seg in segments)
        if isinstance(start, (int, float))
    )
    if not starts:
        return answer

    def _replace(match):
        requested = int(match.group(1)) * 60 + int(match.group(2))
        nearest = min(starts, key=lambda s: abs(s - requested))
        minutes, secs = divmod(int(nearest), 60)
        return f"`{minutes}:{secs:02d}`"

    return _INLINE_TIMESTAMP_RE.sub(_replace, answer)


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
                embeddings_present = bool(json.load(f))
        except Exception:
            embeddings_present = False

    if transcript_has_text and not embeddings_present:
        embeddings = create_embeddings_from_transcript(transcript_data)
        _update_shared_json(EMBEDDINGS_PATH, embeddings)
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
        _update_shared_json(TRANSCRIPTS_PATH, transcript_for_json)
    if embeddings:
        _update_shared_json(EMBEDDINGS_PATH, embeddings)

    return transcript_for_json, embeddings

# Runtime folder layout used by this API:
# - uploads/: original uploaded video files
# - audio/: extracted WAV audio files (same stem as video)
# - frames/: extracted image frames grouped by video stem
# - normalized/: re-encoded MP4s produced when a video needs format
#   normalization or its audio stream turns out to be corrupted
#   (see normalize_video's `force` fallback in _process_upload_job)
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

# CORS is open here to simplify local frontend/backend integration.
# In production this should be restricted to known frontend origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

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

@app.get('/debug/segments')
def debug_segments(video_id: str | None = None):
    """Dump the indexed segments so retrieval can be inspected directly."""
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
    return {
        "text_points": client.count(collection_name=TEXT_COLLECTION).count,
        "frame_points": client.count(collection_name=FRAME_COLLECTION).count,
    }

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


def _update_shared_json(path: Path, data):
    """Overwrite the shared JSON file's contents with just this video's data.

    The frontend only supports one active video at a time, so each new
    upload should fully replace whatever was previously stored here (the
    raw segments/embeddings themselves, no video_id wrapper) rather than
    accumulating every video ever uploaded.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def _clear_previous_uploads(current_video):
    for file in UPLOAD_DIR.iterdir():
        if file.is_file() and file.name != current_video:
            file.unlink(missing_ok=True)


def _clear_previous_video_files(current_stem: str):
    """Remove on-disk audio/frame/normalized artifacts left behind by any
    video other than the one currently being processed.

    This app only keeps one active video's data at a time (same reasoning as
    clear_collections() and _update_shared_json() above), but audio/*.wav,
    frames/<stem>/, and normalized/*.mp4 were never being cleaned up, so old
    uploads just accumulated on disk indefinitely even though the JSON
    stores looked "current". This brings the filesystem in line with that
    same rule.
    """
    for wav_file in AUDIO_DIR.glob("*.wav"):
        if wav_file.stem != current_stem:
            wav_file.unlink(missing_ok=True)

    for frame_dir in FRAMES_DIR.iterdir():
        if frame_dir.is_dir() and frame_dir.name != current_stem:
            shutil.rmtree(frame_dir, ignore_errors=True)

    for normalized_file in NORMALIZED_DIR.glob("*.mp4"):
        if normalized_file.stem != f"{current_stem}_normalized":
            normalized_file.unlink(missing_ok=True)



def _set_job_status(job_id, status=None, stage=None, progress=None, error=None, result=None):
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


def _run_audio_pipeline(video_path: Path, output_audio: Path, job_id=None):
    """Extract audio, transcribe it, and create/store text embeddings.

    Runs with detailed progress tracking. When job_id is given, pushes
    granular stage/progress updates as each step advances -- without this,
    the frontend's progress bar sat frozen at "extracting_audio" for the
    entire (often multi-minute) transcription pass, since that was the only
    status update between the start and the final "finalizing" jump.
    """
    transcript_error = None
    transcript_for_json = {"segments": []}
    embeddings = []

    try:
        t_audio = time.perf_counter()
        extract_audio(video_path, output_audio)
        print(f"✓ Audio extraction complete for {video_path.stem}  [{time.perf_counter()-t_audio:.1f}s]")
    except RuntimeError as e:
        print(f"✗ Direct audio extraction failed for {video_path.stem}: {e}")
        try:
            normalized_video = normalize_video(video_path, NORMALIZED_DIR, force=True)
            print(f"↻ Retrying audio extraction from normalized video: {normalized_video}")
            extract_audio(normalized_video, output_audio)
        except Exception as normalize_error:
            transcript_error = f"Could not extract audio: {normalize_error}"
            print(transcript_error)
            output_audio = None

    try:
        if output_audio and Path(output_audio).exists():
            import time as _time
            t0 = _time.perf_counter()
            print(f"✓ Starting transcription for {video_path.stem}...")

            if job_id:
                _set_job_status(job_id, stage="transcribing_audio", progress=30)

            def _on_transcribe_progress(completed, total):
                if job_id and total:
                    _set_job_status(
                        job_id,
                        stage="transcribing_audio",
                        progress=30 + int(45 * completed / total),
                    )

            transcript = transcribe_audio_chunks(str(output_audio), on_progress=_on_transcribe_progress)
            transcript_for_json = _compact_transcript_for_json(transcript)
            print(f"✓ Transcription complete: {len(transcript_for_json.get('segments', []))} segments  [{_time.perf_counter()-t0:.1f}s]")

            if job_id:
                _set_job_status(job_id, stage="embedding_text", progress=80)

            t1 = _time.perf_counter()
            print(f"↻ Creating text embeddings...")
            embeddings = create_embeddings_from_transcript(transcript_for_json)
            store_text_embeddings(video_path.stem, embeddings)
            print(f"✓ Embeddings stored: {len(embeddings)} vectors  [{_time.perf_counter()-t1:.1f}s]")

            # Compact outline per 5-minute chunk, so questions do not have to
            # re-read the whole transcript every time.
            try:
                _build_digests(transcript_for_json.get("segments") or [], video_path.stem)
            except Exception as digest_error:
                print(f"[Digest] skipped: {digest_error}")

            if job_id:
                _set_job_status(job_id, stage="embedding_text", progress=90)
    except Exception as e:
        transcript_error = str(e)
        print(f"✗ Transcription/embedding failed for {video_path.stem}: {e}")

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
    if coverage_interval_sec and float(coverage_interval_sec) > 0:
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
    for moment in moments:
        # A sentence announces a concept slightly before the slide catches up,
        # so the still is taken a beat later than the word that triggered it.
        at = float(moment) + max(0.0, float(lookahead_sec))
        target = frames_dir / f"frame9{added + 1:05d}.jpg"
        if not extract_frame_at(video_path, at, target):
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
COVERAGE_INTERVAL_SEC = 20.0


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


def _ocr_frames(frames_dir, video_id, stamps=None, workers=10):
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
    for entry in entries:
        frame_path = Path(frames_dir) / entry["file"]
        signature = _frame_signature(frame_path)
        if signature is not None and previous is not None:
            if _signature_distance(signature, previous) < 0.04:
                continue
        if signature is not None:
            previous = signature
        data_url = _frame_data_url(frame_path)
        if data_url:
            prepared.append((entry, data_url))
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


def _sync_concept_frames(video_path, transcript, frames_dir, base_count=0, max_width=0):
    """Add frames chosen from the transcript, then index everything in the dir.

    Used by both orderings: in audio-first mode base_count is 0 and these are
    the only frames; in the parallel mode they supplement the scene pass.
    """
    try:
        added = _add_concept_frames(
            video_path, transcript, frames_dir, max_width=max_width
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


def _run_frame_pipeline(
    video_path: Path,
    output_frames_dir: Path,
    frame_interval_sec,
    frame_strategy,
    scene_threshold,
    keyframes_only,
    frame_max_width,
):
    """Extract frames and write their timestamp manifest.

    Runs on its own thread inside _process_upload_job, in parallel with
    _run_audio_pipeline. Nothing here depends on the transcript, so it can
    run fully concurrently with the audio/text pipeline.
    """
    frame_count, frame_timestamps = extract_frames(
        video_path,
        output_frames_dir,
        interval_seconds=frame_interval_sec,
        extraction_mode=frame_strategy,
        scene_threshold=scene_threshold,
        keyframes_only=keyframes_only,
        max_width=frame_max_width,
    )

    # Persist frame -> timestamp so the UI can offer thumbnails straight off
    # disk, without a Qdrant round-trip. Sorted by time: the scrubber and the
    # strip both need them in playback order.
    entries = sorted(
        ({"file": name, "t": float(seconds)} for name, seconds in frame_timestamps.items()),
        key=lambda item: item["t"],
    )
    (output_frames_dir / "frames.json").write_text(
        json.dumps(entries), encoding="utf-8"
    )

    # No CLIP vectors any more: visual matching was removed, so embedding here
    # would cost ~3s per frame to build an index nothing queries.
    return frame_count, frame_timestamps


def _process_upload_job(
    job_id,
    filename,
    video_path,
    frame_interval_sec,
    frame_strategy,
    scene_threshold,
    keyframes_only,
    frame_max_width,
    start_time=None,
):
    if start_time is None:
        start_time = time.perf_counter()
    try:
        video_path = Path(video_path)
        global CURRENT_VIDEO_ID
        CURRENT_VIDEO_ID = video_path.stem

        # This app only keeps one active video's data at a time -- wipe
        # whatever was stored for the previous video before processing the
        # new one, so /ask never mixes results across uploads.
        clear_collections()
        _clear_previous_video_files(video_path.stem)
        _clear_previous_uploads(video_path.name)

        # Ensure the file the frontend actually plays is seek-friendly
        # (faststart MP4 / H.264 / AAC). Otherwise the browser's seek bar
        # can land on the wrong timestamp when dragged, since the moov atom
        # (the index mapping time -> byte offset) may sit at the end of the
        # raw upload.
        t_normalize = time.perf_counter()
        try:
            playable_video = Path(normalize_video(video_path, NORMALIZED_DIR))
            print(f"✓ Faststart prep done  [{time.perf_counter()-t_normalize:.1f}s]")
            if playable_video != video_path:
                served_filename = f"{video_path.stem}.mp4"
                served_path = UPLOAD_DIR / served_filename
                shutil.copyfile(playable_video, served_path)
                if video_path.suffix.lower() != ".mp4":
                    video_path.unlink(missing_ok=True)
                filename = served_filename
                video_path = served_path
        except Exception as prep_error:
            print(f"⚠ Could not prepare video for playback  [{time.perf_counter()-t_normalize:.1f}s], serving original file: {prep_error}")

        output_audio = AUDIO_DIR / f"{video_path.stem}.wav"
        output_frames_dir = FRAMES_DIR / video_path.stem

        _set_job_status(job_id, status="processing", stage="extracting_audio", progress=25)

        # Frames and audio are independent, so they run concurrently: the frame
        # pass rides alongside transcription instead of adding to it. A frame failure must not fail the upload -- the transcript is
        # the primary product, and /ask degrades to text-only without frames.
        def _visual_only_task():
            """Coverage frames plus OCR, independent of the transcript."""
            try:
                # 20 seconds, not frame_interval_sec: that one defaults to 5s
                # for scrubbing thumbnails, and feeding it here produced 161
                # frames for a 13-minute video -- 322 OCR calls and the upload
                # crawled. 20s is enough to catch any slide that stays up.
                count, coverage_stamps = extract_frames(
                    video_path,
                    output_frames_dir,
                    interval_seconds=COVERAGE_INTERVAL_SEC,
                    extraction_mode="interval",
                    scene_threshold=scene_threshold,
                    keyframes_only=False,
                    max_width=frame_max_width,
                    min_gap_sec=0.0,
                    max_hash_distance=0,
                )
                print(f"[Frames] {count} coverage frames every {COVERAGE_INTERVAL_SEC:.0f}s")
                _ocr_frames(output_frames_dir, video_path.stem, coverage_stamps)
                return count
            except Exception as visual_error:
                print(f"[Frames] coverage pass failed: {visual_error}")
                return 0

        def _frames_task():
            try:
                count, _frame_stamps = _run_frame_pipeline(
                    video_path,
                    output_frames_dir,
                    frame_interval_sec,
                    frame_strategy,
                    scene_threshold,
                    keyframes_only,
                    frame_max_width,
                )
                print(f"[Frames] {count} frames for {video_path.stem}")
                return count
            except Exception as frame_error:
                print(f"[Frames] extraction failed for {video_path.stem}: {frame_error}")
                return 0

        audio_first = str(frame_strategy or "").strip().lower() == "audio"

        if audio_first:
            # Frames + OCR do not need the transcript, and OCR is now the slowest
            # stage (~100 vision calls). Running it alongside transcription turns
            # the total from "transcribe then OCR" into whichever finishes last.
            with ThreadPoolExecutor(max_workers=2) as pool:
                visual_future = pool.submit(_visual_only_task)
                transcript_for_json, embeddings, transcript_error = _run_audio_pipeline(
                    video_path, output_audio, job_id=job_id
                )
                try:
                    visual_future.result()
                except Exception as visual_error:
                    print(f"[Frames] visual pass failed: {visual_error}")

            frame_count = _sync_concept_frames(
                video_path, transcript_for_json, output_frames_dir,
                max_width=frame_max_width,
            )
        else:
            with ThreadPoolExecutor(max_workers=2) as pool:
                frame_future = pool.submit(_frames_task)
                transcript_for_json, embeddings, transcript_error = _run_audio_pipeline(
                    video_path, output_audio, job_id=job_id
                )
                frame_count = frame_future.result()

            frame_count = _sync_concept_frames(
                video_path, transcript_for_json, output_frames_dir,
                base_count=frame_count, max_width=frame_max_width,
            )
            try:
                _ocr_frames(output_frames_dir, video_path.stem)
            except Exception as ocr_error:
                print(f"[OCR] failed: {ocr_error}")

        _set_job_status(job_id, status="processing", stage="finalizing", progress=95)

        _update_shared_json(TRANSCRIPTS_PATH, transcript_for_json)
        _update_shared_json(EMBEDDINGS_PATH, embeddings)

        total_time_sec = time.perf_counter() - start_time

        result = {
            "filename": filename,
            "file_url": f"/uploads/{filename}",
            "audio_url": f"/audio/{video_path.stem}.wav",
            "video_id": video_path.stem,
            "transcript_url": "/audio/output.json",
            "embeddings_url": "/audio/output_embeddings.json",
            "transcript": transcript_for_json,
            "transcript_error": transcript_error,
            "frame_count": frame_count,
            "total_time_sec": round(total_time_sec, 1),
        }
        _set_job_status(job_id, status="completed", stage="completed", progress=100, result=result)

        # Logged last, on purpose: if the console cannot encode this line, a
        # successful job must not be turned into a failed one.
        print(f"[Pipeline] Upload-to-embeddings finished for {video_path.stem} in {total_time_sec:.1f}s")
    except Exception as e:
        total_time_sec = time.perf_counter() - start_time
        # Recorded before logging, for the same reason. Logging first meant a
        # failing print skipped this call, so the job reported the print's
        # encoding error instead of the actual cause.
        _set_job_status(job_id, status="failed", stage="failed", progress=100, error=str(e))
        print(f"[Pipeline] Upload pipeline failed after {total_time_sec:.1f}s: {e}")


class YoutubeRequest(BaseModel):
    url: str
    frame_interval_sec: float = 5.0
    frame_strategy: str = "audio"
    scene_threshold: float = 0.12
    keyframes_only: bool = False
    frame_max_width: int = 0  # 0 = keep the video's own resolution


@app.post('/download-youtube/')
async def download_youtube(req: YoutubeRequest, background_tasks: BackgroundTasks):
    """Download a YouTube video via yt-dlp, save it to uploads/, then process
    it through the same background pipeline as a regular file upload."""
    import re as _re
    import subprocess
    import sys

    start_time = time.perf_counter()

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
        import subprocess
        import sys

        # Resolve yt-dlp from the same Python env so it works regardless of
        # whether the venv Scripts/ folder is on the system PATH.
        scripts_dir = Path(sys.executable).parent
        yt_dlp_exe = scripts_dir / "yt-dlp.exe"
        if not yt_dlp_exe.exists():
            yt_dlp_exe = scripts_dir / "yt-dlp"          # Linux / macOS
        if not yt_dlp_exe.exists():
            _set_job_status(job_id, status="failed", stage="failed", progress=100,
                            error="yt-dlp not found in the Python environment")
            return

        try:
            _set_job_status(job_id, stage="downloading", progress=5)

            # Use a fixed UUID-based filename so we always know exactly where
            # the file lands — no stdout parsing, no fallback to "newest file".
            file_stem = f"yt_{uuid.uuid4().hex[:12]}"
            out_path = UPLOAD_DIR / f"{file_stem}.mp4"

            # YouTube is rotating client/format availability frequently.
            # Hard-coding a narrow stream selector (like "bv*[height<=480]+ba")
            # makes the downloader brittle and triggers the 403s you are seeing.
            # Prefer generic best formats first, then fall back to a more general
            # combined-video/audio selector, instead of forcing a single client.
            # Highest resolution first. "best" on its own is a single combined
            # stream, and YouTube caps those at 360p or 720p -- that is why an
            # imported lecture arrived as 640x360 with unreadable code. Anything
            # above 720p exists only as separate video and audio streams that
            # yt-dlp merges with ffmpeg.
            format_attempts = [
                (
                    "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/"
                    "bestvideo[height<=1080]+bestaudio/"
                    "best[height<=1080]/best"
                ),
                "bestvideo+bestaudio/best",
                "best[ext=mp4]/best",
            ]

            result = None
            for idx, fmt in enumerate(format_attempts):
                _set_job_status(job_id, stage="downloading", progress=5 + (idx * 3),
                                error=f"Trying format {idx + 1}/{len(format_attempts)}")

                print(f"[YouTube] Attempting format={fmt}")

                result = subprocess.run(
                    [
                        str(yt_dlp_exe),
                        "--no-playlist",
                        "--no-warnings",
                        "--extractor-args", "youtube:player_client=android,web,ios",
                        "-f", fmt,
                        "--merge-output-format", "mp4",
                        "--retries", "10",
                        "--fragment-retries", "10",
                        "--socket-timeout", "30",
                        "--concurrent-fragments", "4",
                        "-o", str(out_path),
                        url,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=180,
                )

                if result.returncode == 0 and out_path.exists():
                    file_size_mb = out_path.stat().st_size / 1024 / 1024
                    print(f"[YouTube] Downloaded successfully ({fmt}): {file_size_mb:.1f} MB")
                    break
                else:
                    stderr_snippet = (result.stderr or "")[-150:] if result.stderr else "Unknown"
                    print(f"[YouTube] {fmt} failed: {stderr_snippet}")

            if result is None or result.returncode != 0:
                stderr = (result.stderr or "").strip() if result else "Unknown error"
                _set_job_status(job_id, status="failed", stage="failed", progress=100,
                                error=f"Download failed (all formats): {stderr[-200:]}")
                return

            if not out_path.exists() or out_path.stat().st_size == 0:
                _set_job_status(job_id, status="failed", stage="failed", progress=100,
                                error="Download succeeded but output file is missing or empty")
                return

            _set_job_status(job_id, stage="processing_audio_and_frames", progress=15)
            _process_upload_job(
                job_id,
                out_path.name,
                str(out_path),
                req.frame_interval_sec,
                req.frame_strategy,
                req.scene_threshold,
                req.keyframes_only,
                req.frame_max_width,
                start_time,
            )
        except subprocess.TimeoutExpired:
            _set_job_status(job_id, status="failed", stage="failed", progress=100,
                            error="Download timed out (tried 720p → 480p → any MP4)")
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
    background_tasks: BackgroundTasks,
    file_upload: UploadFile,
    frame_interval_sec: float = 10.0,
    frame_strategy: str = "audio",
    scene_threshold: float = 0.12,
    keyframes_only: bool = False,
    frame_max_width: int = 0,  # 0 = keep the video's own resolution
):
    """Process one uploaded video and return URLs for all generated artifacts.

    Request flow:
    1) Save uploaded bytes under uploads/<original_filename>
    2) Extract WAV audio into audio/<video_stem>.wav
    3) Extract frames into frames/<video_stem>/frameXXXXXX.jpg
    4) Return relative URLs consumed by the frontend

    frame_interval_sec controls temporal sampling density in interval mode.
    frame_strategy selects extraction style: "scene" or "interval".
    scene_threshold controls FFmpeg scene sensitivity in scene mode.
    keyframes_only trades timing uniformity for speed.
    frame_max_width limits frame width to reduce CPU/disk cost.
    """

    start_time = time.perf_counter()

    if not file_upload.filename:
        raise HTTPException(status_code=400, detail="Missing uploaded filename")

    # Stream upload to disk to avoid reading very large files into memory.
    save_to = UPLOAD_DIR / file_upload.filename
    print("UPLOAD_DIR:", UPLOAD_DIR)
    print("Saving to:", save_to)
    with open(save_to, 'wb') as f:
        while True:
            chunk = await file_upload.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)

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
        _process_upload_job,
        job_id,
        file_upload.filename,
        str(save_to),
        frame_interval_sec,
        frame_strategy,
        scene_threshold,
        keyframes_only,
        frame_max_width,
        start_time,
    )

    return {
        "job_id": job_id,
        "status": "processing",
        "stage": "queued",
        "progress": 5,
        "status_url": f"/upload-status/{job_id}",
    }


@app.get('/upload-status/{job_id}')
async def get_upload_status(job_id: str):
    job = JOBS.get(job_id)
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


@app.post("/ask")
async def ask(req: Question):
    try:
        question = req.question
        requested_video_id = req.video_id
        history = (req.history or [])[-6:]

        current_video_id = requested_video_id or CURRENT_VIDEO_ID

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
                f"[on screen] {text}"
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

        # The LLM writes an inline `mm:ss` marker (in backticks) above any code
        # snippet, but it's just paraphrasing the excerpt tags in `context` --
        # it can drift to a nearby-sounding time that isn't an actual segment.
        # Snap every such marker to the closest REAL segment start from the
        # same excerpts the answer was grounded in, so the jump link it
        # produces always lands on an actual transcript moment.
        answer = _snap_inline_timestamps(answer, sorted_results)

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