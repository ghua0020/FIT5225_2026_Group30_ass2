"""
Pacific BioArchive — files-delete Lambda（成员 C）
功能：
  1. POST /files/delete：按 URL 列表删除文件（§4.3 查询⑥），body {urls}
  2. 逐 URL 归一化（去 presigned 查询串）→ GSI 定位 → 删 S3 原图+缩略图 → 删 file_tags 行 → 删 files 行
  3. 逐 URL 返回 deleted/failed/not_found；缺失幂等可重试（DB_SCHEMA_V2 §8）

部署：见 docs/C_QUERY_SETUP_GUIDE.md Step 3（API 方法 POST /files/delete）
环境变量（Lambda 中配置）：
  FILES_TABLE / FILE_TAGS_TABLE    files / file_tags（默认）
  THUMB_INDEX / FULL_INDEX         thumb-index / full-index（默认）
  BUCKET                           S3 桶名（必填）
IAM 要求：s3:DeleteObject/GetObject + dynamodb:DeleteItem/Query（Step 2.2 统一策略）
"""
import json
import os
from urllib.parse import urlparse, urlsplit, urlunsplit

import boto3
from boto3.dynamodb.conditions import Key

FILES_TABLE = os.environ.get("FILES_TABLE", "files")
FILE_TAGS_TABLE = os.environ.get("FILE_TAGS_TABLE", "file_tags")
THUMB_INDEX = os.environ.get("THUMB_INDEX", "thumb-index")
FULL_INDEX = os.environ.get("FULL_INDEX", "full-index")
BUCKET = os.environ.get("BUCKET", "")

_dynamodb = boto3.resource("dynamodb")
_files = _dynamodb.Table(FILES_TABLE)
_file_tags = _dynamodb.Table(FILE_TAGS_TABLE)
_s3 = boto3.client("s3")

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


def _normalise_url(raw):
    """去除 presigned 查询串与 fragment，归一化为稳定 URL，用于 GSI 精确匹配（V2 §3.3）。"""
    p = urlsplit(raw)
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def _resolve_item(raw_url):
    """按 URL 定位 files 记录：先归一化，再经 GSI 找 file_id，最后 get_item 取完整记录。"""
    url = _normalise_url(raw_url)
    file_id = None
    for index, attr in ((FULL_INDEX, "full_url"), (THUMB_INDEX, "thumb_url")):
        resp = _files.query(
            IndexName=index,
            KeyConditionExpression=Key(attr).eq(url),
            Limit=1,
        )
        if resp.get("Items"):
            file_id = resp["Items"][0]["file_id"]
            break
    if not file_id:
        return None
    return _files.get_item(Key={"file_id": file_id}).get("Item")


def _s3_bucket_key(url):
    """从 S3 URL 解析出 (bucket, key)。优先取环境变量 BUCKET；否则从 host 首段推断。"""
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lstrip("/")

    bucket = BUCKET
    if not bucket:
        # https://s3.<region>.amazonaws.com/<bucket>/<key>
        if host.startswith("s3."):
            parts = path.split("/", 1)
            bucket = parts[0]
            return bucket, (parts[1] if len(parts) > 1 else "")
        # https://<bucket>.s3.<region>.amazonaws.com/<key>
        bucket = host.split(".")[0]
    else:
        # path-style 且首段是桶名
        parts = path.split("/", 1)
        if parts and parts[0] == bucket:
            path = parts[1] if len(parts) > 1 else ""
    return bucket, path


def _delete_s3_object(url):
    """删除单个 S3 对象；对象不存在视为成功（幂等，V2 §8 可安全重试）。"""
    if not url:
        return
    try:
        bucket, key = _s3_bucket_key(url)
        if bucket and key:
            _s3.delete_object(Bucket=bucket, Key=key)
    except Exception:
        pass


def lambda_handler(event, context):
    try:
        req = json.loads(event.get("body") or "{}")
    except ValueError:
        return _json(400, {"error": "body must be valid JSON"})

    urls = req.get("urls") or []
    if not isinstance(urls, list) or not urls:
        return _json(400, {"error": "field 'urls' must be a non-empty array"})

    requested = [u.strip() for u in urls if isinstance(u, str) and u.strip()]
    if not requested:
        return _json(400, {"error": "field 'urls' must be a non-empty array"})

    deleted, failed, not_found = [], [], []
    seen = set()

    for raw in requested:
        item = _resolve_item(raw)
        if not item:
            not_found.append(raw)
            continue

        fid = item["file_id"]
        if fid in seen:
            continue  # 同一请求内的重复 URL 只处理一次
        seen.add(fid)

        try:
            _delete_s3_object(item.get("full_url", ""))
            _delete_s3_object(item.get("thumb_url", ""))
            _files.delete_item(Key={"file_id": fid})
            for tag in (item.get("tags", []) or []):
                _file_tags.delete_item(Key={"tag": tag, "file_id": fid})
            deleted.append(
                {"url": raw, "file_id": fid, "full_url": item.get("full_url", "")}
            )
        except Exception as e:
            failed.append({"url": raw, "error": str(e)[:300]})

    return _json(
        200,
        {
            "deleted": deleted,
            "failed": failed,
            "not_found": not_found,
            "count": len(deleted),
        },
    )