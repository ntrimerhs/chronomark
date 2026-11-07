"""Small shared helpers: logging, timestamps, retries, cache keys."""
import hashlib
import json
import logging
import random
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

T = TypeVar("T")


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )


def hms(seconds: float) -> str:
    """Absolute timestamp as HH:MM:SS."""
    total = max(0, int(seconds))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def retry_call(fn: Callable[[], T], attempts: int = 3, base_delay: float = 1.5) -> T:
    """Retry with exponential backoff plus jitter."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - retried by design
            last_error = exc
            if attempt == attempts - 1:
                break
            delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
            logging.warning("attempt %d failed (%s); retrying in %.1fs", attempt + 1, exc, delay)
            time.sleep(delay)
    raise RuntimeError(f"failed after {attempts} attempts: {last_error}") from last_error


def cache_key(*parts: Any) -> str:
    """Stable SHA-256 of the given parts, used to cache analysis results."""
    payload = json.dumps(parts, sort_keys=True, default=str).encode()
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default