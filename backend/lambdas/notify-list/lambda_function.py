"""
Pacific BioArchive — notify-list Lambda（成员 C）
功能：
  1. GET /notify/subscriptions：返回当前用户已订阅的标签列表（§4.4）
  2. 按 user_sub 查 subscriptions 表，分页取全后返回 tags 列表

部署：见 docs/C_QUERY_SETUP_GUIDE.md Step 3（API 方法 GET /notify/subscriptions）
环境变量（Lambda 中配置）：
  SUBSCRIPTIONS_TABLE    subscriptions（默认）
IAM 要求：dynamodb:Query 于 subscriptions（Step 2.2 统一策略）
"""
import json
import os

import boto3

TABLE = os.environ.get("SUBSCRIPTIONS_TABLE", "subscriptions")

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


def _subscribed_tags(user_sub):
    items = []
    last_key = None
    while True:
        kwargs = {
            "KeyConditionExpression": (
                boto3.dynamodb.conditions.Key("user_sub").eq(user_sub)
            )
        }
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key
        resp = _table.query(**kwargs)
        items.extend(resp.get("Items", []))
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
    return sorted({it["tag"] for it in items})


def lambda_handler(event, context):
    claims = (event.get("requestContext") or {}).get("authorizer", {}).get("claims", {})
    user_sub = claims.get("sub", "")
    if not user_sub:
        return _json(401, {"error": "cannot read Cognito identity (sub)"})

    tags = _subscribed_tags(user_sub)
    return _json(200, {"email": claims.get("email", ""),
                       "tags": tags, "count": len(tags)})