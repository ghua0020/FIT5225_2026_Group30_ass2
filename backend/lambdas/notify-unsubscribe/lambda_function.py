"""
Pacific BioArchive — notify-unsubscribe Lambda（成员 C）
功能：
  1. POST /notify/unsubscribe：按标签退订（§4.4），body {tags}
  2. 删 subscriptions 行（未订阅的标签忽略）；全退光则 sns.unsubscribe 该 email 订阅；
     否则仅更新 FilterPolicy 为剩余标签

部署：见 docs/C_QUERY_SETUP_GUIDE.md Step 3 + Step 4（SNS）
环境变量（Lambda 中配置）：
  SUBSCRIPTIONS_TABLE    subscriptions（默认）
  NOTIFY_TOPIC_ARN       pba-tag-events 主题 ARN（必填）
IAM 要求：dynamodb:DeleteItem/Query/Scan + sns:Unsubscribe/List/SetSubscriptionAttributes（Step 2.2）
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


def _claims(event):
    claims = (event.get("requestContext") or {}).get("authorizer", {}).get("claims", {})
    return claims.get("sub", ""), claims.get("email", "")


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


def _sns_subscriptions(email):
    matches = []
    token = None
    while True:
        kwargs = {"TopicArn": TOPIC_ARN}
        if token:
            kwargs["NextToken"] = token
        resp = _sns.list_subscriptions_by_topic(**kwargs)
        for sub in resp.get("Subscriptions", []):
            if sub.get("Protocol") == "email" and sub.get("Endpoint") == email:
                matches.append(sub)
        token = resp.get("NextToken")
        if not token:
            break
    return matches


def _apply_filter_policy(arn, tag_list):
    _sns.set_subscription_attributes(
        SubscriptionArn=arn,
        AttributeName="FilterPolicy",
        AttributeValue=json.dumps({"tags": tag_list}),
    )


def _sync_email_filter(email):
    """按邮箱汇总标签；无标签则移除已确认订阅，否则同步 FilterPolicy。"""
    tags = _email_subscribed_tags(email)
    for sub in _sns_subscriptions(email):
        arn = sub.get("SubscriptionArn", "")
        if not arn.startswith("arn:aws:sns:"):
            continue
        if tags:
            _apply_filter_policy(arn, tags)
        else:
            _sns.unsubscribe(SubscriptionArn=arn)
    return tags


def lambda_handler(event, context):
    user_sub, email = _claims(event)
    if not user_sub or not email:
        return _json(401, {"error": "cannot read Cognito identity (sub/email)"})

    try:
        req = json.loads(event.get("body") or "{}")
    except ValueError:
        return _json(400, {"error": "body must be valid JSON"})

    remove_tags = {str(t).strip() for t in (req.get("tags") or []) if str(t).strip()}
    if not remove_tags:
        return _json(400, {"error": "field 'tags' must be a non-empty array"})

    # 只删真正订阅过的标签（未订阅的忽略，V2 §9）
    subscribed = set(_subscribed_tags(user_sub))
    removed = []
    for tag in remove_tags:
        if tag not in subscribed:
            continue
        try:
            _table.delete_item(Key={"user_sub": user_sub, "tag": tag})
            removed.append(tag)
        except Exception:
            pass  # 单行删除失败不影响其余

    remaining = sorted(subscribed - set(removed))

    if TOPIC_ARN:
        _sync_email_filter(email)

    return _json(200, {"removed": sorted(removed), "remaining": remaining})
