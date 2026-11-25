"""Consent ledger for the one transfer that has no legal safeguard.

Text from a user's files and the questions they ask are sent to DeepSeek, which
stores them in China. That transfer has no adequacy decision and no contractual
safeguards, so the only lawful basis is the user's explicit consent (GDPR
Art. 49(1)(a)). Consent is an append-only ledger in Supabase (`user_consents`);
the newest row per kind wins, and a consent given to an older policy version
does not count. Ownership of documents and videos is not handled here: it lives
in the per-account storage directory (services/user_scope.py) and in the
`owner_id` of each document.
"""

import os
import threading
import time

import requests


# Bump this when the privacy policy changes what the user agreed to: everyone is
# asked again on their next visit.
CONSENT_VERSION = os.getenv("CONSENT_VERSION", "2026-11-25")
CONSENT_KINDS = ("china_transfer", "marketing")


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
