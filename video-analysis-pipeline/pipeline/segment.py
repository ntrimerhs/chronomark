"""Split a video into fixed-length segments without re-encoding."""
import csv
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Segment:
    index: int
    path: Path
    start_sec: float
    end_sec: float

    @property
    def segment_id(self) -> str:
        return f"seg_{self.index:03d}"


def split_video(source: Path, out_dir: Path, seconds: int = 300) -> list[Segment]:
    """Cut `source` into keyframe-aligned segments and return them with real times.

    Uses stream copy, so nothing is re-encoded. Start times come from ffmpeg's
    own listing rather than index * seconds, because keyframe alignment makes
    the cuts drift.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    listing = out_dir / "segments.csv"

    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", str(source),
        "-c", "copy", "-map", "0",
        "-f", "segment",
        "-segment_time", str(seconds),
        "-reset_timestamps", "1",
        "-segment_list", str(listing),
        "-segment_list_type", "csv",
        str(out_dir / "seg_%03d.mp4"),
    ]
    logging.info("segmenting into %ss chunks", seconds)
    subprocess.run(command, check=True, capture_output=True, text=True)

    segments: list[Segment] = []
    with listing.open(newline="", encoding="utf-8") as handle:
        for index, row in enumerate(csv.reader(handle)):
            if not row:
                continue
            name = Path(row[0]).name
            start = float(row[1])
            end = float(row[2])
            segments.append(Segment(index, out_dir / name, start, end))

    if not segments:
        raise RuntimeError("ffmpeg produced no segments")
    logging.info("segments: %d", len(segments))
    return segments