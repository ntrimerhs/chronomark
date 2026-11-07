"""Extract downscaled JPEG frames from a segment."""
import logging
import shutil
import subprocess
from pathlib import Path


def extract_frames(
    segment_path: Path,
    out_dir: Path,
    interval_sec: float = 5.0,
    max_side: int = 512,
    quality: int = 3,
    max_frames: int = 120,
) -> list[Path]:
    """Extract frames; widening the interval automatically if there are too many."""
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    duration = _duration_seconds(segment_path)
    if duration and duration / interval_sec > max_frames:
        interval_sec = duration / max_frames
        logging.info("interval widened to %.1fs to stay under %d frames", interval_sec, max_frames)

    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", str(segment_path),
        "-vf", f"fps=1/{interval_sec},scale='min({max_side},iw)':-2",
        "-q:v", str(quality),
        str(out_dir / "frame_%06d.jpg"),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)

    frames = sorted(out_dir.glob("frame_*.jpg"))
    logging.info("%s -> %d frames (every %.1fs)", segment_path.name, len(frames), interval_sec)
    return frames


def _duration_seconds(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=False,
    )
    try:
        return float(result.stdout.strip())
    except (TypeError, ValueError):
        return 0.0


def frame_timestamp(segment_start: float, frame_index: int, interval_sec: float) -> float:
    """Absolute time of frame N (1-based), per the spec formula."""
    return segment_start + (frame_index - 1) * interval_sec