"""Consent ledger, resource ownership and retention bookkeeping.

Three rules live here so they are enforced in one place:

1. Consent. Text from a user's files and the questions they ask are sent to
   DeepSeek, which stores them in China. That transfer has no adequacy decision
   and no contractual safeguards, so the only lawful basis is the user's explicit
   consent (GDPR Art. 49(1)(a)). Consent is an append-only ledger in Supabase
   (`user_consents`); the newest row per kind wins, and a consent given to an
   older policy version does not count.

2. Ownership. Every document and video is registered to the account that
   created it, and every route that reads one checks that registry. Nothing is
   shared between accounts by accident.

3. Retention. Uploaded content (files, transcripts, vectors) is kept for
   RETENTION_HOURS and then purged. The registry keeps the owner of a purged
   resource so that its chat history, the only thing kept, stays reachable by
   that owner and nobody else.
"""

import json
import os
import re
import threading
import time
from pathlib import Path

import requests
from fastapi import HTTPException, Request

BASE_DIR = Path(__file__).resolve().parent
OWNERSHIP_DIR = Path(os.getenv("OWNERSHIP_DIR") or (BASE_DIR / "ownership"))
OWNERSHIP_DIR.mkdir(parents=True, exist_ok=True)

# Bump this when the privacy policy changes what the user agreed to: everyone is
# asked again on their next visit.
CONSENT_VERSION = os.getenv("CONSENT_VERSION", "2026-11-25")
CONSENT_KINDS = ("china_transfer", "marketing")

RETENTION_HOURS = float(os.getenv("RETENTION_HOURS", "4"))

# Resources that were created before ownership existed belong to this account.
# Leave it empty and they belong to nobody (and are purged on schedule).
LEGACY_OWNER = (os.getenv("LEGACY_OWNER_USER_ID") or "").strip()

_UUID_RE = re.compile(r"^[0-9a-fA-F-]{32,40}$")


class ConsentUnavailable(Exception):
    """The consent store cannot be reached: fail closed, never open."""


# ── Supabase REST (service key) ────────────────────────────────────────────

def _supabase():
    base = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SECRET_KEY") or ""
    if not base or not key:
        raise ConsentUnavailable("Supabase is not configured on this server")
    return base, {"apikey": key, "Authorization": f"Bearer {key}"}


def delete_auth_user(user_id: str) -> None:
    base, headers = _supabase()
    response = requests.delete(f"{base}/auth/v1/admin/users/{user_id}", headers=headers, timeout=25)
    if response.status_code not in (200, 204):
        raise RuntimeError(f"Could not delete the account ({response.status_code})")


# ── consent ledger ─────────────────────────────────────────────────────────

_CACHE_TTL = 60.0
_consent_cache: dict[str, tuple[float, dict]] = {}
_consent_lock = threading.Lock()


def get_consents(user_id: str, *, fresh: bool = False) -> dict:
    """{'china_transfer': bool, 'marketing': bool, 'version': str}."""
    now = time.time()
    if not fresh:
        with _consent_lock:
            cached = _consent_cache.get(user_id)
        if cached and cached[0] > now:
            return cached[1]

    base, headers = _supabase()
    try:
        response = requests.get(
            f"{base}/rest/v1/user_consents",
            params={
                "select": "kind,granted,version,created_at",
                "user_id": f"eq.{user_id}",
                "order": "created_at.desc",
                "limit": "200",
            },
            headers=headers,
            timeout=15,
        )
    except requests.RequestException as error:
        raise ConsentUnavailable(str(error)) from error
    if response.status_code != 200:
        raise ConsentUnavailable(f"consent store answered {response.status_code}")

    latest: dict[str, dict] = {}
    for row in response.json():
        latest.setdefault(row.get("kind"), row)

    transfer = latest.get("china_transfer") or {}
    marketing = latest.get("marketing") or {}
    state = {
        "china_transfer": bool(transfer.get("granted")) and transfer.get("version") == CONSENT_VERSION,
        "marketing": bool(marketing.get("granted")),
        "version": CONSENT_VERSION,
    }
    with _consent_lock:
        _consent_cache[user_id] = (now + _CACHE_TTL, state)
    return state


def record_consent(user_id: str, kind: str, granted: bool) -> None:
    if kind not in CONSENT_KINDS:
        raise ValueError("unknown consent kind")
    base, headers = _supabase()
    try:
        response = requests.post(
            f"{base}/rest/v1/user_consents",
            json={
                "user_id": user_id,
                "kind": kind,
                "granted": bool(granted),
                "version": CONSENT_VERSION,
            },
            headers={**headers, "Prefer": "return=minimal"},
            timeout=15,
        )
    except requests.RequestException as error:
        raise ConsentUnavailable(str(error)) from error
    if response.status_code not in (200, 201, 204):
        raise ConsentUnavailable(f"consent store answered {response.status_code}")
    with _consent_lock:
        _consent_cache.pop(user_id, None)


def has_transfer_consent(user_id: str) -> bool:
    return bool(get_consents(user_id)["china_transfer"])


# ── ownership registry ─────────────────────────────────────────────────────

_registry_lock = threading.Lock()


def _safe(resource_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "", str(resource_id or ""))


def _path(resource_id: str) -> Path:
    safe = _safe(resource_id)
    if not safe:
        raise HTTPException(status_code=400, detail="invalid id")
    return OWNERSHIP_DIR / f"{safe}.json"


def _write(path: Path, record: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def register(resource_id: str, user_id: str, kind: str, file_key: str | None = None) -> dict:
    """Record who owns a resource. Calling it again adds a file key (chunked
    uploads put several objects in R2 under one video id)."""
    path = _path(resource_id)
    with _registry_lock:
        record = None
        if path.exists():
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                record = None
        if record and record.get("owner") not in (None, user_id):
            raise HTTPException(status_code=409, detail="That name is already taken")
        if not record:
            record = {
                "id": _safe(resource_id),
                "owner": user_id,
                "kind": kind,
                "created_at": time.time(),
                "file_keys": [],
            }
        if file_key and file_key not in record["file_keys"]:
            record["file_keys"].append(file_key)
        _write(path, record)
    return record


def get_record(resource_id: str) -> dict | None:
    try:
        path = _path(resource_id)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except HTTPException:
        return None
    except Exception:
        return None


def owner_of(resource_id: str) -> str | None:
    record = get_record(resource_id)
    if record and record.get("owner"):
        return record["owner"]
    return LEGACY_OWNER or None


def is_owner(resource_id: str | None, user_id: str | None) -> bool:
    if not resource_id or not user_id:
        return False
    return owner_of(resource_id) == user_id


def require_owner(request: Request, resource_id: str | None) -> str:
    """The signed-in user's id, or a 404 if the resource is not theirs.

    404 and not 403: a stranger learns nothing about whether the id exists."""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to use this feature.")
    if not is_owner(resource_id, user_id):
        raise HTTPException(status_code=404, detail="Not found")
    return user_id


def all_records() -> list[dict]:
    records = []
    for path in OWNERSHIP_DIR.glob("*.json"):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return records


def records_for(user_id: str) -> list[dict]:
    return [record for record in all_records() if record.get("owner") == user_id]


def mark_purged(resource_id: str) -> None:
    path = _path(resource_id)
    with _registry_lock:
        if not path.exists():
            return
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        record["purged_at"] = time.time()
        record["file_keys"] = []
        _write(path, record)


def remove(resource_id: str) -> None:
    try:
        _path(resource_id).unlink(missing_ok=True)
    except HTTPException:
        pass


def scope_video_id(user_id: str, video_id: str) -> str:
    """Two people uploading 'lecture.mp4' must not share one video id: the id
    keys the transcript, the frames and the vectors."""
    prefix = f"u{re.sub(r'[^0-9a-fA-F]', '', user_id)[:8].lower()}_"
    video_id = _safe(video_id) or "video"
    return video_id if video_id.startswith(prefix) else f"{prefix}{video_id}"
