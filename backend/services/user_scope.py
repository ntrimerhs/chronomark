"""The per-account directory inside the R2 bucket.

Nothing in the bucket is shared any more. Every object an account uploads lands
under ``documents/<dir>/...`` or ``videos/<dir>/...``, and ``<dir>`` is derived
from the user id -- so two accounts never write into the same folder, and the
API can answer "is this key yours?" without keeping a table of owners.

The directory is an HMAC of the user id, not the id itself. The id is the one
value an attacker already holds (it is in their own token), so it must not be
the thing that protects the folder; and a bare UUID in a key would tell anyone
who sees a URL exactly who owns the file. The HMAC is keyed by a server-side
secret, stable per account, and leaks neither.

``R2_SCOPE_SECRET`` lives in backend/.env beside the R2 keys. Rotating it
orphans every object uploaded before the rotation: old keys stop validating and
the old directories are never written to again. It is a break-glass action, not
routine maintenance.
"""

import hashlib
import hmac
import os

from dotenv import load_dotenv

# The salt keeps this digest from being usable anywhere the same secret is used
# for something else (a JWT signature, for instance).
_SALT = b"chronomark-r2-scope-v1"

# 24 hex chars = 96 bits: long enough that the directory cannot be guessed or
# enumerated, short enough to keep object keys readable in a log line.
SCOPE_LENGTH = 24

# What a scope directory may be written into.
KINDS = ("documents", "videos")


def _secret() -> str:
    """Read the secret on use, not at import.

    The API and the worker import this module before dotenv has necessarily run
    in their process, and a frozen empty secret would silently put every account
    in one directory. Reading it lazily also keeps the failure at the moment an
    upload happens, where the error can be returned to whoever caused it.
    """
    load_dotenv()
    value = (os.getenv("R2_SCOPE_SECRET") or "").strip()
    if not value:
        value = (os.getenv("SUPABASE_SECRET_KEY") or "").strip()
    return value


def scope_of(user_id: str) -> str:
    """The random-looking directory name that belongs to this account."""
    subject = str(user_id or "").strip()
    if not subject:
        raise ValueError("a user id is required to scope a storage directory")
    secret = _secret()
    if not secret:
        raise RuntimeError(
            "R2_SCOPE_SECRET is not set: every upload would land in one shared "
            "directory. Add it to backend/.env before accepting uploads."
        )
    digest = hmac.new(
        secret.encode("utf-8"), _SALT + subject.encode("utf-8"), hashlib.sha256
    )
    return digest.hexdigest()[:SCOPE_LENGTH]


def directory(kind: str, user_id: str) -> str:
    """The prefix every key of this account shares: ``documents/<dir>/``."""
    if kind not in KINDS:
        raise ValueError(f"unknown storage kind: {kind}")
    return f"{kind}/{scope_of(user_id)}/"


def owns(kind: str, user_id: str, file_key: str) -> bool:
    """True when this key lives in this account's directory.

    Keys written before per-user directories existed carry no directory at all,
    so they are never owned by anyone -- the migration script moves them into
    an account's directory first.
    """
    try:
        prefix = directory(kind, user_id)
    except (ValueError, RuntimeError):
        return False
    return str(file_key or "").strip().startswith(prefix)
