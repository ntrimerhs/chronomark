import gc
import json
import os
import threading
import time

from dotenv import load_dotenv

load_dotenv()

LOCAL_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
LOCAL_MODEL_DIM = 384

# Embeddings come from Voyage AI when a key is present, and from the local
# MiniLM model otherwise. The two produce different vector sizes (1024 vs 384),
# so the collection they are written to is named after the dimension: switching
# provider writes a new collection and leaves the old one intact as a backup
# instead of silently mixing vectors of two widths in one index.
VOYAGE_API_KEY = (os.getenv("VOYAGE_API_KEY") or "").strip()
VOYAGE_MODEL = os.getenv("VOYAGE_MODEL", "voyage-4")
VOYAGE_DIM = int(os.getenv("VOYAGE_DIM", "1024") or "1024")
VOYAGE_BASE_URL = os.getenv("VOYAGE_BASE_URL", "https://api.voyageai.com/v1").rstrip("/")
VOYAGE_BATCH = int(os.getenv("VOYAGE_BATCH", "128") or "128")
# Voyage meters tokens per minute as well as requests per minute. An account
# without a payment method runs at 3 RPM / 10K TPM, which a 128-text batch blows
# through immediately (429). VOYAGE_BATCH_TOKENS keeps one request inside that
# budget, and VOYAGE_MIN_INTERVAL_SEC spaces the requests out; both are ignored
# on a paid account, where the defaults are simply never reached.
VOYAGE_BATCH_TOKENS = int(os.getenv("VOYAGE_BATCH_TOKENS", "0") or "0")
VOYAGE_MIN_INTERVAL_SEC = float(os.getenv("VOYAGE_MIN_INTERVAL_SEC", "0") or "0")
_VOYAGE_LAST_CALL = 0.0
EMBEDDING_PROVIDER = (os.getenv("EMBEDDING_PROVIDER") or "auto").strip().lower()

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
    """Which embedding backend is live: 'voyage' or 'local'.

    EMBEDDING_PROVIDER pins the choice; 'auto' (the default) uses Voyage when a
    key is configured and the local model when there is none, so a missing key
    is never a startup failure -- it is just the cheaper, older path.
    """
    if EMBEDDING_PROVIDER == "local":
        return "local"
    if EMBEDDING_PROVIDER == "voyage":
        return "voyage" if VOYAGE_API_KEY else "local"
    return "voyage" if VOYAGE_API_KEY else "local"


def embedding_dimension() -> int:
    """Width of the vectors this process writes, so the store can match it."""
    return VOYAGE_DIM if provider() == "voyage" else LOCAL_MODEL_DIM


def _normalise(vector: list[float]) -> list[float]:
    total = sum(value * value for value in vector) ** 0.5
    if not total:
        return vector
    return [value / total for value in vector]


def _voyage_request(batch: list[str], input_type: str) -> list[list[float]]:
    """One batched call to Voyage, retried on rate limits and 5xx."""
    import requests

    global _VOYAGE_LAST_CALL
    if VOYAGE_MIN_INTERVAL_SEC > 0:
        wait_for = VOYAGE_MIN_INTERVAL_SEC - (time.time() - _VOYAGE_LAST_CALL)
        if wait_for > 0:
            time.sleep(wait_for)

    body = {
        "input": batch,
        "model": VOYAGE_MODEL,
        "input_type": input_type,
        # Matryoshka: ask for the width the collection was created with, so the
        # store's vector size never has to move when the model's default does.
        "output_dimension": VOYAGE_DIM,
    }
    headers = {
        "Authorization": f"Bearer {VOYAGE_API_KEY}",
        "Content-Type": "application/json",
    }

    last_error = None
    for attempt in range(5):
        try:
            _VOYAGE_LAST_CALL = time.time()
            response = requests.post(
                f"{VOYAGE_BASE_URL}/embeddings", json=body, headers=headers, timeout=180
            )
            if response.status_code == 400 and "output_dimension" in response.text:
                # Older API surface: drop the request-width hint and trim the
                # vectors here instead (MRL keeps the leading dimensions valid).
                body.pop("output_dimension", None)
                raise RuntimeError("retry without output_dimension")
            if response.status_code == 429 or response.status_code >= 500:
                raise RuntimeError(f"{response.status_code}: {response.text[:200]}")
            response.raise_for_status()
            rows = response.json().get("data") or []
            vectors = [None] * len(batch)
            for row in rows:
                index = int(row.get("index", 0))
                vector = list(row.get("embedding") or [])
                if VOYAGE_DIM and len(vector) > VOYAGE_DIM:
                    vector = vector[:VOYAGE_DIM]
                vectors[index] = _normalise(vector)
            if any(vector is None for vector in vectors):
                raise RuntimeError("Voyage returned fewer vectors than inputs")
            return vectors
        except Exception as error:
            last_error = error
            wait = min(30, 2 ** attempt)
            print(f"[Embed] voyage attempt {attempt + 1} failed: {error} (retrying in {wait}s)")
            time.sleep(wait)

    raise RuntimeError(f"Voyage embeddings failed: {last_error}")


def _voyage_batches(texts: list[str]):
    """Split texts into requests that fit both the batch and token budgets.

    Roughly four characters per token, which is close enough for Latin and
    Greek prose and errs on the safe side for the rate-limited tiers.
    """
    if VOYAGE_BATCH_TOKENS <= 0:
        for start in range(0, len(texts), VOYAGE_BATCH):
            yield texts[start : start + VOYAGE_BATCH]
        return

    batch: list[str] = []
    tokens = 0
    for text in texts:
        estimate = max(1, len(text) // 4)
        if batch and (tokens + estimate > VOYAGE_BATCH_TOKENS or len(batch) >= VOYAGE_BATCH):
            yield batch
            batch, tokens = [], 0
        batch.append(text)
        tokens += estimate
    if batch:
        yield batch


def _voyage_encode(texts: list[str], input_type: str) -> list[list[float]]:
    vectors: list[list[float]] = []
    for batch in _voyage_batches(texts):
        vectors.extend(_voyage_request(batch, input_type))
    return vectors


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


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Vectors for content that is being indexed."""
    if not texts:
        return []
    if provider() == "voyage":
        return _voyage_encode(texts, "document")
    return _encode(texts).tolist()


def warm_up():
    """Force the lazy model load now instead of on the first real embed call.

    Call this from a background thread at server startup so the ~5-15s load
    cost lands before a user's first upload, not inside it. With Voyage there is
    no local model to load, so this only reports which backend is live.
    """
    if provider() == "voyage":
        print(f"[Embed] voyage {VOYAGE_MODEL} ({VOYAGE_DIM}d) via API")
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
    """Vector for a question, in the same space as the indexed documents.

    Voyage is trained asymmetrically: a query is embedded with input_type
    "query" and content with "document", which is why the two paths differ.
    """
    if provider() == "voyage":
        return _voyage_encode([question], "query")[0]
    # Goes through _encode so a query also counts as activity and cannot be
    # overtaken by the idle unloader.
    return _encode([question])[0].tolist()
