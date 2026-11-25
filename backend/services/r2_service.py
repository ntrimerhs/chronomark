"""Cloudflare R2 access via presigned URLs.

The point of this module is that video files never pass through this server:
the browser PUTs the file straight to R2 with a short-lived signed URL, and
playback/analysis reads it back the same way. Only the signed URLs are issued
here -- no bucket traffic flows through this process except the deliberate
fallback download in download_to_file().

Credentials come from backend/.env:
    R2_ENDPOINT_URL      https://<account-id>.r2.cloudflarestorage.com
    R2_ACCESS_KEY_ID     R2 access key (not the Cloudflare email/token)
    R2_SECRET_ACCESS_KEY R2 secret key
    R2_BUCKET_NAME       e.g. chronomark

R2 is S3-compatible but has no regions: region_name must be 'auto', and
signatures must be v4 (S3 presigned v2 is rejected).
"""

import os
import re
import uuid

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

load_dotenv()

R2_ENDPOINT_URL = (os.getenv("R2_ENDPOINT_URL") or "").strip()
R2_ACCESS_KEY_ID = (os.getenv("R2_ACCESS_KEY_ID") or "").strip()
R2_SECRET_ACCESS_KEY = (os.getenv("R2_SECRET_ACCESS_KEY") or "").strip()
R2_BUCKET_NAME = (os.getenv("R2_BUCKET_NAME") or "").strip()

# Every object lives under one of these two roots, and under a directory named
# for its owner (see services/user_scope.py): videos/<dir>/<uuid>-<name>.
UPLOAD_KEY_PREFIX = "videos/"

# Uploaded study documents (PDF / PPTX / DOCX) live beside the videos, in their
# own prefix so the video retention sweeper never deletes a handout.
DOCUMENT_KEY_PREFIX = "documents/"
_ALLOWED_PREFIXES = (UPLOAD_KEY_PREFIX, DOCUMENT_KEY_PREFIX)

# A key is root + optional owner directory + one flat file name. The directory
# is optional only so objects uploaded before scoping existed still validate;
# nothing new is written without one.
_KEY_RE = re.compile(r"^(?:videos|documents)/(?:[a-f0-9]{16,64}/)?[A-Za-z0-9._\-]+$")
_PREFIX_RE = re.compile(r"^(?:videos|documents)/(?:[a-f0-9]{16,64}/)?$")

# Signing-only module: no bucket calls happen here, but the same client also
# serves the fallback download, so the timeout keeps a stuck connection from
# hanging a background job.
_HTTP_TIMEOUT_SECONDS = 60

_client = None


def _get_client():
    """The boto3 S3 client pointed at R2, built once.

    Lazy on purpose: a missing .env variable should produce one clear error at
    the moment an upload is requested, not a crash at import time for every
    backend command.
    """
    global _client
    if _client is not None:
        return _client

    missing = [
        name
        for name, value in (
            ("R2_ENDPOINT_URL", R2_ENDPOINT_URL),
            ("R2_ACCESS_KEY_ID", R2_ACCESS_KEY_ID),
            ("R2_SECRET_ACCESS_KEY", R2_SECRET_ACCESS_KEY),
            ("R2_BUCKET_NAME", R2_BUCKET_NAME),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "R2 is not configured: missing " + ", ".join(missing) + " in backend/.env"
        )

    _client = boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        # R2 has no regions; the S3 signature needs a region string and R2
        # expects the literal 'auto'.
        region_name="auto",
        config=boto3.session.Config(
            signature_version="s3v4",
            read_timeout=_HTTP_TIMEOUT_SECONDS,
            connect_timeout=_HTTP_TIMEOUT_SECONDS,
            retries={"max_attempts": 3},
        ),
    )
    return _client


def sanitize_file_name(file_name: str) -> str:
    """A safe basename for building the object key."""
    base = os.path.basename(str(file_name or "").strip())
    base = re.sub(r"\s+", "_", base)
    base = re.sub(r"[^A-Za-z0-9._\-]", "", base)
    base = base.lstrip(".").strip("._-")
    if len(base) > 120:
        stem, _, ext = base.rpartition(".")
        base = (stem[:110] or "video") + ("." + ext if ext else "")
    return base or "video.mp4"


def validate_file_key(file_key: str) -> str:
    """Accept only keys this module issued, unchanged.

    Shapes: ``videos/<uuid>-<name>`` and ``documents/<uuid>-<name>`` for objects
    from before scoping, and ``videos/<dir>/<uuid>-<name>`` /
    ``documents/<dir>/<uuid>-<name>`` for everything since, where <dir> is the
    owner's directory from services/user_scope.py.
    """
    key = str(file_key or "").strip()
    if not key.startswith(_ALLOWED_PREFIXES):
        raise ValueError("file_key must start with 'videos/' or 'documents/'")
    if ".." in key or not _KEY_RE.fullmatch(key):
        raise ValueError("file_key contains invalid path characters")
    if len(key) > 250:
        raise ValueError("file_key too long")
    return key


def validate_prefix(prefix: str) -> str:
    """A directory new keys are written into: 'videos/' or 'documents/<dir>/'."""
    value = str(prefix or "").strip()
    if not value.endswith("/"):
        value += "/"
    if not _PREFIX_RE.fullmatch(value):
        raise ValueError(f"unsupported key prefix: {prefix}")
    return value


def display_name_for_key(file_key: str) -> str:
    """The original file name stored in a key: <root>/<dir>/<uuid>-<name>."""
    name = str(file_key or "").rsplit("/", 1)[-1]
    return name.split("-", 1)[1] if "-" in name else name


def generate_presigned_upload_url(
    file_name: str,
    content_type: str = "video/mp4",
    expires_in: int = 900,
    prefix: str = UPLOAD_KEY_PREFIX,
):
    """A PUT URL the browser uploads the video to, straight to R2.

    The returned content_type must be sent by the client as its request
    Content-Type exactly -- it is part of the v4 signature, and a mismatch is
    the usual 'SignatureDoesNotMatch' cause.
    """
    content_type = str(content_type or "video/mp4").strip().lower()
    if not (content_type.startswith("video/") or content_type == "application/octet-stream"):
        raise ValueError(f"unsupported content_type: {content_type}")
    if not 1 <= int(expires_in) <= 86400:
        raise ValueError("expires_in must be between 1 and 86400 seconds")

    file_key = f"{validate_prefix(prefix)}{uuid.uuid4().hex}-{sanitize_file_name(file_name)}"

    try:
        upload_url = _get_client().generate_presigned_url(
            "put_object",
            Params={
                "Bucket": R2_BUCKET_NAME,
                "Key": file_key,
                "ContentType": content_type,
            },
            ExpiresIn=int(expires_in),
        )
    except (BotoCoreError, ClientError) as error:
        raise RuntimeError(f"Could not create upload URL: {error}") from error

    return {
        "upload_url": upload_url,
        "file_key": file_key,
        "content_type": content_type,
        "expires_in": int(expires_in),
    }


def generate_presigned_download_url(file_key: str, expires_in: int = 3600) -> str:
    """A short-lived GET URL for playing or fetching the video."""
    key = validate_file_key(file_key)
    if not 1 <= int(expires_in) <= 604800:
        raise ValueError("expires_in must be between 1 and 604800 seconds")

    try:
        return _get_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": R2_BUCKET_NAME, "Key": key},
            ExpiresIn=int(expires_in),
        )
    except (BotoCoreError, ClientError) as error:
        raise RuntimeError(f"Could not create download URL: {error}") from error


def open_object(file_key: str):
    """Open an object for streaming back to a client.

    Returns (body, size) where body is botocore's StreamingBody. Used by the
    document proxy: a presigned URL would be cross-origin for the browser, and
    the R2 token cannot set a bucket CORS policy, so the API relays the bytes
    instead. The caller must close the body.
    """
    key = validate_file_key(file_key)
    try:
        response = _get_client().get_object(Bucket=R2_BUCKET_NAME, Key=key)
    except (BotoCoreError, ClientError) as error:
        raise RuntimeError(f"Could not open '{key}' in R2: {error}") from error
    return response["Body"], int(response.get("ContentLength") or 0)


def bucket_cors_rules():
    """The bucket's CORS policy, or None when it cannot be read.

    Used to decide how a PDF reaches the browser: with a CORS policy that allows
    this site, the viewer can fetch a presigned URL straight from R2 and the VPS
    carries no bytes at all. Without one the file has to be relayed by the API.
    """
    try:
        response = _get_client().get_bucket_cors(Bucket=R2_BUCKET_NAME)
    except (BotoCoreError, ClientError) as error:
        print(f"[R2] CORS policy not readable: {error}")
        return None
    return response.get("CORSRules") or []


def download_to_file(file_key: str, destination) -> str:
    """Fetch the object to a local path.

    Only used as the processing fallback: ffmpeg streams the video straight from
    the presigned URL first, and this exists for the rare container/codec that
    ffmpeg cannot read over HTTP. The caller is responsible for deleting the
    file afterwards.
    """
    key = validate_file_key(file_key)
    destination = str(destination)
    try:
        _get_client().download_file(R2_BUCKET_NAME, key, destination)
    except (BotoCoreError, ClientError) as error:
        raise RuntimeError(f"Could not download '{key}' from R2: {error}") from error
    return destination


DOCUMENT_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/octet-stream",
}


def upload_stream(
    file_obj,
    file_name: str,
    content_type: str = "video/mp4",
    part_size: int = 8 * 1024 * 1024,
    prefix: str = UPLOAD_KEY_PREFIX,
):
    """Upload a stream to R2 with multipart parts, without a local copy.

    Reads the object sequentially in part_size chunks, so a request body that
    only supports forward reads (an in-progress upload) can go straight to R2.
    Never seeks the input. Returns {"file_key", "size"}.
    """
    prefix = validate_prefix(prefix)
    if not 8 * 1024 * 1024 <= int(part_size) <= 1024 * 1024 * 1024:
        # S3 requires every part but the last to be at least 5 MiB; 8 MiB leaves
        # headroom and keeps the in-memory buffer predictable.
        raise ValueError("part_size must be between 8 MiB and 1 GiB")
    content_type = str(content_type or "video/mp4").strip().lower()
    allowed = (
        content_type.startswith("video/")
        or content_type == "application/octet-stream"
        or (prefix.startswith(DOCUMENT_KEY_PREFIX) and content_type in DOCUMENT_CONTENT_TYPES)
    )
    if not allowed:
        raise ValueError(f"unsupported content_type: {content_type}")

    file_key = f"{prefix}{uuid.uuid4().hex}-{sanitize_file_name(file_name)}"
    client = _get_client()
    size = 0

    try:
        multipart = client.create_multipart_upload(
            Bucket=R2_BUCKET_NAME, Key=file_key, ContentType=content_type
        )
        upload_id = multipart["UploadId"]
        parts = []
        try:
            sequence = 0
            while True:
                chunk = file_obj.read(int(part_size))
                if not chunk:
                    break
                size += len(chunk)
                sequence += 1
                part = client.upload_part(
                    Bucket=R2_BUCKET_NAME,
                    Key=file_key,
                    UploadId=upload_id,
                    PartNumber=sequence,
                    Body=chunk,
                )
                parts.append({"PartNumber": sequence, "ETag": part["ETag"]})

            if not parts:
                client.put_object(
                    Bucket=R2_BUCKET_NAME, Key=file_key, Body=b"", ContentType=content_type
                )
            else:
                client.complete_multipart_upload(
                    Bucket=R2_BUCKET_NAME,
                    Key=file_key,
                    UploadId=upload_id,
                    MultipartUpload={"Parts": parts},
                )
        except Exception:
            # Never leave an orphaned multipart upload billing for storage.
            try:
                client.abort_multipart_upload(
                    Bucket=R2_BUCKET_NAME, Key=file_key, UploadId=upload_id
                )
            except (BotoCoreError, ClientError):
                pass
            raise
    except (BotoCoreError, ClientError) as error:
        raise RuntimeError(f"Could not upload to R2: {error}") from error

    return {"file_key": file_key, "size": size}


def delete_object(file_key: str) -> bool:
    """Best-effort delete; failures are logged, not raised. True on success."""
    try:
        key = validate_file_key(file_key)
    except ValueError as error:
        print(f"[R2] delete skipped: {error}")
        return False
    try:
        _get_client().delete_object(Bucket=R2_BUCKET_NAME, Key=key)
    except (BotoCoreError, ClientError) as error:
        print(f"[R2] delete failed for {key}: {error}")
        return False
    return True


def list_upload_keys() -> list:
    """Every object under the upload prefix, with its epoch mtime.

    Used by the retention sweeper to put pre-existing videos on the same
    aging clock as newly uploaded ones.
    """
    entries = []
    paginator = _get_client().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=R2_BUCKET_NAME, Prefix=UPLOAD_KEY_PREFIX):
        for obj in page.get("Contents", []):
            entries.append(
                {"key": obj["Key"], "last_modified": obj["LastModified"].timestamp()}
            )
    return entries
