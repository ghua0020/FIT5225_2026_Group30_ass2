"""
Pacific BioArchive — query-by-file Lambda（成员 C）
功能：
  1. POST /search/by-file：上传图片检测物种后，返回含该标签集（AND）的全部文件 URL（§4.3 查询④）
  2. 临时同步 Invoke B 的检测函数得 tags → 逐 tag 求 file_id 交集；文件只在内存处理，
     绝不写 S3/DB（满足"查询用文件不入库、不永久存储"）

部署：见 docs/C_QUERY_SETUP_GUIDE.md Step 3（API 方法 POST /search/by-file）
环境变量（Lambda 中配置）：
  DETECT_FUNCTION    B 的检测 Lambda 名称或 ARN（必填，B 落地后配置）
  FILE_TAGS_TABLE    file_tags（默认）
IAM 要求：lambda:InvokeFunction（B 检测函数）+ dynamodb:Query（Step 2.2 统一策略）
"""
import json
import os

import boto3
from boto3.dynamodb.conditions import Key

DETECT_FUNCTION = os.environ.get("DETECT_FUNCTION", "")
TABLE = os.environ.get("FILE_TAGS_TABLE", "file_tags")

_lambda = boto3.client("lambda")
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


def _detect(base64_str):
    """同步调用 B 的检测函数，返回 [{"name": "koala", "count": 2}, ...]"""
    if not DETECT_FUNCTION:
        raise RuntimeError("DETECT_FUNCTION is not configured in Lambda env vars")
    resp = _lambda.invoke(
        FunctionName=DETECT_FUNCTION,
        InvocationType="RequestResponse",
        Payload=json.dumps({"base64": base64_str}),
    )
    payload = json.loads(resp["Payload"].read())
    # B 的函数按 Lambda Proxy 格式返回：{"statusCode":200,"body":"..."}
    if resp.get("StatusCode") != 200 or payload.get("statusCode", 500) != 200:
        raise RuntimeError(
            "detection failed: " + str(payload).replace("\\n", " ")[:500]
        )
    body = payload.get("body", "[]")
    if isinstance(body, str):
        body = json.loads(body)
    return body.get("tags", []) if isinstance(body, dict) else []


def _query_tag(tag):
    """{file_id: {'file_type','full_url','thumb_url'}}，分页取全。"""
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
            }
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
    return out


def lambda_handler(event, context):
    try:
        req = json.loads(event.get("body") or "{}")
    except ValueError:
        return _json(400, {"error": "body must be valid JSON"})

    base64_str = (req.get("base64") or "").strip() if isinstance(req, dict) else ""
    if not base64_str:
        return _json(400, {"error": 'body must be {"base64": "<image bytes>"}'})

    # 1. 临时检测（不落库）
    try:
        detected = _detect(base64_str)
    except Exception as e:
        return _json(502, {"error": "detection failed", "detail": str(e)[:500]})

    tags = [tag.get("name") for tag in detected if tag.get("name")]
    tags = list(dict.fromkeys(tags))
    if not tags:
        return _json(200, {"detected": [], "count": 0,
                           "thumbnails": [], "videos": []})

    # 2. 按检测出的标签求交集（文件须包含该标签集）
    info_by_tag = {tag: _query_tag(tag) for tag in tags}
    matched = set(info_by_tag[tags[0]].keys())
    for tag in tags[1:]:
        matched &= set(info_by_tag[tag].keys())
        if not matched:
            break

    # 3. 汇总结果（查询文件本身不入库、不留存）
    thumbnails, videos = [], []
    for fid in sorted(matched):
        info = info_by_tag[tags[0]][fid]
        if info["file_type"] == "video":
            videos.append(info["full_url"])
        else:
            thumbnails.append(info["thumb_url"])

    return _json(
        200,
        {"detected": tags, "count": len(matched),
         "thumbnails": thumbnails, "videos": videos},
    )