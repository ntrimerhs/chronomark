"""Allow the browser to read PDFs straight from R2.

The document viewer renders the uploaded PDF with pdf.js, which fetches the file
from a presigned R2 URL. That fetch is cross-origin (the site is on
chronomark.0digital.xyz, the file on r2.cloudflarestorage.com), so without a
bucket CORS policy the browser blocks it and the viewer shows "Could not load
this PDF". R2 has no dashboard setting for this: it is an S3 API call.

Run once, from inside the backend container (it has boto3 and the R2 env):

    docker compose exec backend python /app/scripts/set_r2_cors.py
"""

import json
import os
import sys

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

load_dotenv()

ORIGINS = [
    origin.strip()
    for origin in (
        os.getenv("R2_ALLOWED_ORIGINS")
        or "https://chronomark.0digital.xyz,http://localhost:5173,http://localhost:8080"
    ).split(",")
    if origin.strip()
]

POLICY = {
    "CORSRules": [
        {
            "AllowedOrigins": ORIGINS,
            "AllowedMethods": ["GET", "HEAD"],
            "AllowedHeaders": ["*"],
            # The viewer needs the length to plan page rendering, and range
            # support so pdf.js can fetch one page at a time.
            "ExposeHeaders": [
                "Content-Type",
                "Content-Length",
                "Content-Range",
                "Accept-Ranges",
                "ETag",
                "Last-Modified",
            ],
            "MaxAgeSeconds": 3600,
        }
    ]
}


def main() -> int:
    endpoint = (os.getenv("R2_ENDPOINT_URL") or "").strip()
    bucket = (os.getenv("R2_BUCKET_NAME") or "").strip()
    key = (os.getenv("R2_ACCESS_KEY_ID") or "").strip()
    secret = (os.getenv("R2_SECRET_ACCESS_KEY") or "").strip()

    missing = [
        name
        for name, value in (
            ("R2_ENDPOINT_URL", endpoint),
            ("R2_BUCKET_NAME", bucket),
            ("R2_ACCESS_KEY_ID", key),
            ("R2_SECRET_ACCESS_KEY", secret),
        )
        if not value
    ]
    if missing:
        print(f"[CORS] missing environment: {', '.join(missing)}")
        return 1

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=key,
        aws_secret_access_key=secret,
        region_name="auto",
    )

    try:
        client.put_bucket_cors(Bucket=bucket, CORSConfiguration=POLICY)
        current = client.get_bucket_cors(Bucket=bucket)
    except (BotoCoreError, ClientError) as error:
        print(f"[CORS] failed: {error}")
        return 1

    print(f"[CORS] bucket '{bucket}' now allows {', '.join(ORIGINS)}")
    print(json.dumps(current.get("CORSRules", []), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
