import gc
import json
import os
import threading
import time

from dotenv import load_dotenv

load_dotenv()

EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# Encoding is CPU work on a 2-core box, and torch happily grabs every core by
# default: while it embeds, the ffmpeg decode and the API itself stall. One
# thread is enough for a few hundred short texts and leaves a core free.
EMBEDDING_THREADS = int(os.getenv("EMBEDDING_THREADS", "1") or "1")
# Batch size drives peak memory more than speed on this class of machine.
EMBEDDING_BATCH = int(os.getenv("EMBEDDING_BATCH", "32") or "32")

# The model costs ~470 MB resident, which on a 3.8 GB box is a sixth of the
# machine sitting idle between uploads. After this long with no encoding, the
# weights are dropped and reloaded on the next request. Set 0 to keep it loaded.
EMBEDDING_IDLE_UNLOAD_SEC = float(os.getenv("EMBEDDING_IDLE_UNLOAD_SEC", "900") or "0")

_MODEL_LOCK = threading.RLock()
_unloader_started = False
_idle_since = time.time()

# Loaded lazily on first use instead of at import time, so `uvicorn` starts
# instantly; the ~5-15s model load cost is paid on the first embed call.
_model = None


def _start_idle_unloader():
    """Drop the model after a quiet spell, in a daemon thread."""
    global _unloader_started
    if _unloader_started or EMBEDDING_IDLE_UNLOAD_SEC <= 0:
        return
    _unloader_started = True

    def _watch():
        global _model
        while True:
            time.sleep(60)
            try:
                with _MODEL_LOCK:
                    if _model is None:
                        continue
                    if time.time() - _idle_since < EMBEDDING_IDLE_UNLOAD_SEC:
                        continue
                    _model = None
                    gc.collect()
                    print(
                        f"[Embed] model unloaded after "
                        f"{int(EMBEDDING_IDLE_UNLOAD_SEC / 60)} min idle "
                        "(reloads on the next request)"
                    )
            except Exception as error:
                print(f"[Embed] idle unload skipped: {error}")

    threading.Thread(target=_watch, name="embedding-idle-unload", daemon=True).start()


def _get_model():
    global _model, _idle_since
    with _MODEL_LOCK:
        if _model is None:
            import torch
            from sentence_transformers import SentenceTransformer

            torch.set_num_threads(EMBEDDING_THREADS)
            started = time.perf_counter()
            _model = SentenceTransformer(EMBEDDING_MODEL)
            print(f"[Embed] model loaded in {time.perf_counter() - started:.1f}s")
        _idle_since = time.time()
        return _model


def _encode(texts, batch_size=None):
    """Encode under the same lock the unloader takes.

    Without this a request could be halfway through `encode` when the idle
    thread drops the weights underneath it.
    """
    global _idle_since
    with _MODEL_LOCK:
        model = _get_model()
        _idle_since = time.time()
        return model.encode(
            texts,
            batch_size=batch_size or EMBEDDING_BATCH,
            show_progress_bar=False,
        )


def warm_up():
    """Force the lazy model load now instead of on the first real embed call.

    Call this from a background thread at server startup so the ~5-15s load
    cost lands before a user's first upload, not inside it.
    """
    _get_model()
    _start_idle_unloader()


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

    embeddings = _encode(texts).tolist()

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
    # Goes through _encode so a query also counts as activity and cannot be
    # overtaken by the idle unloader.
    return _encode([question])[0].tolist()
