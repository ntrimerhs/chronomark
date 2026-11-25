"""Move pre-scoping R2 objects into their owner's directory.

Before per-account storage every document landed at ``documents/<uuid>-<name>``
and every account could see every file. This script gives the existing library
an owner: it copies each object into ``documents/<dir>/`` (the directory derived
from that account's user id), records ``owner_id`` in the document's metadata
and only then deletes the old key.

It is deliberately copy-first: the API keeps working on the old key until the
new one is confirmed to exist with the same size, so an interrupted run leaves
a duplicate, never a hole. Re-running it is safe -- objects already in the
owner's directory are only stamped, not moved.

    docker compose exec -T backend python scripts/migrate_scopes.py \
        --owner 5b5983c2-6eb0-4ceb-adf4-7e0698cc6d4b --dry-run
    docker compose exec -T backend python scripts/migrate_scopes.py \
        --owner 5b5983c2-6eb0-4ceb-adf4-7e0698cc6d4b
"""

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from services import r2_service, user_scope  # noqa: E402

DOCS_DIR = pathlib.Path(__file__).resolve().parent.parent / "documents"


def _save(document: dict) -> None:
    path = DOCS_DIR / f"{document['doc_id']}.json"
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False)
    tmp.replace(path)


def _move(client, key: str, new_key: str) -> None:
    """Copy, verify the size, then delete the old object."""
    source = client.head_object(Bucket=r2_service.R2_BUCKET_NAME, Key=key)
    size = int(source["ContentLength"])
    client.copy_object(
        Bucket=r2_service.R2_BUCKET_NAME,
        Key=new_key,
        CopySource={"Bucket": r2_service.R2_BUCKET_NAME, "Key": key},
    )
    copied = client.head_object(Bucket=r2_service.R2_BUCKET_NAME, Key=new_key)
    if int(copied["ContentLength"]) != size:
        raise SystemExit(
            f"copy of {key} is {copied['ContentLength']} bytes, expected {size}; "
            "stopping before anything is deleted"
        )
    client.delete_object(Bucket=r2_service.R2_BUCKET_NAME, Key=key)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", required=True, help="user id to assign the library to")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--keep-old", action="store_true", help="copy but do not delete")
    args = parser.parse_args()

    prefix = user_scope.directory("documents", args.owner)
    client = r2_service._get_client()
    print(f"owner directory: {prefix}")

    moved = stamped = skipped = 0
    for path in sorted(DOCS_DIR.glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                document = json.load(handle)
        except Exception as error:  # noqa: BLE001
            print(f"  {path.name}: unreadable ({error})")
            skipped += 1
            continue

        doc_id = document.get("doc_id")
        key = str(document.get("file_key") or "")
        if not doc_id:
            print(f"  {path.name}: no doc_id")
            skipped += 1
            continue

        if document.get("owner_id"):
            skipped += 1
            continue

        if not key:
            print(f"  {doc_id}: no stored file, stamping owner only")
            if not args.dry_run:
                document["owner_id"] = args.owner
                _save(document)
            stamped += 1
            continue

        if key.startswith(prefix):
            print(f"  {doc_id}: already in the owner directory")
            if not args.dry_run:
                document["owner_id"] = args.owner
                _save(document)
            stamped += 1
            continue

        new_key = prefix + key.rsplit("/", 1)[-1]
        print(f"  {doc_id}: {key} -> {new_key}")
        if args.dry_run:
            moved += 1
            continue

        if not args.keep_old:
            _move(client, key, new_key)
        document["owner_id"] = args.owner
        document["file_key"] = new_key
        _save(document)
        moved += 1

    print(f"\nmoved {moved}, stamped {stamped}, skipped {skipped}")
    if args.dry_run:
        print("(dry run: nothing was written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
