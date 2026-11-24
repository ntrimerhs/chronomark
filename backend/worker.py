"""Background worker: the only process that runs an ingestion job.

The API accepts an upload, stores it in R2 (or in the shared uploads directory for
documents), writes one job file and answers immediately. This process watches that
queue and does the slow part: Document AI, Groq, OpenAI, Qdrant.

    docker compose logs -f worker

Concurrency is the number of jobs this one worker runs at once (WORKER_CONCURRENCY,
default 2). Jobs beyond that wait in the directory -- which is the point: the API
stays instant no matter how many people upload at the same time.
"""

import os
import threading
import time
import traceback

import jobs as job_store


def _load_pipeline():
    """Import the backend lazily: importing main costs a few seconds of warmup."""
    import main as backend

    return backend


def _run_document(backend, job):
    # The job measures its own elapsed time with time.perf_counter(); handing it
    # enqueued_at (an epoch) produced a negative "ready in ...s" line.
    backend._process_document_job(
        job["job_id"],
        job["doc_id"],
        job["temp_path"],
        job["file_name"],
        job.get("file_key") or "",
        time.perf_counter(),
    )


def _run_video(backend, job):
    backend._process_r2_video_job(
        job["job_id"],
        job["file_key"],
        job["display_name"],
        job["video_id"],
        time.perf_counter(),
    )


HANDLERS = {
    "document": _run_document,
    "video": _run_video,
}


def _process(claimed_path, job, backend, error_lock):
    kind = job.get("kind")
    handler = HANDLERS.get(kind)
    job_id = job.get("job_id")
    try:
        if handler is None:
            raise RuntimeError(f"unknown job kind '{kind}'")
        print(f"[Worker] {kind} {job_id} started", flush=True)
        handler(backend, job)
        print(f"[Worker] {kind} {job_id} done", flush=True)
    except Exception as error:
        with error_lock:
            print(f"[Worker] {kind} {job_id} failed: {error}", flush=True)
            traceback.print_exc()
        try:
            job_store.update(
                job_id,
                status="failed",
                stage="failed",
                progress=100,
                error=str(error),
            )
        except Exception:
            pass
    finally:
        job_store.finish(claimed_path)


def main():
    concurrency = int(os.getenv("WORKER_CONCURRENCY", "2") or "2")
    poll_seconds = float(os.getenv("WORKER_POLL_SECONDS", "2") or "2")

    print(f"[Worker] concurrency={concurrency} queue={job_store.QUEUE_DIR}", flush=True)
    backend = _load_pipeline()
    print("[Worker] pipeline loaded; watching the queue", flush=True)

    error_lock = threading.Lock()
    active: list[threading.Thread] = []

    while True:
        active = [thread for thread in active if thread.is_alive()]

        if len(active) < concurrency:
            claimed = job_store.claim()
            if claimed is None:
                time.sleep(poll_seconds)
                continue
            claimed_path, job = claimed
            print(
                f"[Worker] claimed {job.get('kind')} {job.get('job_id')} "
                f"({len(active) + 1}/{concurrency} active)",
                flush=True,
            )
            thread = threading.Thread(
                target=_process,
                args=(claimed_path, job, backend, error_lock),
                name=f"job-{job.get('job_id')}",
                daemon=True,
            )
            thread.start()
            active.append(thread)
            continue

        time.sleep(0.5)


if __name__ == "__main__":
    main()
