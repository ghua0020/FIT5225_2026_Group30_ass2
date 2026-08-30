"""
Pacific BioArchive — notify-subscribe Lambda（成员 C）
功能：
  1. POST /notify/subscribe：按标签订阅通知（§4.4），body {tags}
  2. upsert subscriptions 行；保证该用户邮箱在 pba-tag-events 上存在 email 订阅
     （无则创建，SNS 自动发确认邮件）；FilterPolicy 更新为用户全部订阅标签（免 SES/consumer）

部署：见 docs/C_QUERY_SETUP_GUIDE.md Step 3 + Step 4（SNS）
环境变量（Lambda 中配置）：
  SUBSCRIPTIONS_TABLE    subscriptions（默认）
  NOTIFY_TOPIC_ARN       pba-tag-events 主题 ARN（必填）
IAM 要求：dynamodb:Query/Scan/Put + sns:Subscribe/List/SetSubscriptionAttributes（Step 2.2 统一策略）
"""
import json
import os
import time

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
    """汇总同一邮箱下全部 Cognito identity 的标签，避免账号之间覆盖 SNS policy。"""
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
    """返回邮箱在 topic 上的全部订阅；包含 pending 项以避免重复创建。"""
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
    """将数据库中该邮箱的标签并集同步到所有已确认 SNS email subscriptions。"""
    tags = _email_subscribed_tags(email)
    for sub in _sns_subscriptions(email):
        arn = sub.get("SubscriptionArn", "")
        if arn.startswith("arn:aws:sns:"):
            _apply_filter_policy(arn, tags)
    return tags


def lambda_handler(event, context):
    user_sub, email = _claims(event)
    if not user_sub or not email:
        return _json(401, {"error": "cannot read Cognito identity (sub/email)"})
    if not TOPIC_ARN:
        return _json(500, {"error": "NOTIFY_TOPIC_ARN not configured"})

    try:
        req = json.loads(event.get("body") or "{}")
    except ValueError:
        return _json(400, {"error": "body must be valid JSON"})

    new_tags = [str(t).strip() for t in (req.get("tags") or []) if str(t).strip()]
    if not new_tags:
        return _json(400, {"error": "field 'tags' must be a non-empty array"})

    # 1. upsert subscriptions 行
    now = int(time.time() * 1000)
    for tag in new_tags:
        _table.put_item(
            Item={"user_sub": user_sub, "tag": tag, "email": email, "created_at": now}
        )

    # 2. 保证 email 订阅存在
    subscriptions = _sns_subscriptions(email)
    created = False
    if not subscriptions:
        _sns.subscribe(TopicArn=TOPIC_ARN, Protocol="email", Endpoint=email)
        created = True

    # 3. 已确认时立即同步；首次仍 pending 时，notify-list 会在用户确认后自动补设。
    all_tags = _subscribed_tags(user_sub)
    email_tags = _sync_email_filter(email)

    return _json(
        200,
        {
            "email": email,
            "tags": all_tags,
            "email_tags": email_tags,
            "subscription_created": created,
            "message": (
                "Subscription updated. If a confirmation email was sent, "
                "click the link to activate it."
            ),
        },
    )
