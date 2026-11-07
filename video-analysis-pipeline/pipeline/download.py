"""Download a YouTube video with yt-dlp."""
import logging
import subprocess
from pathlib import Path


def download(url: str, target: Path, max_height: int = 1080) -> Path:
    """Download `url` into `target` and return the resulting file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    template = target.with_suffix(".%(ext)s")
    format_selector = f"bv*[height<={max_height}]+ba/b[height<={max_height}]"

    command = [
        "yt-dlp",
        "-f", format_selector,
        "--merge-output-format", "mp4",
        "-o", str(template),
        url,
    ]
    logging.info("downloading %s", url)
    subprocess.run(command, check=True, capture_output=True, text=True)

    for candidate in sorted(target.parent.glob(f"{target.stem}.*")):
        if candidate.suffix.lower() == ".mp4":
            logging.info("downloaded %s", candidate.name)
            return candidate
    raise RuntimeError("yt-dlp finished but no mp4 was produced")