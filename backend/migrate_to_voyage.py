"""Re-embed the indexed corpus into the Voyage collection.

The text collection is named after the vector width, so switching embeddings
from the local MiniLM (384d) to Voyage (1024d) writes a new collection and leaves
the old one untouched -- that old collection is the backup until this migration
is verified.

Nothing is parsed again. Every point already carries the text it was indexed
from, so this reads the old collection, re-embeds those exact strings, and
writes the same point ids and payloads into the new one: a document keeps its
page numbers and figure descriptions, a video keeps its timestamps.

    docker exec chronomark-backend python migrate_to_voyage.py
"""

import os
import sys
import time

from qdrant_client import models

import bert
import qdrant_store

OLD_COLLECTION = os.getenv("OLD_TEXT_COLLECTION", "video_text_segments")
# Target is explicit: the running API may still be serving the old collection
# while this backfills the new one, so the two cannot be inferred from whoever
# started the process.
NEW_COLLECTION = os.getenv("NEW_TEXT_COLLECTION") or qdrant_store.TEXT_COLLECTION
BATCH = int(os.getenv("MIGRATE_BATCH", "128") or "128")


def _ensure_target() -> None:
    if not qdrant_store.client.collection_exists(NEW_COLLECTION):
        qdrant_store.client.create_collection(
            collection_name=NEW_COLLECTION,
            vectors_config=models.VectorParams(
                size=bert.embedding_dimension(),
                distance=models.Distance.COSINE,
            ),
        )
        print(f"[Migrate] created {NEW_COLLECTION} ({bert.embedding_dimension()}d)")
    info = qdrant_store.client.get_collection(NEW_COLLECTION)
    if "video_id" not in (info.payload_schema or {}):
        qdrant_store.client.create_payload_index(
            collection_name=NEW_COLLECTION,
            field_name="video_id",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )


def _read_all(collection: str) -> list:
    points = []
    offset = None
    while True:
        batch, offset = qdrant_store.client.scroll(
            collection_name=collection,
            with_payload=True,
            with_vectors=False,
            limit=256,
            offset=offset,
        )
        points.extend(batch)
        if offset is None:
            break
    return points


def main() -> int:
    print(f"[Migrate] provider={bert.provider()} dim={bert.embedding_dimension()}")
    print(f"[Migrate] {OLD_COLLECTION} -> {NEW_COLLECTION}")

    if OLD_COLLECTION == NEW_COLLECTION:
        print("[Migrate] source and target are the same collection; nothing to do")
        return 0

    if not qdrant_store.client.collection_exists(OLD_COLLECTION):
        print(f"[Migrate] {OLD_COLLECTION} does not exist; nothing to migrate")
        return 1

    points = _read_all(OLD_COLLECTION)
    if not points:
        print(f"[Migrate] {OLD_COLLECTION} is empty; nothing to migrate")
        return 1
    print(f"[Migrate] {len(points)} points to re-embed")

    _ensure_target()

    # Points that already exist in the target (a previous interrupted run) are
    # skipped, so re-running this is cheap and safe.
    existing = {str(point.id) for point in _read_all(NEW_COLLECTION)}
    todo = [point for point in points if str(point.id) not in existing]
    print(f"[Migrate] {len(todo)} left after skipping {len(points) - len(todo)} already written")

    started = time.perf_counter()
    written = 0
    for start in range(0, len(todo), BATCH):
        chunk = todo[start : start + BATCH]
        texts = [((point.payload or {}).get("text") or "").strip() for point in chunk]
        # A point with no text cannot be re-embedded; keep it out of the new
        # collection rather than writing a zero vector into the index.
        keep = [(point, text) for point, text in zip(chunk, texts) if text]
        if not keep:
            continue
        vectors = bert.embed_documents([text for _point, text in keep])
        if len(vectors) != len(keep):
            print(f"[Migrate] embed returned {len(vectors)} vectors for {len(keep)} texts")
            return 1
        payloads = []
        for (point, _text), vector in zip(keep, vectors):
            payloads.append(
                models.PointStruct(
                    id=point.id,
                    vector=vector,
                    payload=point.payload or {},
                )
            )
        qdrant_store.client.upsert(collection_name=NEW_COLLECTION, points=payloads)
        written += len(payloads)
        done = start + len(chunk)
        print(f"[Migrate] {done}/{len(todo)} ({written} written) {time.perf_counter() - started:.1f}s")

    total = qdrant_store.client.count(collection_name=NEW_COLLECTION).count
    old_total = qdrant_store.client.count(collection_name=OLD_COLLECTION).count
    print(f"[Migrate] done: {NEW_COLLECTION}={total} points, {OLD_COLLECTION}={old_total} (kept as backup)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
