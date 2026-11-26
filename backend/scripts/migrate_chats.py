"""Bring the conversations that already existed into the new history.

Until today a document's conversations lived only in `backend/chats/<doc_id>.json`
and a chat with no file behind it was not stored at all. The sidebar now lists
conversations, so everything from before is invisible -- a user with weeks of
reading opens the app and sees nothing.

This walks the documents that have an owner, and for each one:

  * a document with chats  -> one conversation per chat, with its messages,
  * a document without any  -> one empty conversation, so the pages stay reachable.

Each record carries `source` so a second run does nothing. Nothing is deleted:
the old chat files stay where they are.
"""

import json
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import conversations  # noqa: E402

DOCS_DIR = BASE / "documents"
CHATS_DIR = BASE / "chats"


def _existing_sources(owner_id: str) -> set:
    keys = set()
    for item in conversations.list_for(owner_id):
        record = conversations.get(item["chat_id"], owner_id)
        if record and record.get("source"):
            keys.add(record["source"])
    return keys


def _store(owner_id, title, document_id, messages, source, created_at, updated_at):
    record = conversations.create(owner_id, title)
    record["document_id"] = document_id
    record["messages"] = messages
    record["source"] = source
    record["created_at"] = created_at or record["created_at"]
    record["updated_at"] = updated_at or record["updated_at"]
    conversations._write(record)
    return record


def main() -> int:
    made_chats = made_docs = skipped = 0
    for path in sorted(DOCS_DIR.glob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        doc_id = document.get("doc_id")
        owner = document.get("owner_id")
        if not doc_id or not owner:
            continue

        name = pathlib.Path(str(document.get("file_name") or "")).stem or "Document"
        created = document.get("created_at") or 0
        known = _existing_sources(owner)

        chat_file = CHATS_DIR / f"{doc_id}.json"
        chats = []
        if chat_file.exists():
            try:
                chats = json.loads(chat_file.read_text(encoding="utf-8")).get("chats") or []
            except (OSError, ValueError):
                chats = []

        if not chats:
            source = f"doc:{doc_id}:"
            if source in known:
                skipped += 1
                continue
            _store(owner, name, doc_id, [], source, created, created)
            made_docs += 1
            print(f"  {doc_id}: one empty conversation ({name})")
            continue

        for chat in chats:
            source = f"doc:{doc_id}:{chat.get('id')}"
            if source in known:
                skipped += 1
                continue
            messages = [
                {
                    "role": "assistant" if m.get("role") == "assistant" else "user",
                    "content": m.get("content") or "",
                    "at": m.get("at") or 0,
                }
                for m in (chat.get("messages") or [])
                if (m.get("content") or "").strip()
            ]
            _store(
                owner,
                chat.get("title") or name,
                doc_id,
                messages,
                source,
                chat.get("created_at") or created,
                chat.get("updated_at") or created,
            )
            made_chats += 1
            print(f"  {doc_id}: conversation '{chat.get('title')}' ({len(messages)} messages)")

    print(f"\nconversations from chats: {made_chats}")
    print(f"conversations without a chat: {made_docs}")
    print(f"already there: {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
