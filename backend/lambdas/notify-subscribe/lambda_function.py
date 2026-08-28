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
IAM 要求：dynamodb:Query/Put + sns:Subscribe/List/SetSubscriptionAttributes（Step 2.2 统一策略）
"""
import json
import os
import time

import boto3

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


def _sns_subscription_arn(email):
    """返回该 topic 上 email 对应的订阅 ARN；无订阅返回 None。
    SNS 对未确认的 email 订阅显示 "pending confirmation"（非完整 ARN）。
    这里仍原样返回该字符串作为"已有订阅记录"标记，避免重复 subscribe 产生多条待确认订阅；
    是否可用由调用方用 startswith("arn:aws:sns:") 判断。"""
    token = None
    while True:
        kwargs = {"TopicArn": TOPIC_ARN}
        if token:
            kwargs["NextToken"] = token
        resp = _sns.list_subscriptions_by_topic(**kwargs)
        for sub in resp.get("Subscriptions", []):
            if sub.get("Protocol") == "email" and sub.get("Endpoint") == email:
                return sub.get("SubscriptionArn", "") or None
        token = resp.get("NextToken")
        if not token:
            break
    return None


def _apply_filter_policy(arn, tag_list):
    _sns.set_subscription_attributes(
        SubscriptionArn=arn,
        AttributeName="FilterPolicy",
        AttributeValue=json.dumps({"tags": tag_list}),
    )


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
    arn = _sns_subscription_arn(email)
    created = False
    if arn is None:
        resp = _sns.subscribe(TopicArn=TOPIC_ARN, Protocol="email", Endpoint=email)
        arn = resp.get("SubscriptionArn", "")
        created = True

    # 3. 更新 FilterPolicy 为用户订阅的全部标签
    #    仅当拿到真实完整 ARN（arn:aws:sns:...）才设置；SNS 对 email 首次 subscribe
    #    返回的是 "PendingConfirmation"（非完整 ARN），此时 SetSubscriptionAttributes 会
    #    报 "An ARN must have at least 6 elements" —— 待用户点确认邮件生效后再设置
    all_tags = _subscribed_tags(user_sub)
    if arn and arn.startswith("arn:aws:sns:"):
        _apply_filter_policy(arn, all_tags)

    return _json(
        200,
        {
            "email": email,
            "tags": all_tags,
            "subscription_created": created,
            "message": (
                "Subscription updated. If a confirmation email was sent, "
                "click the link to activate it."
            ),
        },
    )