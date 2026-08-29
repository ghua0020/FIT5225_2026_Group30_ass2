"""List processed media records for the authenticated Gallery.

API Gateway route:
  GET /files?limit=100&cursor=<opaque cursor>

Environment variables:
  FILES_TABLE                  DynamoDB files table (default: files)
  MEDIA_BUCKET                 Private S3 media bucket (required)
  PRESIGNED_URL_TTL_SECONDS    Download URL lifetime (default: 900)

IAM requirements:
  dynamodb:Scan on the files table
  s3:GetObject on objects in MEDIA_BUCKET
"""

from __future__ import annotations

import base64
from decimal import Decimal
import json
import logging
import os
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

import boto3


FILES_TABLE = os.environ.get("FILES_TABLE", "files")
MEDIA_BUCKET = os.environ.get("MEDIA_BUCKET", "")
PRESIGNED_URL_TTL_SECONDS = int(
    os.environ.get("PRESIGNED_URL_TTL_SECONDS", "900")
)
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 100

_s3 = boto3.client("s3")
_dynamodb = boto3.resource("dynamodb")
_table = _dynamodb.Table(FILES_TABLE)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

CORS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": (
        "Content-Type,Authorization,X-Amz-Date,X-Api-Key,X-Amz-Security-Token"
    ),
    "Access-Control-Allow-Methods": "GET,OPTIONS",
}


def _normalise(value: Any) -> Any:
    """Convert DynamoDB Decimal values into JSON-compatible Python values."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {key: _normalise(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalise(item) for item in value]
    return value


def _json(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": CORS,
        "body": json.dumps(_normalise(body), ensure_ascii=False),
    }


def _parse_media_url(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    if parsed.scheme == "s3":
        bucket = parsed.netloc
    elif parsed.scheme in {"http", "https"}:
        host = parsed.hostname or ""
        if ".s3." in host:
            bucket = host.split(".s3.", 1)[0]
        elif host.endswith(".s3.amazonaws.com"):
            bucket = host[: -len(".s3.amazonaws.com")]
        else:
            raise ValueError("media URL is not an S3 object URL")
    else:
        raise ValueError("media URL has an unsupported scheme")

    key = unquote(parsed.path.lstrip("/"))
    if not MEDIA_BUCKET:
        raise RuntimeError("MEDIA_BUCKET is not configured")
    if bucket != MEDIA_BUCKET:
        raise ValueError("media URL points outside the configured bucket")
    if not key:
        raise ValueError("media URL is missing its object key")
    return bucket, key


def _presign(url: str) -> str:
    if not url:
        return ""
    bucket, key = _parse_media_url(url)
    return _s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=PRESIGNED_URL_TTL_SECONDS,
    )


def _encode_cursor(last_key: dict | None) -> str | None:
    if not last_key:
        return None
    payload = json.dumps(_normalise(last_key), separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> dict:
    try:
        padding = "=" * (-len(cursor) % 4)
        decoded = base64.b64decode(
            cursor + padding,
            altchars=b"-_",
            validate=True,
        )
        value = json.loads(decoded)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("cursor is invalid") from exc
    if not isinstance(value, dict) or not value:
        raise ValueError("cursor is invalid")
    return value


def _page_size(raw_value: str | None) -> int:
    if not raw_value:
        return DEFAULT_PAGE_SIZE
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer") from exc
    if value < 1 or value > MAX_PAGE_SIZE:
        raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
    return value


def _gallery_item(raw_item: dict) -> dict:
    item = _normalise(raw_item)
    full_url = str(item.get("full_url", ""))
    thumb_url = str(item.get("thumb_url", ""))
    if not full_url:
        raise ValueError("file record is missing full_url")
    _, full_key = _parse_media_url(full_url)
    return {
        "file_id": str(item.get("file_id", "")),
        "checksum": str(item.get("checksum", "")),
        "file_type": str(item.get("file_type", "image")),
        "file_name": PurePosixPath(full_key).name,
        "tags": item.get("tags", []),
        "tag_counts": item.get("tag_counts", {}),
        "full_url": _presign(full_url),
        "thumb_url": _presign(thumb_url),
        # Preserve the exact values stored in DynamoDB for management and
        # integration testing. These are object identifiers, not public URLs.
        "full_url_source": full_url,
        "thumb_url_source": thumb_url,
        "created_at": item.get("created_at", 0),
    }


def lambda_handler(event: dict, context: Any) -> dict:
    params = event.get("queryStringParameters") or {}
    try:
        limit = _page_size(params.get("limit"))
        cursor = (params.get("cursor") or "").strip()
        scan_kwargs: dict[str, Any] = {"Limit": limit}
        if cursor:
            scan_kwargs["ExclusiveStartKey"] = _decode_cursor(cursor)
    except ValueError as exc:
        return _json(400, {"error": str(exc)})

    try:
        response = _table.scan(**scan_kwargs)
        items = [_gallery_item(item) for item in response.get("Items", [])]
        return _json(
            200,
            {
                "items": items,
                "next_cursor": _encode_cursor(response.get("LastEvaluatedKey")),
            },
        )
    except Exception:
        logger.exception("Failed to list Gallery media")
        return _json(500, {"error": "failed to list processed media"})
