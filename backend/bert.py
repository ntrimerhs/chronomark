import gc
import json
import os
import threading
import time

from dotenv import load_dotenv

load_dotenv()

LOCAL_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
LOCAL_MODEL_DIM = 384

# Embeddings come from OpenAI's text-embedding-3-small when a key is present, and
# from the local MiniLM model otherwise. The two produce different vector sizes
# (1536 vs 384), so the collection they are written to is named after the
# dimension: switching provider writes a new collection and leaves the old one
# intact as a backup instead of silently mixing vectors of two widths in one
# index.
EMBEDDING_PROVIDER = (os.getenv("EMBEDDING_PROVIDER") or "auto").strip().lower()
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536") or "1536")
# A dedicated key keeps the embedding meter separable from the chat/transcription
# key; when it is absent the ordinary OPENAI_API_KEY is used.
EMBEDDING_API_KEY = (
    os.getenv("EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
).strip()
EMBEDDING_BASE_URL = (os.getenv("EMBEDDING_BASE_URL") or "").strip() or None
EMBEDDING_REQUEST_BATCH = int(os.getenv("EMBEDDING_REQUEST_BATCH", "96") or "96")

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
_remote_client = None


def _release_memory():
    """Hand freed pages back to the OS.

    Dropping the Python reference is not enough: torch and the C++ allocator keep
    the arena, so RSS barely moves. glibc's malloc_trim is the only thing that
    returns it, and it exists on Linux only, hence the quiet fallback.
    """
    gc.collect()
    try:
        import ctypes

        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


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
                    _release_memory()
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
            _model = SentenceTransformer(LOCAL_MODEL)
            print(f"[Embed] model loaded in {time.perf_counter() - started:.1f}s")
        _idle_since = time.time()
        return _model


def provider() -> str:
    """Which embedding backend is live: 'openai' or 'local'.

    EMBEDDING_PROVIDER pins the choice; 'auto' (the default) uses OpenAI when a
    key is configured and the local model when there is none, so a missing key is
    never a startup failure -- it is just the older, free path.
    """
    if EMBEDDING_PROVIDER == "local":
        return "local"
    if EMBEDDING_PROVIDER == "openai":
        return "openai" if EMBEDDING_API_KEY else "local"
    return "openai" if EMBEDDING_API_KEY else "local"


def embedding_dimension() -> int:
    """Width of the vectors this process writes, so the store can match it."""
    return EMBEDDING_DIM if provider() == "openai" else LOCAL_MODEL_DIM


def _normalise(vector: list) -> list:
    total = sum(value * value for value in vector) ** 0.5
    if not total:
        return list(vector)
    return [value / total for value in vector]


def _remote_client_instance():
    global _remote_client
    with _MODEL_LOCK:
        if _remote_client is None:
            from openai import OpenAI

            _remote_client = OpenAI(api_key=EMBEDDING_API_KEY, base_url=EMBEDDING_BASE_URL)
        return _remote_client


def _openai_embed(batch: list[str]) -> list[list[float]]:
    """One batched embeddings call, retried on rate limits and 5xx."""
    client = _remote_client_instance()
    last_error = None
    for attempt in range(6):
        try:
            response = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
            rows = sorted(response.data, key=lambda row: row.index)
            vectors = []
            for row in rows:
                vector = list(row.embedding)
                # text-embedding-3-* support truncation via `dimensions`; if the
                # configured width is smaller, keeping the leading values and
                # renormalising is the same operation done by hand.
                if EMBEDDING_DIM and len(vector) > EMBEDDING_DIM:
                    vector = _normalise(vector[:EMBEDDING_DIM])
                vectors.append(vector)
            if len(vectors) != len(batch):
                raise RuntimeError(f"got {len(vectors)} vectors for {len(batch)} inputs")
            return vectors
        except Exception as error:
            last_error = error
            wait = min(30, 2 ** attempt)
            print(f"[Embed] openai attempt {attempt + 1} failed: {error} (retrying in {wait}s)")
            time.sleep(wait)
    raise RuntimeError(f"OpenAI embeddings failed: {last_error}")


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Vectors for content that is being indexed."""
    if not texts:
        return []
    if provider() == "openai":
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBEDDING_REQUEST_BATCH):
            vectors.extend(
                _openai_embed(texts[start : start + EMBEDDING_REQUEST_BATCH])
            )
        return vectors
    return _encode(texts).tolist()


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

    Call this from a background thread at server startup so the ~5-15s load cost
    lands before a user's first upload, not inside it. With OpenAI there is no
    local model to load, so this only reports which backend is live.
    """
    if provider() == "openai":
        print(f"[Embed] {EMBEDDING_MODEL} ({EMBEDDING_DIM}d) via OpenAI")
        return
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

    embeddings = embed_documents(texts)

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
    """Vector for a question, in the same space as the indexed documents."""
    if provider() == "openai":
        return _openai_embed([question])[0]
    # Goes through _encode so a query also counts as activity and cannot be
    # overtaken by the idle unloader.
    return _encode([question])[0].tolist()
