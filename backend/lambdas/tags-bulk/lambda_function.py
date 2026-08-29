"""
Pacific BioArchive — tags-bulk Lambda（成员 C）
功能：
  1. POST /tags/bulk：批量增删标签（§4.3 查询⑤），body {urls, tags, operation:1|0}
  2. operation=1 加（不存在才建 count=1、已存在保留原计数）；operation=0 删（不存在忽略）
  3. files 更新与 file_tags put/delete 走同一 TransactWriteItems（DB_SCHEMA_V2 §7）
  4. 仅"有变更且最终标签非空"时向 SNS 发布事件（V2 §10）；presigned URL 先归一化再查 GSI

部署：见 docs/C_QUERY_SETUP_GUIDE.md Step 3（API 方法 POST /tags/bulk）
环境变量（Lambda 中配置）：
  FILES_TABLE / FILE_TAGS_TABLE    files / file_tags（默认）
  THUMB_INDEX / FULL_INDEX         thumb-index / full-index（默认）
  NOTIFY_TOPIC_ARN                 pba-tag-events 主题 ARN（可选）
  NOTIFY_URL_EXPIRY                临时查看 URL 有效秒数（默认 3600）
IAM 要求：dynamodb:Get/Put/Query/TransactWriteItems + sns:Publish + s3:GetObject
"""
import json
import os
import time
from urllib.parse import unquote, urlsplit, urlunsplit

import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeSerializer

FILES_TABLE = os.environ.get("FILES_TABLE", "files")
FILE_TAGS_TABLE = os.environ.get("FILE_TAGS_TABLE", "file_tags")
THUMB_INDEX = os.environ.get("THUMB_INDEX", "thumb-index")
FULL_INDEX = os.environ.get("FULL_INDEX", "full-index")
TOPIC_ARN = os.environ.get("NOTIFY_TOPIC_ARN", "")
NOTIFY_URL_EXPIRY = int(os.environ.get("NOTIFY_URL_EXPIRY", "3600"))

_dynamodb = boto3.resource("dynamodb")
_dynamodb_client = boto3.client("dynamodb")
_files = _dynamodb.Table(FILES_TABLE)
_file_tags = _dynamodb.Table(FILE_TAGS_TABLE)
_sns = boto3.client("sns")
_s3 = boto3.client("s3")

_serializer = TypeSerializer()


def _to_dyn(item):
    """普通 Python dict → DynamoDB AttributeValue 格式（client.transact_write_items 要求）。
    resource 的 put_item 会自动转换，但 client 需要显式 {"S": ...} / {"N": ...} 包装。"""
    return {k: _serializer.serialize(v) for k, v in item.items()}

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
    """按 URL 定位 files 记录：先归一化，再经 GSI 找 file_id，最后 get_item 取完整记录。
    避免 GSI 仅投影部分属性（KEYS_ONLY）时返回截断记录，导致回写 files 丢字段。"""
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


def _temporary_url(full_url):
    """为私有 S3 原始对象生成邮件中可直接打开的短期 GET URL。"""
    try:
        parsed = urlsplit(full_url)
        if parsed.scheme == "s3":
            bucket = parsed.netloc
        else:
            hostname = parsed.hostname or ""
            marker = hostname.find(".s3")
            bucket = hostname[:marker] if marker > 0 else ""
        key = unquote(parsed.path.lstrip("/"))
        if not bucket or not key:
            return None
        return _s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=NOTIFY_URL_EXPIRY,
        )
    except Exception:
        return None


def _publish_update(file_id, tags, full_url):
    """标签变更后向 SNS 发布事件（带 tags MessageAttributes 供 filter policy 路由）。
    空标签列表不发（V2 §10）。"""
    if not TOPIC_ARN or not tags:
        return
    try:
        message = {
            "file_id": file_id,
            "tags": sorted(tags),
            "full_url": full_url,
            "created_at": int(time.time() * 1000),
        }
        temporary_url = _temporary_url(full_url)
        if temporary_url:
            message["temporary_url"] = temporary_url
            message["temporary_url_expires_in"] = NOTIFY_URL_EXPIRY
        _sns.publish(
            TopicArn=TOPIC_ARN,
            Message=json.dumps(message, ensure_ascii=False),
            MessageAttributes={
                "tags": {
                    "DataType": "String.Array",
                    "StringValue": json.dumps(sorted(tags)),
                }
            },
        )
    except Exception:
        pass  # 通知失败不影响主流程


def _apply_operation(item, tag_names, operation):
    """按 V2 §7 就地计算变更，并通过同一个 TransactWriteItems 原子写回 files + file_tags。
    返回 (最终标签列表, 实际变更的标签列表)；无变更时不写任何数据。"""
    file_id = item["file_id"]
    tags = set(item.get("tags", []) or [])
    tag_counts = dict(item.get("tag_counts", {}) or {})
    now = int(time.time() * 1000)
    changed = []
    transact = []

    if operation == 1:  # 添加：已存在则保留原计数
        for tag in tag_names:
            if tag in tags:
                continue
            tags.add(tag)
            tag_counts[tag] = 1
            transact.append(
                {
                    "Put": {
                        "TableName": FILE_TAGS_TABLE,
                        "Item": _to_dyn(
                            {
                                "tag": tag,
                                "file_id": file_id,
                                "count": 1,
                                "file_type": item.get("file_type", "image"),
                                "full_url": item.get("full_url", ""),
                                "thumb_url": item.get("thumb_url", ""),
                                "created_at": now,
                            }
                        ),
                    }
                }
            )
            changed.append(tag)
    else:  # 移除：不存在的标签忽略
        for tag in tag_names:
            if tag not in tags:
                continue
            tags.discard(tag)
            tag_counts.pop(tag, None)
            transact.append(
                {
                    "Delete": {
                        "TableName": FILE_TAGS_TABLE,
                        "Key": _to_dyn({"tag": tag, "file_id": file_id}),
                    }
                }
            )
            changed.append(tag)

    if changed:
        item["tags"] = sorted(tags)
        item["tag_counts"] = tag_counts
        transact.append({"Put": {"TableName": FILES_TABLE, "Item": _to_dyn(item)}})
        _dynamodb_client.transact_write_items(TransactItems=transact)

    return sorted(tags), changed


def lambda_handler(event, context):
    try:
        req = json.loads(event.get("body") or "{}")
    except ValueError:
        return _json(400, {"error": "body must be valid JSON"})

    urls = req.get("urls") or []
    tags = [str(t).strip() for t in (req.get("tags") or []) if str(t).strip()]
    operation = req.get("operation")

    if not isinstance(urls, list) or not urls:
        return _json(400, {"error": "field 'urls' must be a non-empty array"})
    if not tags:
        return _json(400, {"error": "field 'tags' must be a non-empty array"})
    if operation not in (0, 1):
        return _json(400, {"error": "field 'operation' must be 1 (add) or 0 (remove)"})

    # URL -> files 记录（按 file_id 去重）
    items_by_file = {}
    for url in urls:
        if not isinstance(url, str) or not url.strip():
            continue
        item = _resolve_item(url.strip())
        if item:
            items_by_file[item["file_id"]] = item

    if not items_by_file:
        return _json(404, {"error": "none of the provided URLs matched any file"})

    results = []
    for file_id, item in items_by_file.items():
        final_tags, changed = _apply_operation(item, tags, operation)
        results.append(
            {
                "file_id": file_id,
                "full_url": item.get("full_url", ""),
                "tags": final_tags,
                "changed": changed,
            }
        )
        # 仅在确实发生变更且最终标签非空时发通知（新增/更新）
        if changed and final_tags:
            _publish_update(file_id, final_tags, item.get("full_url", ""))

    return _json(200, {"count": len(results), "results": results})
