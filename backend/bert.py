import json
import os

from dotenv import load_dotenv

load_dotenv()

EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Encoding is CPU work on a 2-core box, and torch happily grabs every core by
# default: while it embeds, the ffmpeg decode and the API itself stall. One
# thread is enough for a few hundred short texts and leaves a core free.
EMBEDDING_THREADS = int(os.getenv("EMBEDDING_THREADS", "1") or "1")
# Batch size drives peak memory more than speed on this class of machine.
EMBEDDING_BATCH = int(os.getenv("EMBEDDING_BATCH", "32") or "32")

# Loaded lazily on first use instead of at import time, so `uvicorn` starts
# instantly; the ~5-15s model load cost is paid on the first embed call.
_model = None


def _get_model():
    global _model
    if _model is None:
        import torch
        from sentence_transformers import SentenceTransformer

        torch.set_num_threads(EMBEDDING_THREADS)
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def warm_up():
    """Force the lazy model load now instead of on the first real embed call.

    Call this from a background thread at server startup so the ~5-15s load
    cost lands before a user's first upload, not inside it.
    """
    _get_model()


def create_embeddings(transcript_json_path: str):
    with open(transcript_json_path, "r", encoding="utf-8") as f:
        transcript = json.load(f)

    return create_embeddings_from_transcript(transcript)


def create_embeddings_from_transcript(transcript: dict):
    chunks = transcript.get("segments") or transcript.get("chunks") or []

    valid_chunks = [c for c in chunks if (c.get("text") or "").strip()]
    texts = [c["text"].strip() for c in valid_chunks]

    if not texts:
        return []

    # Encode all texts in one batch — orders of magnitude faster than one-by-one API calls
    embeddings = _get_model().encode(
        texts, batch_size=EMBEDDING_BATCH, show_progress_bar=False
    ).tolist()

    results = []
    for chunk, text, embedding in zip(valid_chunks, texts, embeddings):
        timestamp = chunk.get("timestamp")
        if not timestamp:
            timestamp = [chunk.get("start"), chunk.get("end")]

        results.append({
            "text": text,
            "timestamp": timestamp,
            # Documents address their chunks by page: without carrying it here
            # the page number died between extraction and the Qdrant payload.
            "page": chunk.get("page"),
            "embedding": embedding,
        })

    return results


def embed_query(question: str):
    return _get_model().encode(question).tolist()