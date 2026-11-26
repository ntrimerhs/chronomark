"""Conversations that are not about a file.

A reader can press send before uploading anything: the model answers, and that
exchange is worth keeping. It has no document and no recording behind it, so it
cannot live in `chats/<doc_id>.json` (that store is keyed by document) -- one
JSON file per conversation, owned by the account that started it, in its own
directory.

Same file-store reasoning as the rest of the queue: a rename or a delete is an
atomic write or an unlink, and a restart loses nothing.
"""

import json
import re
import threading
import time
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STORE_DIR = BASE_DIR / "chats" / "general"
STORE_DIR.mkdir(parents=True, exist_ok=True)

_LOCK = threading.Lock()
_ID_RE = re.compile(r"[^A-Za-z0-9_-]")
TITLE_MAX = 60


def _path(chat_id: str) -> Path:
    safe = _ID_RE.sub("", str(chat_id or ""))
    if not safe:
        raise ValueError("invalid chat id")
    return STORE_DIR / f"{safe}.json"


def _read(chat_id: str) -> dict | None:
    try:
        return json.loads(_path(chat_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(record: dict) -> None:
    path = _path(record["id"])
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _owned(record: dict | None, owner_id: str) -> dict | None:
    if not record:
        return None
    if str(record.get("owner_id") or "") != str(owner_id):
        return None
    return record


def create(owner_id: str, title: str = "New conversation") -> dict:
    record = {
        "id": f"cv_{uuid.uuid4().hex[:10]}",
        "owner_id": str(owner_id),
        "title": (title or "New conversation")[:TITLE_MAX],
        "created_at": time.time(),
        "updated_at": time.time(),
        "messages": [],
    }
    with _LOCK:
        _write(record)
    return record


def get(chat_id: str, owner_id: str) -> dict | None:
    return _owned(_read(chat_id), owner_id)


def attach(chat_id: str, owner_id: str, kind: str, target: str) -> dict | None:
    """Bind a document or a recording to the conversation that uploaded it.

    One conversation, one subject: uploading inside a chat must not open a second
    chat, so the file lands on the conversation that was already there.
    """
    field = {"document": "document_id", "video": "video_id"}.get(str(kind))
    if field is None or not str(target or "").strip():
        return None
    with _LOCK:
        record = _owned(_read(chat_id), owner_id)
        if record is None:
            return None
        record[field] = str(target)
        record["updated_at"] = time.time()
        _write(record)
        return record


def list_for(owner_id: str) -> list:
    """Newest first, without the messages -- the sidebar needs names, not text."""
    items = []
    for path in STORE_DIR.glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if str(record.get("owner_id")) != str(owner_id):
            continue
        items.append(
            {
                "chat_id": record.get("id"),
                "title": record.get("title") or "Conversation",
                "created_at": record.get("created_at"),
                "updated_at": record.get("updated_at"),
                "message_count": len(record.get("messages") or []),
                # The file the conversation is about, if it has one. The sidebar
                # draws one row per conversation, never one per file.
                "document_id": record.get("document_id"),
                "video_id": record.get("video_id"),
            }
        )
    items.sort(key=lambda item: item.get("updated_at") or 0, reverse=True)
    return items


def append_turn(chat_id: str, owner_id: str, question: str, answer: str) -> dict | None:
    """Store one exchange. Returns the record, or None if it is not theirs."""
    with _LOCK:
        record = _owned(_read(chat_id), owner_id)
        if record is None:
            return None
        messages = record.setdefault("messages", [])
        messages.append({"role": "user", "content": question, "at": time.time()})
        messages.append({"role": "assistant", "content": answer, "at": time.time()})
        record["updated_at"] = time.time()
        _write(record)
        return record


def rename(chat_id: str, owner_id: str, title: str) -> dict | None:
    clean = " ".join(str(title or "").split())[:TITLE_MAX]
    if not clean:
        return None
    with _LOCK:
        record = _owned(_read(chat_id), owner_id)
        if record is None:
            return None
        record["title"] = clean
        record["renamed_by_user"] = True
        record["updated_at"] = time.time()
        _write(record)
        return record


def set_generated_title(chat_id: str, owner_id: str, title: str) -> dict | None:
    """Name a conversation from its own answer -- never over a reader's rename."""
    clean = " ".join(str(title or "").split())[:TITLE_MAX]
    if not clean:
        return None
    with _LOCK:
        record = _owned(_read(chat_id), owner_id)
        if record is None or record.get("renamed_by_user"):
            return None
        record["title"] = clean
        record["updated_at"] = time.time()
        _write(record)
        return record


def remove(chat_id: str, owner_id: str) -> bool:
    with _LOCK:
        record = _owned(_read(chat_id), owner_id)
        if record is None:
            return False
        try:
            _path(chat_id).unlink(missing_ok=True)
        except OSError:
            return False
    return True
