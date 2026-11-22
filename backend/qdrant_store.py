# import uuid

# from qdrant_client import QdrantClient, models

# # Embedded local mode: stores data on disk, no server/URL needed.
# client = QdrantClient(path="./qdrant_data")

# # QDRANT_URL = os.getenv("QDRANT_URL", "[localhost](http://localhost:6333)")
# # QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None

# # client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)

# TEXT_COLLECTION = "video_text_segments"
# FRAME_COLLECTION = "video_frames"

import os
import uuid

from dotenv import load_dotenv
from qdrant_client import QdrantClient, models

load_dotenv()

# Where the vectors live. QDRANT_URL points at a Qdrant Cloud cluster (or any
# Qdrant server) and QDRANT_API_KEY authenticates to it; a shared server is also
# concurrency-safe, where the embedded sqlite store is not -- concurrent uploads
# used to crash it with sqlite3 "bad parameter or other API misuse". Leave
# QDRANT_URL empty to fall back to the embedded local mode, which keeps
# everything in ./qdrant_data but is single-process only.
QDRANT_URL = (os.getenv("QDRANT_URL") or "").strip()
QDRANT_API_KEY = (os.getenv("QDRANT_API_KEY") or "").strip() or None

if QDRANT_URL:
    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=30)
    print(f"[Qdrant] remote: {QDRANT_URL}")
else:
    client = QdrantClient(path="./qdrant_data")
    print("[Qdrant] embedded local: ./qdrant_data (single process only)")

TEXT_COLLECTION = "video_text_segments"
FRAME_COLLECTION = "video_frames"


def _ensure_video_id_index(collection_name: str) -> None:
    """Indexed payload field for the per-video filters.

    Every search/scroll filters on video_id, and a Qdrant server (unlike the
    embedded store) rejects a filtered query with
    'Index required but not found for "video_id" of type [keyword]' unless the
    field carries a payload index. Creating it only when missing keeps this
    idempotent across restarts.
    """
    info = client.get_collection(collection_name)
    if "video_id" in (info.payload_schema or {}):
        return
    client.create_payload_index(
        collection_name=collection_name,
        field_name="video_id",
        field_schema=models.PayloadSchemaType.KEYWORD,
    )


def ensure_collections():
    if not client.collection_exists(TEXT_COLLECTION):
        client.create_collection(
            collection_name=TEXT_COLLECTION,
            vectors_config=models.VectorParams(
                size=384,
                distance=models.Distance.COSINE,
            ),
        )

    if not client.collection_exists(FRAME_COLLECTION):
        client.create_collection(
            collection_name=FRAME_COLLECTION,
            vectors_config=models.VectorParams(
                size=512,
                distance=models.Distance.COSINE,
            ),
        )

    _ensure_video_id_index(TEXT_COLLECTION)
    _ensure_video_id_index(FRAME_COLLECTION)


def clear_collections():
    """Wipe all stored points so only the most recently uploaded video's data
    is searchable. The frontend only supports one active video at a time, so
    leftover points from a previous upload would otherwise pollute /ask
    results with segments/frames from a video that's no longer displayed.

    Deletes the points, and deliberately does NOT drop the collections.
    Dropping is what this used to do, and it silently did nothing: Qdrant's
    local mode removes the collection from meta.json but leaves its
    storage.sqlite on disk, so the next ensure_collections() recreates the
    collection and adopts the orphaned file -- every point comes back. The
    store had grown to ~39k points while holding one video's worth of data,
    which slowed every upsert and search and let /ask answer from a video that
    was no longer loaded.

    The remaining count is logged so a silent failure cannot hide again.
    """
    ensure_collections()

    for name in (TEXT_COLLECTION, FRAME_COLLECTION):
        if not client.collection_exists(name):
            continue
        client.delete(
            collection_name=name,
            points_selector=models.FilterSelector(filter=models.Filter(must=[])),
        )
        remaining = client.count(collection_name=name).count
        print(f"[Qdrant] {name} after clear: {remaining} points")


def store_text_embeddings(
    video_id: str,
    segments: list[dict],
    id_prefix: str = "text",
    extra_payload: dict | None = None,
):
    """Upsert one point per segment.

    extra_payload is merged into every point's payload: documents use it to
    carry `page`, `source_type` and `file_key` alongside the fields a video
    segment already has (start/end stay empty for them).
    """
    points = []

    for i, seg in enumerate(segments):
        timestamp = seg.get("timestamp") or [None, None]
        start = timestamp[0]
        end = timestamp[1]

        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{video_id}_{id_prefix}_{i}"))

        payload = {
            "video_id": video_id,
            "type": "text",
            "text": seg.get("text"),
            "start": start,
            "end": end,
            "chunk_index": i,
        }
        if extra_payload:
            payload.update(extra_payload)
        if seg.get("page") is not None:
            payload["page"] = seg.get("page")

        points.append(
            models.PointStruct(
                id=point_id,
                vector=seg["embedding"],
                payload=payload,
            )
        )

    if points:
        client.upsert(
            collection_name=TEXT_COLLECTION,
            points=points,
        )


def store_frame_embeddings(video_id: str, frame_results: list[dict]):
    points = []

    for item in frame_results:
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{video_id}_frame_{item['frame']}"))

        points.append(
            models.PointStruct(
                id=point_id,
                vector=item["embedding"],
                payload={
                    "video_id": video_id,
                    "type": "frame",
                    "frame": item["frame"],
                    "timestamp": item.get("timestamp"),
                },
            )
        )

    if points:
        client.upsert(
            collection_name=FRAME_COLLECTION,
            points=points,
        )


def search_text(query_embedding: list[float], limit: int = 5, video_id: str | None = None):
    query_filter = None
    if video_id:
        query_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="video_id",
                    match=models.MatchValue(value=video_id),
                )
            ]
        )

    results = client.query_points(
        collection_name=TEXT_COLLECTION,
        query=query_embedding,
        limit=limit,
        with_payload=True,
        query_filter=query_filter,
    )

    return results.points


def scroll_all_text(video_id: str | None = None) -> list:
    """Return every text segment for a video, sorted by start timestamp.

    Used for summary mode so we cover the entire video instead of only the
    segments whose embedding happens to be close to the word 'summary'.
    """
    scroll_filter = None
    if video_id:
        scroll_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="video_id",
                    match=models.MatchValue(value=video_id),
                )
            ]
        )

    all_points = []
    offset = None

    while True:
        result, next_offset = client.scroll(
            collection_name=TEXT_COLLECTION,
            scroll_filter=scroll_filter,
            with_payload=True,
            with_vectors=False,
            limit=250,
            offset=offset,
        )
        all_points.extend(result)
        if next_offset is None:
            break
        offset = next_offset

    all_points.sort(key=lambda p: (p.payload.get("start") or 0))
    return all_points


def search_frames(query_embedding: list[float], limit: int = 5, video_id: str | None = None):
    """Search the frame collection using a 512-dim CLIP text embedding."""

    query_filter = None
    if video_id:
        query_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="video_id",
                    match=models.MatchValue(value=video_id),
                )
            ]
        )

    results = client.query_points(
        collection_name=FRAME_COLLECTION,
        query=query_embedding,
        limit=limit,
        with_payload=True,
        query_filter=query_filter,
    )

    return results.points