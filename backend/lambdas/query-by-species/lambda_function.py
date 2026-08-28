"""
Pacific BioArchive — query-by-species Lambda（成员 C）
功能：
  1. GET /search/by-species?species=X：返回至少含 1 个该物种的图片（缩略图 URL）与视频（完整 URL）（§4.3 查询②）
  2. 直接 Query(file_tags, PK=species) 聚合，分页取全（DB_SCHEMA_V2 §6.3）

部署：见 docs/C_QUERY_SETUP_GUIDE.md Step 3（API 方法 GET /search/by-species）
环境变量（Lambda 中配置）：
  FILE_TAGS_TABLE    file_tags（默认）
IAM 要求：dynamodb:Query/Scan 于 file_tags（Step 2.2 统一策略）
"""
import json
import os

import boto3
from boto3.dynamodb.conditions import Key

TABLE = os.environ.get("FILE_TAGS_TABLE", "file_tags")

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


def lambda_handler(event, context):
    params = event.get("queryStringParameters") or {}
    species = (params.get("species") or "").strip()
    if not species:
        return _json(400, {"error": "missing required query parameter 'species'"})

    thumbnails, videos = [], []
    for item in _query_species(species):
        if item.get("file_type") == "video":
            videos.append(item.get("full_url", ""))
        else:
            thumbnails.append(item.get("thumb_url", ""))

    return _json(
        200,
        {"species": species, "count": len(thumbnails) + len(videos),
         "thumbnails": thumbnails, "videos": videos},
    )