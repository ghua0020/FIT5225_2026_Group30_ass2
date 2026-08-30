"""
Pacific BioArchive — notify-list Lambda（成员 C）
功能：
  1. GET /notify/subscriptions：返回当前用户已订阅的标签列表（§4.4）
  2. 按 user_sub 查 subscriptions 表，分页取全后返回 tags 列表
  3. 页面加载时按邮箱汇总标签并修复已确认 SNS subscription 的 FilterPolicy

部署：见 docs/C_QUERY_SETUP_GUIDE.md Step 3（API 方法 GET /notify/subscriptions）
环境变量（Lambda 中配置）：
  SUBSCRIPTIONS_TABLE    subscriptions（默认）
  NOTIFY_TOPIC_ARN       pba-tag-events 主题 ARN（可选；配置后自动修复过滤策略）
IAM 要求：dynamodb:Query/Scan + sns:ListSubscriptionsByTopic/SetSubscriptionAttributes/Unsubscribe
"""
import json
import os

import boto3
from boto3.dynamodb.conditions import Attr, Key

TABLE = os.environ.get("SUBSCRIPTIONS_TABLE", "subscriptions")
TOPIC_ARN = os.environ.get("NOTIFY_TOPIC_ARN", "")

_dynamodb = boto3.resource("dynamodb")
_table = _dynamodb.Table(TABLE)
_sns = boto3.client("sns")

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
                Key("user_sub").eq(user_sub)
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


def _email_subscribed_tags(email):
    items = []
    last_key = None
    while True:
        kwargs = {"FilterExpression": Attr("email").eq(email)}
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key
        resp = _table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
    return sorted({it["tag"] for it in items})


def _sns_subscription_arns(email):
    arns = []
    token = None
    while True:
        kwargs = {"TopicArn": TOPIC_ARN}
        if token:
            kwargs["NextToken"] = token
        resp = _sns.list_subscriptions_by_topic(**kwargs)
        for sub in resp.get("Subscriptions", []):
            arn = sub.get("SubscriptionArn", "")
            if (
                sub.get("Protocol") == "email"
                and sub.get("Endpoint") == email
                and arn.startswith("arn:aws:sns:")
            ):
                arns.append(arn)
        token = resp.get("NextToken")
        if not token:
            break
    return arns


def _sync_email_filter(email):
    tags = _email_subscribed_tags(email)
    for arn in _sns_subscription_arns(email):
        if tags:
            _sns.set_subscription_attributes(
                SubscriptionArn=arn,
                AttributeName="FilterPolicy",
                AttributeValue=json.dumps({"tags": tags}),
            )
        else:
            _sns.unsubscribe(SubscriptionArn=arn)
    return tags


def lambda_handler(event, context):
    claims = (event.get("requestContext") or {}).get("authorizer", {}).get("claims", {})
    user_sub = claims.get("sub", "")
    email = claims.get("email", "")
    if not user_sub or not email:
        return _json(401, {"error": "cannot read Cognito identity (sub/email)"})

    tags = _subscribed_tags(user_sub)
    sync_status = "not_configured"
    if TOPIC_ARN:
        try:
            _sync_email_filter(email)
            sync_status = "synced"
        except Exception as exc:
            print(f"failed to sync SNS FilterPolicy for {email}: {exc}")
            sync_status = "failed"
    return _json(
        200,
        {"email": email, "tags": tags, "count": len(tags), "filter_sync": sync_status},
    )
