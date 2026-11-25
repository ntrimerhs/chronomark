"""Who owns which analysed video, and when it was created.

A video leaves behind more than its file in R2: a transcript and embeddings in
shared JSON stores, frames on disk, an audio track and vectors in Qdrant, all
keyed by one video_id. Without an owner on that id, nothing stops one account
asking about another's video, and nothing can delete a user's videos on request
or on schedule. One tiny JSON file per video_id holds the owner and the clock.
"""

import json
import re
import time
from pathlib import Path

from services import user_scope

BASE_DIR = Path(__file__).resolve().parent.parent
REGISTRY_DIR = BASE_DIR / "documents" / "videos"
REGISTRY_DIR.mkdir(parents=True, exist_ok=True)

_SCOPE_CHARS = 12
_ID_RE = re.compile(r"[^A-Za-z0-9_-]")


def scoped_id(user_id: str, raw: str) -> str:
    """``<account>_<name>``: two accounts can never share a video_id."""
    prefix = user_scope.scope_of(user_id)[:_SCOPE_CHARS] + "_"
    name = _ID_RE.sub("", str(raw or ""))[:80] or "video"
    return name if name.startswith(prefix) else prefix + name


def _path(video_id: str) -> Path:
    safe = _ID_RE.sub("", str(video_id or ""))
    if not safe:
        raise ValueError("invalid video_id")
    return REGISTRY_DIR / f"{safe}.json"


def register(video_id: str, owner_id: str, file_key: str | None = None) -> None:
    path = _path(video_id)
    record = get(video_id) or {"video_id": video_id, "created_at": time.time(), "file_keys": []}
    record["owner_id"] = str(owner_id)
    if file_key and file_key not in record["file_keys"]:
        record["file_keys"].append(file_key)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record), encoding="utf-8")
    tmp.replace(path)


def get(video_id: str) -> dict | None:
    try:
        return json.loads(_path(video_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def is_owner(video_id: str, user_id: str) -> bool:
    record = get(video_id)
    return bool(record) and str(record.get("owner_id")) == str(user_id)


def all_records() -> list[dict]:
    out = []
    for path in REGISTRY_DIR.glob("*.json"):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def records_for(user_id: str) -> list[dict]:
    return [r for r in all_records() if str(r.get("owner_id")) == str(user_id)]


def remove(video_id: str) -> None:
    try:
        _path(video_id).unlink(missing_ok=True)
    except ValueError:
        pass
