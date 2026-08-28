"""
Pacific BioArchive — query-thumbnail Lambda（成员 C）
功能：
  1. GET /search/thumbnail?url=<缩略图URL>：缩略图 URL 反查原文件（全尺寸）URL（§4.3 查询③）
  2. 经 files 表 GSI thumb-index 按 thumb_url 精确查询；未命中返回 404

部署：见 docs/C_QUERY_SETUP_GUIDE.md Step 3（API 方法 GET /search/thumbnail）
环境变量（Lambda 中配置）：
  FILES_TABLE    files（默认）
  THUMB_INDEX    thumb-index（默认）
IAM 要求：dynamodb:Query 于 files 的 GSI thumb-index（Step 2.2 统一策略）
"""
import json
import os

import boto3
from boto3.dynamodb.conditions import Key

TABLE = os.environ.get("FILES_TABLE", "files")
THUMB_INDEX = os.environ.get("THUMB_INDEX", "thumb-index")

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


def lambda_handler(event, context):
    params = event.get("queryStringParameters") or {}
    thumb_url = (params.get("url") or "").strip()
    if not thumb_url:
        return _json(400, {"error": "missing required query parameter 'url'"})

    resp = _table.query(
        IndexName=THUMB_INDEX,
        KeyConditionExpression=Key("thumb_url").eq(thumb_url),
        Limit=1,
    )
    items = resp.get("Items", [])
    if not items:
        return _json(404, {"error": "no file found for this thumbnail URL"})

    item = items[0]
    return _json(
        200,
        {
            "file_id": item["file_id"],
            "full_url": item.get("full_url", ""),
            "thumb_url": item.get("thumb_url", ""),
        },
    )