"""
Pacific BioArchive — query-by-species Lambda（成员 C）
功能：
  1. GET /search/by-species?species=X：返回至少含 1 个该物种的图片（缩略图 URL）与视频（完整 URL）（§4.3 查询②）
  2. 直接 Query(file_tags, PK=species) 聚合，分页取全（DB_SCHEMA_V2 §6.3）

部署：见 docs/C_QUERY_SETUP_GUIDE.md Step 3（API 方法 GET /search/by-species）
环境变量（Lambda 中配置）：
  FILE_TAGS_TABLE    file_tags（默认）
  MEDIA_BUCKET       私有媒体桶名（用于生成临时 GET URL）
IAM 要求：dynamodb:Query 于 file_tags + s3:GetObject 于媒体桶
"""
import json
import os
from urllib.parse import unquote, urlsplit

import boto3
from boto3.dynamodb.conditions import Key

TABLE = os.environ.get("FILE_TAGS_TABLE", "file_tags")
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


def _query_species(species):
    items = []
    last_key = None
    while True:
        kwargs = {"KeyConditionExpression": Key("tag").eq(species)}
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key
        resp = _table.query(**kwargs)
        items.extend(resp.get("Items", []))
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
    return items


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
    if bucket != MEDIA_BUCKET:
        raise ValueError("media URL points outside the configured bucket")
    if not key:
        raise ValueError("media URL is missing an object key")
    return bucket, key


def _presign_media_url(url):
    if not url:
        return ""
    bucket, key = _parse_media_url(url)
    return _s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=PRESIGNED_URL_TTL_SECONDS,
    )


def lambda_handler(event, context):
    params = event.get("queryStringParameters") or {}
    species = (params.get("species") or "").strip()
    if not species:
        return _json(400, {"error": "missing required query parameter 'species'"})

    thumbnails, thumbnail_sources, full_images, videos = [], [], [], []
    try:
        for item in _query_species(species):
            if item.get("file_type") == "video":
                videos.append(_presign_media_url(item.get("full_url", "")))
            else:
                stable_thumb_url = item.get("thumb_url", "")
                thumbnail_sources.append(stable_thumb_url)
                thumbnails.append(_presign_media_url(stable_thumb_url))
                full_images.append(_presign_media_url(item.get("full_url", "")))
    except (RuntimeError, ValueError) as exc:
        return _json(
            500,
            {"error": "media URL configuration failed", "detail": str(exc)},
        )

    return _json(
        200,
        {"species": species, "count": len(thumbnails) + len(videos),
         "thumbnails": thumbnails, "thumbnail_sources": thumbnail_sources,
         "full_images": full_images, "videos": videos},
    )
