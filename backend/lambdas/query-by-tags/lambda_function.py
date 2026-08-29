"""
Pacific BioArchive — query-by-tags Lambda（成员 C）
功能：
  1. POST /search/by-tags：按标签+最低计数查询（§4.3 查询①，逻辑 AND），body 形如 {"koala": 3}
  2. 逐 tag Query(file_tags) 并过滤 count>=min，各 tag 的 file_id 求交集；
     图片返回缩略图 URL、视频返回完整 URL（DB_SCHEMA_V2 §6.3）

部署：见 docs/C_QUERY_SETUP_GUIDE.md Step 3（API 方法 POST /search/by-tags）
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


def _query_tag(tag):
    """返回 {file_id: {'file_type', 'full_url', 'thumb_url', 'count'}}，
    带分页，一次取全。"""
    out = {}
    last_key = None
    while True:
        kwargs = {"KeyConditionExpression": Key("tag").eq(tag)}
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key
        resp = _table.query(**kwargs)
        for item in resp.get("Items", []):
            out[item["file_id"]] = {
                "file_type": item.get("file_type", "image"),
                "full_url": item.get("full_url", ""),
                "thumb_url": item.get("thumb_url", ""),
                "count": int(item.get("count", 0)),
            }
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
    return out


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
    try:
        req = json.loads(event.get("body") or "{}")
    except ValueError:
        return _json(400, {"error": "body must be valid JSON"})

    if not isinstance(req, dict) or not req:
        return _json(400, {"error": 'body must be a JSON object like {"koala": 3}'})

    # 规格化每个 tag 的最低计数（语义为 >=1）
    criteria = []
    for raw_tag, raw_min in req.items():
        tag = str(raw_tag).strip()
        if not tag:
            continue
        try:
            min_count = max(1, int(raw_min))
        except (TypeError, ValueError):
            min_count = 1
        criteria.append((tag, min_count))

    if not criteria:
        return _json(400, {"error": "no valid tags provided"})

    # 各 tag 先各自过滤 count>=min
    info_by_tag = {}
    for tag, min_count in criteria:
        info_by_tag[tag] = {
            fid: info
            for fid, info in _query_tag(tag).items()
            if info["count"] >= min_count
        }

    # AND：从第一个 tag 的文件集开始求交集
    base_tag, _ = criteria[0]
    matched = set(info_by_tag[base_tag].keys())
    for tag, _ in criteria[1:]:
        matched &= set(info_by_tag[tag].keys())
        if not matched:
            break

    thumbnails, thumbnail_sources, full_images, videos = [], [], [], []
    try:
        for fid in sorted(matched):
            info = info_by_tag[base_tag][fid]
            if info["file_type"] == "video":
                videos.append(_presign_media_url(info["full_url"]))
            else:
                thumbnail_sources.append(info["thumb_url"])
                thumbnails.append(_presign_media_url(info["thumb_url"]))
                full_images.append(_presign_media_url(info["full_url"]))
    except (RuntimeError, ValueError) as exc:
        return _json(
            500,
            {"error": "media URL configuration failed", "detail": str(exc)},
        )

    return _json(
        200,
        {"count": len(matched), "thumbnails": thumbnails,
         "thumbnail_sources": thumbnail_sources, "full_images": full_images,
         "videos": videos},
    )
