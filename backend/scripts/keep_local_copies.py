"""Keep a local copy of every document that still has one in the bucket."""

import json
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import main as backend  # noqa: E402

made = skipped = missing = 0
for path in sorted(backend.DOCS_DIR.glob("*.json")):
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        continue
    doc_id = document.get("doc_id")
    suffix = pathlib.Path(str(document.get("file_name") or "")).suffix.lower()
    if not doc_id or not suffix:
        continue
    target = backend._kept_document_path(doc_id, suffix)
    if target.exists():
        skipped += 1
        continue
    key = document.get("file_key")
    if not key:
        missing += 1
        continue
    try:
        backend.r2_service.download_to_file(key, str(target))
        made += 1
        print(f"  kept {doc_id}{suffix}")
    except Exception as error:  # noqa: BLE001
        missing += 1
        print(f"  {doc_id}: not in the bucket any more ({error})")

print(f"\nkept {made}, already there {skipped}, gone from the bucket {missing}")