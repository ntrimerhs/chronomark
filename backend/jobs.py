"""File-based job store and queue.

The API and the worker are separate processes (and separate containers), so the
queue and the job status cannot live in a Python dict. Everything here is a small
file:

    queue/<job_id>.json        a job waiting to be picked up
    queue/<job_id>.processing  a job a worker has claimed
    jobs/<job_id>.json         the status the UI polls

Claiming is a rename, which is atomic on a POSIX filesystem: two workers cannot
take the same job. Writes are tmp-then-rename for the same reason -- a status
file is never read half-written.
"""

import json
import os
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

QUEUE_DIR = Path(os.getenv("QUEUE_DIR") or (BASE_DIR / "queue"))
JOBS_DIR = Path(os.getenv("JOBS_DIR") or (BASE_DIR / "jobs"))
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR") or (BASE_DIR / "uploads"))

for _directory in (QUEUE_DIR, JOBS_DIR, UPLOAD_DIR):
    _directory.mkdir(parents=True, exist_ok=True)


def _atomic_write(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    tmp.replace(path)


def _read(path: Path) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return None
    except Exception as error:
        print(f"[Jobs] unreadable {path.name}: {error}")
        return None


def status_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def create(job_id: str, **fields) -> dict:
    """Start a job's status file; the upload endpoint does this before replying."""
    record = {
        "job_id": job_id,
        "status": "processing",
        "stage": "queued",
        "progress": 0,
        "error": None,
        "result": None,
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    record.update(fields)
    _atomic_write(status_path(job_id), record)
    return record


def update(job_id: str, **fields) -> dict:
    """Merge progress into a job's status file (read-modify-write, single writer)."""
    record = _read(status_path(job_id)) or {"job_id": job_id}
    for key, value in fields.items():
        if value is not None:
            record[key] = value
    record["updated_at"] = time.time()
    if "progress" in record and record["progress"] is not None:
        record["progress"] = int(max(0, min(100, record["progress"])))
    _atomic_write(status_path(job_id), record)
    return record


def read(job_id: str) -> dict | None:
    return _read(status_path(job_id))


def enqueue(payload: dict) -> str:
    """Put a job in the queue. Returns its id."""
    job_id = payload["job_id"]
    payload.setdefault("enqueued_at", time.time())
    _atomic_write(QUEUE_DIR / f"{job_id}.json", payload)
    return job_id


def claim() -> tuple[Path, dict] | None:
    """Take the oldest waiting job, or None. The rename is the lock."""
    pending = sorted(QUEUE_DIR.glob("*.json"), key=lambda path: path.stat().st_mtime)
    for path in pending:
        if path.name.endswith(".tmp"):
            continue
        claimed = path.with_suffix(".processing")
        try:
            path.rename(claimed)
        except (FileNotFoundError, OSError):
            # Another worker got there first.
            continue
        payload = _read(claimed)
        if payload is None:
            claimed.unlink(missing_ok=True)
            continue
        return claimed, payload
    return None


def finish(claimed_path: Path) -> None:
    """Drop the claimed file once the job is done (status lives in jobs/)."""
    try:
        claimed_path.unlink(missing_ok=True)
    except OSError as error:
        print(f"[Jobs] could not clear {claimed_path.name}: {error}")


def release(claimed_path: Path) -> None:
    """Put a claimed job back in the queue (the worker died before finishing)."""
    try:
        claimed_path.rename(claimed_path.with_suffix(".json"))
    except OSError as error:
        print(f"[Jobs] could not requeue {claimed_path.name}: {error}")


def stats() -> dict:
    waiting = len([p for p in QUEUE_DIR.glob("*.json") if not p.name.endswith(".tmp")])
    working = len(list(QUEUE_DIR.glob("*.processing")))
    return {"waiting": waiting, "working": working}
