"""One-off migration: embedded Qdrant (local sqlite folder) -> Qdrant server.

Run with the backend venv while no process holds the qdrant_data lock:

    cd backend
    .\.venv\Scripts\python.exe migrate_qdrant_to_server.py

Reads every point (vector + payload) from ./qdrant_data and re-upserts it
into the server at QDRANT_URL (default http://localhost:6333), recreating
the same collections. Safe to re-run: upserts are idempotent per point id.
"""

import sys

from qdrant_client import QdrantClient, models

SRC = "./qdrant_data"
DST_URL = __import__("os").getenv("QDRANT_URL", "http://localhost:6333")
COLLECTIONS = {
    "video_text_segments": 384,
    "video_frames": 512,
}


def main():
    src = QdrantClient(path=SRC)
    dst = QdrantClient(url=DST_URL)

    for name, dim in COLLECTIONS.items():
        if not src.collection_exists(name):
            print(f"[migrate] {name}: not present in local store, skipped")
            continue

        if not dst.collection_exists(name):
            dst.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(
                    size=dim,
                    distance=models.Distance.COSINE,
                ),
            )

        migrated = 0
        offset = None
        while True:
            records, offset = src.scroll(
                collection_name=name,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            if not records:
                break
            points = [
                models.PointStruct(
                    id=r.id,
                    vector=list(r.vector or []),
                    payload=r.payload or {},
                )
                for r in records
            ]
            dst.upsert(collection_name=name, points=points)
            migrated += len(points)
            if offset is None:
                break

        print(
            f"[migrate] {name}: {migrated} points -> {DST_URL} "
            f"(server now has {dst.count(collection_name=name).count})"
        )

    print("[migrate] done")


if __name__ == "__main__":
    sys.exit(main())
