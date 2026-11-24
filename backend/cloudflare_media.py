"""Cloudflare Media Transformations: audio extracted at the edge, not here.

The zone has Transformations enabled and the R2 bucket answers on
`media.0digital.xyz`, so the edge can produce the audio track for us:

    https://<zone>/cdn-cgi/media/mode=audio,duration=60s,format=m4a/<public mp4 url>

The result is an M4A that Groq fetches directly. Nothing is downloaded here and
ffmpeg never runs. Two hard limits come with it: the source must be under 100 MB
and ten minutes, and one request yields at most 60 seconds -- so a video becomes
one slice per minute, transcribed in parallel and stitched back with offsets.

Anything outside those limits is left to the caller's next route.
"""

import math
import os
import time
from concurrent.futures import ThreadPoolExecutor

import cloudflare_stream

MEDIA_ZONE = (os.getenv("MEDIA_TRANSFORM_ZONE") or "").strip()
PUBLIC_ORIGIN = (os.getenv("MEDIA_PUBLIC_ORIGIN") or "").strip().rstrip("/")
SLICE_SECONDS = int(os.getenv("MEDIA_TRANSFORM_SLICE", "60") or "60")
SLICE_WORKERS = int(os.getenv("MEDIA_TRANSFORM_WORKERS", "4") or "4")
# The edge refuses sources longer than ten minutes, and larger than 100 MB.
MAX_SECONDS = int(os.getenv("MEDIA_TRANSFORM_MAX_SECONDS", "600") or "600")
MAX_BYTES = int(float(os.getenv("MEDIA_TRANSFORM_MAX_MB", "100")) * 1024 * 1024)
# A whole video must not hold a worker for ever: if the edge has not answered by
# this point the caller falls back to the local path instead of sitting at 25%.
DEADLINE_SECONDS = int(os.getenv("MEDIA_TRANSFORM_DEADLINE", "600") or "600")
SLICE_TIMEOUT = int(os.getenv("MEDIA_TRANSFORM_SLICE_TIMEOUT", "240") or "240")


def source_size(url: str):
    """Content-Length of the source, or None when the origin will not say."""
    import requests

    try:
        response = requests.head(url, timeout=20, allow_redirects=True)
        length = response.headers.get("Content-Length")
        return int(length) if length and length.isdigit() else None
    except Exception:
        return None


def configured() -> bool:
    return bool(MEDIA_ZONE and PUBLIC_ORIGIN)


def public_url(file_key: str) -> str:
    return f"{PUBLIC_ORIGIN}/{str(file_key).lstrip('/')}"


def audio_slice_url(source_url: str, duration_seconds: int) -> str:
    """One audio-only transform of up to 60 seconds, starting at the source start."""
    return (
        f"https://{MEDIA_ZONE}/cdn-cgi/media/mode=audio,"
        f"duration={int(duration_seconds)}s,format=m4a/{source_url}"
    )


def _shift(segments: list, seconds: float) -> list:
    shifted = []
    for segment in segments or []:
        item = dict(segment)
        for key in ("start", "end"):
            if isinstance(item.get(key), (int, float)):
                item[key] = item[key] + seconds
        shifted.append(item)
    return shifted


def audio_slices_transcript(
    source: str,
    duration_seconds: float,
    language: str | None = None,
    on_progress=None,
    offset_seconds: float = 0.0,
):
    """Transcribe an edge-reachable video by pulling sixty-second audio slices."""
    total = max(1, int(math.ceil(duration_seconds / SLICE_SECONDS)))
    started = time.time()

    def one(index: int):
        if (time.time() - started) > DEADLINE_SECONDS:
            raise RuntimeError(f"the edge did not finish within {DEADLINE_SECONDS}s")
        offset = index * SLICE_SECONDS
        remaining = duration_seconds - offset
        length = int(max(1, min(SLICE_SECONDS, math.ceil(remaining))))
        url = (
            f"https://{MEDIA_ZONE}/cdn-cgi/media/mode=audio,time={offset}s,"
            f"duration={length}s,format=m4a/{source}"
        ) if offset else (
            f"https://{MEDIA_ZONE}/cdn-cgi/media/mode=audio,"
            f"duration={length}s,format=m4a/{source}"
        )
        payload = cloudflare_stream.transcribe_url(
            url, language=language, timeout=SLICE_TIMEOUT
        )
        return offset, payload

    results = []
    with ThreadPoolExecutor(max_workers=min(SLICE_WORKERS, total)) as pool:
        for done, item in enumerate(pool.map(one, range(total)), start=1):
            results.append(item)
            if on_progress:
                try:
                    on_progress(done, total)
                except Exception:
                    pass

    segments = []
    texts = []
    for offset, payload in sorted(results, key=lambda pair: pair[0]):
        segments.extend(_shift(payload.get("segments") or [], offset + offset_seconds))
        piece = (payload.get("text") or "").strip()
        if piece:
            texts.append(piece)
    return {"segments": segments, "text": " ".join(texts).strip()}


def transcribe_media(file_key: str, duration_seconds: float, language: str | None = None, on_progress=None):
    """Transcribe a whole video through audio-only slices at the edge."""
    if not configured():
        return None
    if not duration_seconds or duration_seconds <= 0:
        return None

    source = public_url(file_key)
    size = source_size(source)
    if size and size > MAX_BYTES:
        print(
            f"[Media] {file_key}: {size / 1024 / 1024:.0f} MB is over the edge limit "
            f"of {MAX_BYTES / 1024 / 1024:.0f} MB; using the local path"
        )
        return None

    total = max(1, int(math.ceil(duration_seconds / SLICE_SECONDS)))
    print(f"[Media] {file_key}: {duration_seconds:.0f}s in {total} edge slice(s)")
    started = time.time()

    def over_deadline() -> bool:
        return (time.time() - started) > DEADLINE_SECONDS

    def one(index: int):
        if over_deadline():
            raise RuntimeError(
                f"the edge did not finish within {DEADLINE_SECONDS}s; falling back"
            )
        offset = index * SLICE_SECONDS
        remaining = duration_seconds - offset
        length = int(max(1, min(SLICE_SECONDS, math.ceil(remaining))))

        if index == 0:
            url = audio_slice_url(source, length)
        else:
            # A later slice starts inside the source: `time` picks the offset.
            url = (
                f"https://{MEDIA_ZONE}/cdn-cgi/media/mode=audio,time={offset}s,"
                f"duration={length}s,format=m4a/{source}"
            )
        payload = cloudflare_stream.transcribe_url(
            url, language=language, timeout=SLICE_TIMEOUT
        )
        return offset, payload

    results = []
    with ThreadPoolExecutor(max_workers=min(SLICE_WORKERS, total)) as pool:
        for done, item in enumerate(pool.map(one, range(total)), start=1):
            results.append(item)
            if on_progress:
                try:
                    on_progress(done, total)
                except Exception:
                    pass

    segments = []
    texts = []
    for offset, payload in sorted(results, key=lambda pair: pair[0]):
        segments.extend(_shift(payload.get("segments") or [], offset))
        piece = (payload.get("text") or "").strip()
        if piece:
            texts.append(piece)

    if not segments and not texts:
        raise RuntimeError("the edge returned no transcript for this video")

    print(f"[Media] {file_key}: {len(segments)} segments from {total} slice(s)")
    return {
        "text": " ".join(texts).strip(),
        "segments": segments,
        "language": results[0][1].get("language") if results else None,
    }
