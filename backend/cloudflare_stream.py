"""Cloudflare Stream: transcode and serve the media, so this box never touches it.

The heavy path for a long video used to be "download it, run ffmpeg on it,
transcribe the WAV". With Stream the sequence becomes:

    1. the object already sits in R2 (the browser or the upload endpoint put it there)
    2. POST /stream/copy with a presigned R2 URL -- Cloudflare fetches it
    3. poll until the transcode is ready
    4. ask Groq to transcribe the MP4 URL directly

No download, no ffmpeg, no disk, no CPU: the worker only passes URLs around. A
video longer than Groq's file limit is clipped into parts here (Stream's clipping
API), each part transcribed, and the segments stitched back with their offsets.

Everything is behind STREAM_TRANSCODE and fails back to the local path: a missing
token, an account without the Stream permission, or any HTTP error simply returns
None and the caller keeps its ffmpeg route.
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

CLOUDFLARE_ACCOUNT_ID = (os.getenv("CLOUDFLARE_ACCOUNT_ID") or "").strip()
CLOUDFLARE_API_TOKEN = (os.getenv("CLOUDFLARE_API_TOKEN") or "").strip()
GROQ_API_KEY = (os.getenv("GROQ_API_KEY") or "").strip()

STREAM_BASE = (
    f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/stream"
    if CLOUDFLARE_ACCOUNT_ID
    else ""
)
GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3")

# A clip long enough to stay well inside Groq's 100 MB server-side limit, short
# enough that parallel transcription still beats one long request.
CLIP_SECONDS = int(os.getenv("STREAM_CLIP_SECONDS", "1200") or "1200")
CLIP_WORKERS = int(os.getenv("STREAM_CLIP_WORKERS", "4") or "4")
READY_TIMEOUT_SEC = int(os.getenv("STREAM_READY_TIMEOUT", "1800") or "1800")

_probe_result = None
_probe_at = 0.0


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json",
    }


def configured() -> bool:
    return bool(CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN)


def available(refresh: bool = False) -> bool:
    """True only when Stream actually answers for this token.

    The token may exist and still have no Stream permission -- that is the state
    this project shipped with -- so availability is verified once by calling the
    API, not assumed from the presence of two strings.
    """
    global _probe_result, _probe_at
    if not configured():
        return False
    if _probe_result is not None and not refresh and (time.time() - _probe_at) < 600:
        return _probe_result

    try:
        response = requests.get(f"{STREAM_BASE}?limit=1", headers=_headers(), timeout=20)
        _probe_result = response.status_code == 200 and bool(response.json().get("success"))
        if not _probe_result:
            print(
                "[Stream] token cannot reach Cloudflare Stream "
                f"(HTTP {response.status_code}); keeping the local path"
            )
    except Exception as error:
        _probe_result = False
        print(f"[Stream] probe failed: {error}; keeping the local path")

    _probe_at = time.time()
    return _probe_result


def _result(response, label: str):
    try:
        payload = response.json()
    except Exception:
        raise RuntimeError(f"{label}: HTTP {response.status_code} {response.text[:200]}")
    if response.status_code >= 400 or not payload.get("success", True):
        message = payload.get("errors") or payload.get("error") or response.text[:200]
        raise RuntimeError(f"{label}: {message}")
    return payload.get("result")


def copy_from_url(source_url: str, name: str = "chronomark") -> dict:
    """Ask Cloudflare to pull the object from R2 and transcode it."""
    response = requests.post(
        f"{STREAM_BASE}/copy",
        headers=_headers(),
        json={"url": source_url, "meta": {"name": name[:100]}},
        timeout=120,
    )
    return _result(response, "stream copy")


def wait_ready(uid: str) -> dict:
    """Poll until the video is playable, then return its record."""
    deadline = time.time() + READY_TIMEOUT_SEC
    started = time.perf_counter()
    while time.time() < deadline:
        response = requests.get(f"{STREAM_BASE}/{uid}", headers=_headers(), timeout=30)
        video = _result(response, "stream status") or {}
        state = (video.get("status") or {}).get("state")
        if state == "ready":
            print(f"[Stream] {uid} ready in {time.perf_counter() - started:.1f}s")
            return video
        if state == "error":
            reason = (video.get("status") or {}).get("errorReasonText") or "unknown"
            raise RuntimeError(f"stream transcode failed: {reason}")
        time.sleep(5)
    raise RuntimeError("stream transcode timed out")


def download_url(uid: str) -> str:
    """The MP4 URL, enabling downloads on the video first if it is not allowed."""
    response = requests.get(f"{STREAM_BASE}/{uid}/downloads", headers=_headers(), timeout=30)
    try:
        result = _result(response, "stream downloads") or {}
        default = (result.get("default") or {}).get("url")
        if default:
            return default
    except RuntimeError:
        pass

    # Downloads are off: ask for them, then read the URLs again.
    requests.post(
        f"{STREAM_BASE}/{uid}/downloads",
        headers=_headers(),
        json={"type": "default"},
        timeout=30,
    )
    time.sleep(3)
    # Enabling downloads makes Stream generate the MP4 in the background: the
    # API hands out a URL before the file exists, and fetching it too early
    # answers 404. Poll until the file actually serves a byte.
    deadline = time.time() + 300
    while time.time() < deadline:
        response = requests.get(f"{STREAM_BASE}/{uid}/downloads", headers=_headers(), timeout=30)
        result = _result(response, "stream downloads (after enable)") or {}
        default = (result.get("default") or {}).get("url")
        if default:
            resolved = _resolve_redirects(default)
            if _serves_bytes(resolved):
                return resolved
        time.sleep(5)

    raise RuntimeError("stream never produced a downloadable MP4 for this video")


def _serves_bytes(url: str) -> bool:
    """True when the URL answers a range request, i.e. the MP4 really exists."""
    try:
        response = requests.get(url, headers={"Range": "bytes=0-1023"}, stream=True, timeout=30)
        ok = response.status_code in (200, 206)
        response.close()
        return ok
    except Exception:
        return False


def _resolve_redirects(url: str) -> str:
    """Cloudflare's download URL answers 302; Groq does not follow redirects.

    The Location target is the signed CDN URL, so it is resolved here and the
    final address is what gets handed over.
    """
    try:
        response = requests.get(url, allow_redirects=True, stream=True, timeout=30)
        final = response.url or url
        response.close()
        if final and final != url:
            return final
    except Exception as error:
        print(f"[Stream] could not resolve the download redirect: {error}")
    return url


def delete_video(uid: str) -> None:
    """Drop the video from Stream once it is transcribed: storage is billed."""
    try:
        requests.delete(f"{STREAM_BASE}/{uid}", headers=_headers(), timeout=30)
        print(f"[Stream] deleted {uid} from the account")
    except Exception as error:
        print(f"[Stream] could not delete {uid}: {error}")


def clip(uid: str, start_seconds: int, duration_seconds: int, name: str) -> str:
    """Cut one part out of a long video and return its MP4 URL."""
    response = requests.post(
        f"{STREAM_BASE}/{uid}/clip",
        headers=_headers(),
        json={
            "clippedFromUid": uid,
            "startTimeMs": int(start_seconds * 1000),
            "endTimeMs": int((start_seconds + duration_seconds) * 1000),
            "meta": {"name": name[:100]},
        },
        timeout=120,
    )
    piece = _result(response, "stream clip") or {}
    piece_uid = piece.get("uid")
    if not piece_uid:
        raise RuntimeError("stream clip returned no uid")
    wait_ready(piece_uid)
    return download_url(piece_uid)


def transcribe_url(media_url: str, language: str | None = None, timeout: int = 1800) -> dict:
    """Groq fetches the media itself; nothing passes through this machine."""
    # Groq wants multipart/form-data even for the url form: a JSON body or a
    # urlencoded form is rejected with "request Content-Type isn't
    # multipart/form-data". Text fields go as empty-name parts, the same shape the
    # SDK produces for a file upload.
    fields = {
        "model": GROQ_MODEL,
        "url": media_url,
        "response_format": "verbose_json",
        "timestamp_granularities[]": "segment",
    }
    if language:
        fields["language"] = language

    response = requests.post(
        GROQ_TRANSCRIBE_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        files={key: (None, value) for key, value in fields.items()},
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"groq url transcription: HTTP {response.status_code} {response.text[:200]}")
    return response.json()


def _offset(segments: list, seconds: float) -> list:
    shifted = []
    for segment in segments or []:
        item = dict(segment)
        for key in ("start", "end"):
            if isinstance(item.get(key), (int, float)):
                item[key] = item[key] + seconds
        shifted.append(item)
    return shifted


def fetch_mp4(uid: str, destination_dir) -> Path:
    """Download the transcoded MP4 to this machine.

    Slower than handing a URL over, but Stream's download URL redirects to a
    short-lived signed address that Groq will not follow, and the transcoded file
    is a fraction of the original upload -- small enough to transcribe directly.
    """
    url = download_url(uid)
    destination = Path(destination_dir)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f"{uid}.mp4"

    with requests.get(url, stream=True, timeout=600) as response:
        response.raise_for_status()
        with open(target, "wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)

    size = target.stat().st_size
    print(f"[Stream] downloaded {uid}: {size / 1024 / 1024:.1f} MB")
    return target


def transcode_to_file(source_url: str, destination_dir, name: str = "chronomark") -> Path | None:
    """Copy the media into Stream, wait for it, and bring the MP4 back down."""
    if not available():
        return None

    uid = None
    try:
        video = copy_from_url(source_url, name=name)
        uid = video.get("uid")
        if not uid:
            raise RuntimeError("stream copy returned no uid")
        video = wait_ready(uid)
        duration = float((video.get("duration") or 0) or 0)
        print(f"[Stream] {uid}: {duration:.0f}s media, fetching the transcoded copy")
        return fetch_mp4(uid, destination_dir)
    except Exception as error:
        print(f"[Stream] fell back to the local path: {error}")
        return None
    finally:
        if uid:
            delete_video(uid)


def transcribe_large_media(source_url: str, name: str = "chronomark", language: str | None = None) -> dict | None:
    """Full pipeline: R2 URL -> Stream -> Groq. None when Stream is unusable."""
    if not available():
        return None

    started = time.perf_counter()
    uid = None
    try:
        video = copy_from_url(source_url, name=name)
        uid = video.get("uid")
        if not uid:
            raise RuntimeError("stream copy returned no uid")
        video = wait_ready(uid)
        duration = float((video.get("duration") or 0) or 0)

        if duration <= CLIP_SECONDS:
            payload = transcribe_url(download_url(uid), language=language)
            payload["text"] = (payload.get("text") or "").strip()
            payload["segments"] = payload.get("segments") or []
            print(
                f"[Stream] {uid} transcribed in {time.perf_counter() - started:.1f}s "
                f"({duration:.0f}s media)"
            )
            return payload

        # Long video: transcribe overlapping-free slices in parallel and stitch.
        offsets = list(range(0, int(duration), CLIP_SECONDS))
        print(f"[Stream] {uid}: {duration:.0f}s, {len(offsets)} clip(s) to transcribe")

        def one(offset_seconds: int):
            url = clip(uid, offset_seconds, CLIP_SECONDS, f"{name}-{offset_seconds}")
            payload = transcribe_url(url, language=language)
            return offset_seconds, payload

        with ThreadPoolExecutor(max_workers=min(CLIP_WORKERS, len(offsets))) as pool:
            results = list(pool.map(one, offsets))

        merged_segments = []
        text_parts = []
        for offset_seconds, payload in sorted(results, key=lambda item: item[0]):
            merged_segments.extend(_offset(payload.get("segments") or [], offset_seconds))
            piece_text = (payload.get("text") or "").strip()
            if piece_text:
                text_parts.append(piece_text)

        print(f"[Stream] {uid} transcribed in {time.perf_counter() - started:.1f}s in {len(offsets)} clip(s)")
        return {
            "text": " ".join(text_parts).strip(),
            "segments": merged_segments,
            "language": None,
        }
    except Exception as error:
        print(f"[Stream] fell back to the local path: {error}")
        return None
    finally:
        # Stream storage is billed by the minute: a transcribed video is dead
        # weight, so it is removed as soon as the transcript exists.
        if uid:
            delete_video(uid)
