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
from concurrent.futures import ThreadPoolExecutor

import cloudflare_stream

MEDIA_ZONE = (os.getenv("MEDIA_TRANSFORM_ZONE") or "").strip()
PUBLIC_ORIGIN = (os.getenv("MEDIA_PUBLIC_ORIGIN") or "").strip().rstrip("/")
SLICE_SECONDS = int(os.getenv("MEDIA_TRANSFORM_SLICE", "60") or "60")
SLICE_WORKERS = int(os.getenv("MEDIA_TRANSFORM_WORKERS", "4") or "4")
# The edge refuses sources longer than ten minutes.
MAX_SECONDS = int(os.getenv("MEDIA_TRANSFORM_MAX_SECONDS", "600") or "600")


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


def transcribe_media(file_key: str, duration_seconds: float, language: str | None = None, on_progress=None):
    """Transcribe a whole video through audio-only slices at the edge."""
    if not configured():
        return None
    if not duration_seconds or duration_seconds <= 0:
        return None

    source = public_url(file_key)
    total = max(1, int(math.ceil(duration_seconds / SLICE_SECONDS)))
    print(f"[Media] {file_key}: {duration_seconds:.0f}s in {total} edge slice(s)")

    def one(index: int):
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
        payload = cloudflare_stream.transcribe_url(url, language=language)
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
