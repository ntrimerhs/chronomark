"""Supabase access-token verification for the endpoints that cost money.

Why this file exists at all: /uploadfile, /ask, /api/document/ask and the
YouTube import spin up OCR, ASR and embedding calls that are billed per use.
The frontend now sends a signed-out visitor to /register, but a redirect is a
courtesy, not a wall -- anyone can still POST to the API directly. So the same
rule is enforced here, where the real work happens.

Verification is done against the project's JWKS with `cryptography`, which the
image already ships for google-auth. No PyJWT, no new dependency, no rebuild
cost for a library that would do the same two hundred lines less clearly.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import threading
import time

import requests

import compliance
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware

JWKS_URL = os.getenv("SUPABASE_JWKS_URL", "").strip()
JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "").strip()
AUDIENCE = os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated").strip()
ISSUER = os.getenv("SUPABASE_URL", "").strip().rstrip("/") + "/auth/v1"

# The gate is useless if it fails open because a JWKS fetch was slow, and
# worse than useless if it fails closed on every request. One long-lived
# cache, refreshed on a miss (key rotation) and on a staleness timeout.
_JWKS_TTL = 3600
_jwks = {"keys": {}, "fetched": 0.0}
_jwks_lock = threading.Lock()


class AuthError(Exception):
    """A token we cannot accept, with a message short enough to return."""


def _b64url(raw: str) -> bytes:
    pad = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + pad)


def _split(token: str):
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthError("Malformed token.")
    try:
        header = json.loads(_b64url(parts[0]))
        claims = json.loads(_b64url(parts[1]))
        signature = _b64url(parts[2])
    except Exception as exc:  # noqa: BLE001 - any decode failure is the same 401
        raise AuthError("Malformed token.") from exc
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise AuthError("Malformed token.")
    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
    return header, claims, signature, signing_input


def _public_key_from_jwk(jwk: dict):
    kty = jwk.get("kty")
    if kty == "EC" and jwk.get("crv") == "P-256":
        numbers = ec.EllipticCurvePublicNumbers(
            int.from_bytes(_b64url(jwk["x"]), "big"),
            int.from_bytes(_b64url(jwk["y"]), "big"),
            ec.SECP256R1(),
        )
        return numbers.public_key()
    if kty == "RSA":
        numbers = rsa.RSAPublicNumbers(
            int.from_bytes(_b64url(jwk["e"]), "big"),
            int.from_bytes(_b64url(jwk["n"]), "big"),
        )
        return numbers.public_key()
    raise AuthError(f"Unsupported signing key ({kty}).")


def _fetch_jwks(force: bool = False) -> dict:
    if not JWKS_URL:
        raise AuthError("Token verification is not configured.")
    now = time.time()
    with _jwks_lock:
        fresh = now - _jwks["fetched"] < _JWKS_TTL
        if _jwks["keys"] and fresh and not force:
            return _jwks["keys"]
        try:
            response = requests.get(JWKS_URL, timeout=10)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            if _jwks["keys"]:
                # Stale keys beat a locked door: the JWKS endpoint being down
                # is not a user's problem, and rotation is slower than an hour.
                return _jwks["keys"]
            raise AuthError("Could not reach the key set.") from exc
        keys = {}
        for jwk in payload.get("keys", []):
            kid = jwk.get("kid")
            if not kid:
                continue
            try:
                keys[kid] = _public_key_from_jwk(jwk)
            except AuthError:
                continue
        if not keys:
            raise AuthError("No usable signing keys.")
        _jwks.update({"keys": keys, "fetched": now})
        return keys


def _verify_signature(header: dict, signature: bytes, signing_input: bytes) -> None:
    alg = header.get("alg")
    kid = header.get("kid")

    if alg == "HS256":
        if not JWT_SECRET:
            raise AuthError("Unsupported token algorithm.")
        expected = hmac.new(JWT_SECRET.encode(), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, signature):
            raise AuthError("Invalid token signature.")
        return

    keys = _fetch_jwks()
    key = keys.get(kid)
    if key is None:
        key = _fetch_jwks(force=True).get(kid)
    if key is None:
        raise AuthError("Unknown signing key.")

    try:
        if alg == "ES256":
            # JWS ES256 carries the raw r||s pair, not a DER sequence.
            if len(signature) != 64:
                raise AuthError("Invalid token signature.")
            r = int.from_bytes(signature[:32], "big")
            s = int.from_bytes(signature[32:], "big")
            key.verify(encode_dss_signature(r, s), signing_input, ec.ECDSA(hashes.SHA256()))
        elif alg == "RS256":
            key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
        else:
            raise AuthError("Unsupported token algorithm.")
    except InvalidSignature as exc:
        raise AuthError("Invalid token signature.") from exc


def _check_claims(claims: dict) -> None:
    now = int(time.time())
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or exp <= now:
        raise AuthError("Token has expired.")

    aud = claims.get("aud")
    audiences = aud if isinstance(aud, list) else [aud]
    if AUDIENCE not in [a for a in audiences if a]:
        raise AuthError("Token is for another audience.")

    if not claims.get("sub"):
        raise AuthError("Token has no subject.")


def verify_token(token: str) -> dict:
    """Return the claims, or raise AuthError. Never returns None."""
    header, claims, signature, signing_input = _split(token)
    _verify_signature(header, signature, signing_input)
    _check_claims(claims)
    return claims


# Normalised path -> protected. "/api" is stripped first, because Caddy already
# removes one prefix from the public URL while some routes are declared with
# "/api" inside the app: the same door has to be recognised either way.
_PROTECTED = {
    "/uploadfile",
    "/download-youtube",
    "/ask",
    "/get-upload-url",
    "/upload-document",
    "/process-video",
    "/document/ask",
    "/document/ask/stream",
    "/document/quiz",
    "/document/flashcards",
    "/document/notes",
}

# Whole families of routes that are always for a signed-in account: the
# document library and its conversations, the consent ledger and the account
# itself (export, deletion).
_PROTECTED_PREFIXES = (
    "/document/",
    "/documents",
    "/consent",
    "/account",
)

# Everything that sends a user's content to a provider outside the EU. Without
# the user's explicit consent to that transfer (privacy policy, section 5) these
# answer 403 with code=consent_required and the app shows the consent dialog.
_CONSENT_REQUIRED = {
    "/uploadfile",
    "/download-youtube",
    "/ask",
    "/get-upload-url",
    "/upload-document",
    "/process-video",
    "/document/ask",
    "/document/ask/stream",
    "/document/quiz",
    "/document/flashcards",
    "/document/notes",
}

# /document/<doc_id>/... carries the id in the path, so ownership is checked
# here, for every method. The body-borne ids (ask, quiz, ...) are checked in the
# route itself.
_DOC_PATH_RE = re.compile(r"^/document/([A-Za-z0-9._-]+)(?:/|$)")
_NOT_DOC_IDS = {"ask", "quiz", "flashcards", "notes"}

_DEBUG_ENABLED = os.getenv("ENABLE_DEBUG_ENDPOINTS", "").strip() == "1"

# Media elements load these straight into a <video> or an <a download>, where a
# JS-added Authorization header is not an option, so they stay open. They are
# guarded by unguessable keys instead -- and by not costing anything to serve.
_OPEN_PREFIXES = (
    "/api/video-stream",
    "/api/document-stream",
    "/api/document-file",
    "/video-frames",
    "/uploads",
    "/audio",
    "/frames",
    "/health",
)


def _normalise(path: str) -> str:
    path = path.rstrip("/") or "/"
    if path == "/api":
        return "/"
    if path.startswith("/api/"):
        return path[4:]
    return path


def _is_protected(method: str, path: str) -> bool:
    if method == "OPTIONS":
        return False
    if any(path.startswith(prefix) for prefix in _OPEN_PREFIXES):
        return False
    normalised = _normalise(path)
    return normalised in _PROTECTED or any(normalised.startswith(p) for p in _PROTECTED_PREFIXES)


class AuthGateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Diagnostic routes dump transcripts and vector counts for every user.
        if _normalise(request.url.path).startswith("/debug") and not _DEBUG_ENABLED:
            return JSONResponse({"detail": "Not found"}, status_code=404)

        if not _is_protected(request.method, request.url.path):
            return await call_next(request)

        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            return JSONResponse(
                {"detail": "Sign in to use this feature."},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            claims = await run_in_threadpool(verify_token, header[7:].strip())
        except AuthError as exc:
            return JSONResponse(
                {"detail": str(exc)},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        request.state.user = claims
        request.state.user_id = claims.get("sub")
        normalised = _normalise(request.url.path)

        if request.method != "OPTIONS":
            match = _DOC_PATH_RE.match(normalised)
            if match and match.group(1) not in _NOT_DOC_IDS:
                if not compliance.is_owner(match.group(1), request.state.user_id):
                    return JSONResponse({"detail": "Not found"}, status_code=404)

            if normalised in _CONSENT_REQUIRED:
                try:
                    allowed = await run_in_threadpool(
                        compliance.has_transfer_consent, request.state.user_id
                    )
                except compliance.ConsentUnavailable:
                    return JSONResponse(
                        {"detail": "Consent service is unavailable. Try again shortly."},
                        status_code=503,
                    )
                if not allowed:
                    return JSONResponse(
                        {
                            "detail": "Your consent is needed before your files can be processed.",
                            "code": "consent_required",
                        },
                        status_code=403,
                    )

        return await call_next(request)
