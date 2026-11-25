"""YouTube import that does not land on the VPS disk.

The box is a 2 vCPU / 38 GB machine and a lecture is 0.5-1.5 GB, so nothing
here is allowed to write the video to a file first. yt-dlp can write a single
stream to stdout (`-o -`), and R2 accepts a forward-only body, so the bytes go
YouTube -> pipe -> R2 with no landing file on the way.

Two plans, because YouTube offers two shapes of video:

  muxed   One progressive format (picture and sound in the same container).
          One stream, zero disk. YouTube caps these at 720p, often at 360p.
  dash    Separate video and audio streams, up to 1080p. Two streams into R2,
          then ffmpeg muxes them from the two signed URLs into a temporary
          file and it is uploaded and deleted immediately. This is the only
          path that touches the disk, because the MP4 moov atom has to be
          rewritten and that needs a seekable output -- a pipe cannot do it.
          It is skipped when the free space is below the floor.

`YT_DLP_MODE` picks the behaviour: `auto` (default) prefers a muxed stream at
or above `YT_DLP_MIN_MUXED_HEIGHT`, otherwise DASH when the disk allows it;
`muxed` never writes to disk; `dash` always takes the best quality.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from collections import deque
from pathlib import Path

from services import r2_service

COOKIES_PATH = os.environ.get("YT_DLP_COOKIES", "/app/cookies.txt")
MAX_HEIGHT = int(os.environ.get("YT_DLP_MAX_HEIGHT", "1080"))
MIN_MUXED_HEIGHT = int(os.environ.get("YT_DLP_MIN_MUXED_HEIGHT", "720"))
MODE = os.environ.get("YT_DLP_MODE", "auto").strip().lower()
DISK_FLOOR_MB = int(os.environ.get("YT_DLP_DISK_FLOOR_MB", "2500"))
DOWNLOAD_TIMEOUT = int(os.environ.get("YT_DLP_TIMEOUT", "3600"))


class YouTubeIngestError(RuntimeError):
    """Anything that stops the import, with a message fit for the job status."""


# ── yt-dlp plumbing ─────────────────────────────────────────────────────────


def ytdlp_executable() -> str:
    """Resolve yt-dlp next to the running interpreter, then on PATH."""
    scripts_dir = Path(sys.executable).parent
    for name in ("yt-dlp.exe", "yt-dlp"):
        candidate = scripts_dir / name
        if candidate.exists():
            return str(candidate)
    found = shutil.which("yt-dlp")
    if found:
        return found
    raise YouTubeIngestError("yt-dlp not found in the Python environment")


def _proxy_args() -> list[str]:
    """Only yt-dlp goes through the proxy: the datacenter IP is what YouTube
    challenges, and transcription/LLM traffic must keep the direct route."""
    proxy = os.environ.get("YT_DLP_PROXY", "").strip()
    return ["--proxy", proxy] if proxy else []


def _command() -> list[str]:
    return [
        ytdlp_executable(),
        "--cookies",
        COOKIES_PATH,
        "--no-playlist",
        "--no-warnings",
        "--retries",
        "10",
        "--fragment-retries",
        "10",
        "--socket-timeout",
        "30",
        "--concurrent-fragments",
        "4",
        *_proxy_args(),
    ]


def _tail(text: str, limit: int = 300) -> str:
    return " ".join((text or "").strip().splitlines()[-6:])[-limit:] or "no output"


class _StderrDrain(threading.Thread):
    """Keep the last lines of yt-dlp's stderr.

    The pipe has to be drained while the body is being uploaded, or yt-dlp
    blocks on a full 64 KB buffer and the upload waits for a process that is
    waiting for us.
    """

    def __init__(self, stream):
        super().__init__(daemon=True)
        self.stream = stream
        self.lines: deque[str] = deque(maxlen=60)

    def run(self) -> None:
        try:
            for raw in iter(self.stream.readline, b""):
                line = raw.decode("utf-8", "replace").strip()
                if line:
                    self.lines.append(line)
        except Exception:
            pass

    def text(self) -> str:
        return _tail("\n".join(self.lines))


def probe(url: str, timeout: int = 120) -> dict:
    """The format list, without downloading a byte."""
    result = subprocess.run(
        [*_command(), "-J", url],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise YouTubeIngestError(f"yt-dlp could not read the video: {_tail(result.stderr)}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise YouTubeIngestError(f"yt-dlp returned unreadable metadata: {error}") from error


def _stream_to_r2(
    url: str,
    selector: str,
    file_name: str,
    content_type: str,
    on_status=None,
    prefix: str = r2_service.UPLOAD_KEY_PREFIX,
) -> dict:
    """Pipe one yt-dlp output stream straight into R2. No local file."""
    if on_status:
        on_status(stage="downloading", error=None)
    process = subprocess.Popen(
        [*_command(), "-f", selector, "-o", "-", url],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    drain = _StderrDrain(process.stderr)
    drain.start()

    # A stalled download must not hold the worker forever; the watchdog kills
    # the producer, which closes stdout and lets the upload finish.
    watchdog = threading.Timer(DOWNLOAD_TIMEOUT, process.kill)
    watchdog.daemon = True
    watchdog.start()

    uploaded = None
    try:
        uploaded = r2_service.upload_stream(
            process.stdout, file_name, content_type, prefix=prefix
        )
    except Exception as error:
        process.kill()
        process.wait()
        raise YouTubeIngestError(f"the upload to R2 stopped: {error}") from error
    finally:
        watchdog.cancel()
        try:
            process.stdout.close()
        except Exception:
            pass

    process.wait()
    drain.join(timeout=5)

    size = (uploaded or {}).get("size") or 0
    if process.returncode != 0 or size <= 0:
        if uploaded and uploaded.get("file_key"):
            try:
                r2_service.delete_object(uploaded["file_key"])
            except Exception:
                pass
        raise YouTubeIngestError(f"yt-dlp failed ({process.returncode}): {drain.text()}")

    print(f"[YouTube] {selector} -> R2 {uploaded['file_key']} ({size / 1048576:.1f} MB)")
    return uploaded


# ── format selection ────────────────────────────────────────────────────────


def _protocol_rank(fmt: dict) -> int:
    """How well a format survives being written to a pipe.

    Progressive HTTPS and DASH segments are downloaded by yt-dlp itself and
    written sequentially, so `-o -` works. HLS goes through ffmpeg, and an
    ffmpeg output on a pipe fails on some URLs (it cannot open the m3u8 it is
    being handed), so HLS is the last resort, not the first choice.
    """
    protocol = (fmt.get("protocol") or "").lower()
    if protocol.startswith("m3u8"):
        return 0
    if protocol in ("https", "http"):
        return 3
    if protocol == "http_dash_segments":
        return 2
    if protocol in ("mhtml", "images"):
        return -1
    return 1


def _usable(formats: list[dict]) -> list[dict]:
    kept = []
    for fmt in formats:
        if not fmt.get("url"):
            continue
        if _protocol_rank(fmt) < 0:
            continue
        kept.append(fmt)
    return kept


def choose_plan(info: dict) -> dict:
    """Pick the best muxed format and the best DASH pair from the metadata."""
    formats = _usable(info.get("formats") or [])

    muxed, video, audio = [], [], []
    for fmt in formats:
        video_codec = fmt.get("vcodec") or "none"
        audio_codec = fmt.get("acodec") or "none"
        height = int(fmt.get("height") or 0)
        is_mp4 = (fmt.get("ext") or "") == "mp4"
        rank = _protocol_rank(fmt)
        if video_codec != "none" and audio_codec != "none":
            muxed.append((rank, height, is_mp4, fmt))
        elif video_codec != "none" and 0 < height <= MAX_HEIGHT:
            video.append((rank, height, is_mp4, fmt))
        elif audio_codec != "none":
            audio.append((rank, float(fmt.get("abr") or 0), (fmt.get("ext") or "") == "m4a", fmt))

    # Resolution first among equally streamable formats, but never an HLS
    # stream when a DASH one exists: HLS is the name that breaks the pipe.
    best_muxed = max(muxed, key=lambda item: (item[0], item[1], item[2])) if muxed else None
    best_video = max(video, key=lambda item: (item[0], item[1], item[2])) if video else None
    best_audio = max(audio, key=lambda item: (item[0], item[1], item[2])) if audio else None

    plan = {
        "title": info.get("title") or "",
        "is_live": bool(info.get("is_live")),
        "muxed_selector": None,
        "muxed_height": 0,
        "video_selector": None,
        "audio_selector": None,
        "dash_height": 0,
        "expected_mb": ((info.get("filesize") or info.get("filesize_approx") or 0) / 1048576),
    }

    if best_muxed:
        plan["muxed_selector"] = best_muxed[3]["format_id"]
        plan["muxed_height"] = best_muxed[1]

    # One selector per stream. Joining them here ("299+258") sent yt-dlp a
    # mux job that it hands to ffmpeg, and an ffmpeg mux on a pipe is exactly
    # what this module exists to avoid -- the video and the audio are fetched
    # separately and joined afterwards.
    if best_video and best_audio:
        plan["video_selector"] = best_video[3]["format_id"]
        plan["audio_selector"] = best_audio[3]["format_id"]
        plan["dash_height"] = best_video[1]

    return plan


def free_mb() -> float:
    return shutil.disk_usage(tempfile.gettempdir()).free / 1048576


def _required_mb(info: dict) -> float:
    expected = ((info.get("filesize") or info.get("filesize_approx") or 0) / 1048576)
    return expected * 1.35 + 400


# ── the mux path (the only one that writes a file) ──────────────────────────


def _mux_to_r2(
    video_key: str,
    audio_key: str,
    file_name: str,
    prefix: str = r2_service.UPLOAD_KEY_PREFIX,
) -> dict:
    video_url = r2_service.generate_presigned_download_url(video_key, expires_in=3600)
    audio_url = r2_service.generate_presigned_download_url(audio_key, expires_in=3600)

    out_path = Path(tempfile.gettempdir()) / f"chronomark-mux-{uuid.uuid4().hex[:12]}.mp4"
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        video_url,
        "-i",
        audio_url,
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=3600)
        if result.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
            raise YouTubeIngestError(f"ffmpeg could not mux the streams: {_tail(result.stderr)}")
        with open(out_path, "rb") as handle:
            return r2_service.upload_stream(
                handle, file_name, "video/mp4", prefix=prefix
            )
    finally:
        # The muxed file must not survive the upload, whatever happened.
        try:
            out_path.unlink(missing_ok=True)
        except OSError:
            pass


def _import_dash(
    url: str, plan: dict, stem: str, on_status, prefix: str = r2_service.UPLOAD_KEY_PREFIX
) -> dict:
    if on_status:
        on_status(stage="downloading_video", progress=6)
    video = _stream_to_r2(
        url, plan["video_selector"], f"{stem}-video.mp4", "application/octet-stream", prefix=prefix
    )

    audio = None
    try:
        if on_status:
            on_status(stage="downloading_audio", progress=10)
        audio = _stream_to_r2(
            url, plan["audio_selector"], f"{stem}-audio.m4a", "application/octet-stream", prefix=prefix
        )

        if on_status:
            on_status(stage="muxing", progress=13)
        return _mux_to_r2(video["file_key"], audio["file_key"], f"{stem}.mp4", prefix=prefix)
    finally:
        for uploaded in (video, audio):
            if not uploaded:
                continue
            try:
                r2_service.delete_object(uploaded["file_key"])
            except Exception:
                pass


# ── entry point ─────────────────────────────────────────────────────────────


def import_to_r2(
    url: str, on_status=None, prefix: str = r2_service.UPLOAD_KEY_PREFIX
) -> dict:
    """Bring a YouTube video into R2 and return {"file_key", "size", ...}."""
    info = probe(url)
    if info.get("is_live"):
        raise YouTubeIngestError("Live streams cannot be imported")

    plan = choose_plan(info)
    if not plan["muxed_selector"] and not plan["video_selector"]:
        raise YouTubeIngestError("YouTube offered no downloadable format for this video")

    stem = f"yt_{uuid.uuid4().hex[:12]}"
    mode = MODE
    if mode not in ("auto", "muxed", "dash"):
        mode = "auto"

    if mode == "auto":
        muxed_is_good = plan["muxed_height"] >= MIN_MUXED_HEIGHT
        dash_affordable = plan["video_selector"] and free_mb() >= max(
            _required_mb(info), DISK_FLOOR_MB
        )
        if muxed_is_good or not dash_affordable:
            mode = "muxed" if plan["muxed_selector"] else "dash"
        else:
            mode = "dash"

    if mode == "muxed" and not plan["muxed_selector"]:
        mode = "dash"
    if mode == "dash" and not plan["video_selector"]:
        mode = "muxed"

    if mode == "muxed":
        height = plan["muxed_height"]
        uploaded = _stream_to_r2(
            url, plan["muxed_selector"], f"{stem}.mp4", "video/mp4", on_status, prefix=prefix
        )
        reason = f"muxed {height}p, nothing written to disk"
    else:
        height = plan["dash_height"]
        uploaded = _import_dash(url, plan, stem, on_status, prefix=prefix)
        reason = f"dash {height}p, two streams muxed and the temp file deleted"

    uploaded["mode"] = mode
    uploaded["height"] = height
    uploaded["title"] = plan["title"]
    uploaded["reason"] = reason
    print(f"[YouTube] {reason}: {uploaded['file_key']} ({uploaded['size'] / 1048576:.1f} MB)")
    return uploaded
