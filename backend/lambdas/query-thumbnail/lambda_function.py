"""
Pacific BioArchive — query-thumbnail Lambda（成员 C）
功能：
  1. GET /search/thumbnail?url=<缩略图URL>：缩略图 URL 反查原文件（全尺寸）URL（§4.3 查询③）
  2. 经 files 表 GSI thumb-index 按 thumb_url 精确查询；未命中返回 404

部署：见 docs/C_QUERY_SETUP_GUIDE.md Step 3（API 方法 GET /search/thumbnail）
环境变量（Lambda 中配置）：
  FILES_TABLE    files（默认）
  THUMB_INDEX    thumb-index（默认）
  MEDIA_BUCKET   私有媒体桶名（必填，用于生成临时 GET URL）
IAM 要求：dynamodb:Query 于 files 的 GSI thumb-index + s3:GetObject
"""
import json
import os
from urllib.parse import quote, unquote, urlsplit

import boto3
from boto3.dynamodb.conditions import Key

TABLE = os.environ.get("FILES_TABLE", "files")
THUMB_INDEX = os.environ.get("THUMB_INDEX", "thumb-index")
MEDIA_BUCKET = os.environ.get("MEDIA_BUCKET", "")
PRESIGNED_URL_TTL_SECONDS = int(os.environ.get("PRESIGNED_URL_TTL_SECONDS", "900"))

_s3 = boto3.client("s3")
_dynamodb = boto3.resource("dynamodb")
_table = _dynamodb.Table(TABLE)

CORS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": (
        "Content-Type,Authorization,X-Amz-Date,X-Api-Key,X-Amz-Security-Token"
    ),
    "Access-Control-Allow-Methods": "GET,PUT,POST,DELETE,OPTIONS",
}


def _json(status, body):
    return {
        "statusCode": status,
        "headers": CORS,
        "body": json.dumps(body, ensure_ascii=False),
    }


def _parse_media_url(url):
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
    if bucket != MEDIA_BUCKET or not key:
        raise ValueError("media URL points outside the configured bucket")
    return bucket, key


def _stable_media_url(url):
    bucket, key = _parse_media_url(url)
    region = os.environ.get("AWS_REGION", "us-east-1")
    return f"https://{bucket}.s3.{region}.amazonaws.com/{quote(key, safe='/')}"


def _presign_media_url(url):
    bucket, key = _parse_media_url(url)
    return _s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=PRESIGNED_URL_TTL_SECONDS,
    )


def lambda_handler(event, context):
    params = event.get("queryStringParameters") or {}
    thumb_url = (params.get("url") or "").strip()
    if not thumb_url:
        return _json(400, {"error": "missing required query parameter 'url'"})

    try:
        stable_thumb_url = _stable_media_url(thumb_url)
        resp = _table.query(
            IndexName=THUMB_INDEX,
            KeyConditionExpression=Key("thumb_url").eq(stable_thumb_url),
            Limit=1,
        )
    except (RuntimeError, ValueError) as exc:
        return _json(400, {"error": str(exc)})
    items = resp.get("Items", [])
    if not items:
        return _json(404, {"error": "no file found for this thumbnail URL"})

    item = items[0]
    try:
        return _json(
            200,
            {
                "file_id": item["file_id"],
                "full_url": _presign_media_url(item.get("full_url", "")),
                "thumb_url": _presign_media_url(item.get("thumb_url", "")),
            },
        )
    except (RuntimeError, ValueError) as exc:
        return _json(500, {"error": "media URL configuration failed", "detail": str(exc)})
