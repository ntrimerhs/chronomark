"""Configuration, read once from the environment."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str) -> str:
    return os.getenv(name, default)


def _num(name: str, default):
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return type(default)(raw)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    vision_model: str
    text_model: str

    frame_interval_sec: float
    max_frames_per_segment: int
    max_frames_per_request: int
    image_max_side: int
    jpeg_quality: int

    max_parallel_segments: int
    max_retries: int
    request_timeout_sec: int
    max_requests_per_run: int

    data_dir: Path
    keep_frames: bool
    log_level: str


def load_settings() -> Settings:
    return Settings(
        api_key=_get("DEEPSEEK_API_KEY", ""),
        base_url=_get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        vision_model=_get("DEEPSEEK_VISION_MODEL", ""),
        text_model=_get("DEEPSEEK_TEXT_MODEL", ""),
        frame_interval_sec=_num("FRAME_INTERVAL_SEC", 5.0),
        max_frames_per_segment=_num("MAX_FRAMES_PER_SEGMENT", 120),
        max_frames_per_request=_num("MAX_FRAMES_PER_REQUEST", 8),
        image_max_side=_num("IMAGE_MAX_SIDE", 512),
        jpeg_quality=_num("JPEG_QUALITY", 3),
        max_parallel_segments=_num("MAX_PARALLEL_SEGMENTS", 3),
        max_retries=_num("MAX_RETRIES", 3),
        request_timeout_sec=_num("REQUEST_TIMEOUT_SEC", 120),
        max_requests_per_run=_num("MAX_REQUESTS_PER_RUN", 200),
        data_dir=Path(_get("DATA_DIR", "./data")),
        keep_frames=_get("KEEP_FRAMES", "false").lower() in ("1", "true", "yes"),
        log_level=_get("LOG_LEVEL", "INFO").upper(),
    )