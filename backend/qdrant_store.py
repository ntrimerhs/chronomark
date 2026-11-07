# import uuid

# from qdrant_client import QdrantClient, models

# # Embedded local mode: stores data on disk, no server/URL needed.
# client = QdrantClient(path="./qdrant_data")

# # QDRANT_URL = os.getenv("QDRANT_URL", "[localhost](http://localhost:6333)")
# # QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None

# # client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)

# TEXT_COLLECTION = "video_text_segments"
# FRAME_COLLECTION = "video_frames"

import uuid

from qdrant_client import QdrantClient, models

# Embedded local mode: stores data on disk, no server/URL needed.
client = QdrantClient(path="./qdrant_data")

TEXT_COLLECTION = "video_text_segments"
FRAME_COLLECTION = "video_frames"


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


def store_text_embeddings(video_id: str, segments: list[dict], id_prefix: str = "text"):
    points = []

    for i, seg in enumerate(segments):
        timestamp = seg.get("timestamp") or [None, None]
        start = timestamp[0]
        end = timestamp[1]

        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{video_id}_{id_prefix}_{i}"))

        points.append(
            models.PointStruct(
                id=point_id,
                vector=seg["embedding"],
                payload={
                    "video_id": video_id,
                    "type": "text",
                    "text": seg.get("text"),
                    "start": start,
                    "end": end,
                },
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