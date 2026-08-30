import importlib.util
import json
from pathlib import Path
import sys

import boto3


TOPIC_ARN = "arn:aws:sns:us-east-1:123456789012:pba-tag-events"
SUBSCRIPTION_ARN = TOPIC_ARN + ":confirmed-id"
EMAIL = "person@example.com"


class FakeTable:
    def __init__(self, query_responses=None, scan_responses=None):
        self.query_responses = list(query_responses or [])
        self.scan_responses = list(scan_responses or [])
        self.puts = []
        self.deletes = []

    def query(self, **kwargs):
        return self.query_responses.pop(0)

    def scan(self, **kwargs):
        return self.scan_responses.pop(0)

    def put_item(self, **kwargs):
        self.puts.append(kwargs["Item"])

    def delete_item(self, **kwargs):
        self.deletes.append(kwargs["Key"])


class FakeDynamoResource:
    def __init__(self, table):
        self.table = table

    def Table(self, name):
        assert name == "subscriptions"
        return self.table


class FakeSns:
    def __init__(self, list_responses):
        self.list_responses = list(list_responses)
        self.attribute_updates = []
        self.subscribe_requests = []
        self.unsubscribe_requests = []

    def list_subscriptions_by_topic(self, **kwargs):
        assert kwargs["TopicArn"] == TOPIC_ARN
        return self.list_responses.pop(0)

    def set_subscription_attributes(self, **kwargs):
        self.attribute_updates.append(kwargs)

    def subscribe(self, **kwargs):
        self.subscribe_requests.append(kwargs)
        return {"SubscriptionArn": "pending confirmation"}

    def unsubscribe(self, **kwargs):
        self.unsubscribe_requests.append(kwargs)


def _load_module(monkeypatch, folder, table, sns):
    monkeypatch.setenv("SUBSCRIPTIONS_TABLE", "subscriptions")
    monkeypatch.setenv("NOTIFY_TOPIC_ARN", TOPIC_ARN)
    monkeypatch.setattr(boto3, "resource", lambda *args, **kwargs: FakeDynamoResource(table))
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: sns)

    name = "notification_lambda_" + folder.replace("-", "_")
    sys.modules.pop(name, None)
    path = (
        Path(__file__).resolve().parents[1]
        / "lambdas"
        / folder
        / "lambda_function.py"
    )
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _event(body=None):
    event = {
        "requestContext": {
            "authorizer": {"claims": {"sub": "current-user", "email": EMAIL}}
        }
    }
    if body is not None:
        event["body"] = json.dumps(body)
    return event


def _confirmed_subscription():
    return {
        "Protocol": "email",
        "Endpoint": EMAIL,
        "SubscriptionArn": SUBSCRIPTION_ARN,
    }


def test_list_repairs_filter_after_email_confirmation(monkeypatch):
    table = FakeTable(
        query_responses=[{"Items": [{"tag": "Felis_catus"}]}],
        scan_responses=[
            {
                "Items": [
                    {"tag": "Felis_catus", "email": EMAIL},
                    {"tag": "Dama_dama", "email": EMAIL},
                ]
            }
        ],
    )
    sns = FakeSns([{"Subscriptions": [_confirmed_subscription()]}])
    module = _load_module(monkeypatch, "notify-list", table, sns)

    response = module.lambda_handler(_event(), None)
    body = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert body["tags"] == ["Felis_catus"]
    assert body["filter_sync"] == "synced"
    assert sns.attribute_updates == [
        {
            "SubscriptionArn": SUBSCRIPTION_ARN,
            "AttributeName": "FilterPolicy",
            "AttributeValue": json.dumps({"tags": ["Dama_dama", "Felis_catus"]}),
        }
    ]


def test_subscribe_does_not_duplicate_pending_subscription(monkeypatch):
    pending = {
        "Protocol": "email",
        "Endpoint": EMAIL,
        "SubscriptionArn": "PendingConfirmation",
    }
    table = FakeTable(
        query_responses=[{"Items": [{"tag": "Felis_catus"}]}],
        scan_responses=[{"Items": [{"tag": "Felis_catus", "email": EMAIL}]}],
    )
    sns = FakeSns(
        [
            {"Subscriptions": [pending]},
            {"Subscriptions": [pending]},
        ]
    )
    module = _load_module(monkeypatch, "notify-subscribe", table, sns)

    response = module.lambda_handler(
        _event({"tags": ["Felis_catus"]}),
        None,
    )

    assert response["statusCode"] == 200
    assert sns.subscribe_requests == []
    assert sns.attribute_updates == []


def test_list_removes_stale_subscription_when_email_has_no_tags(monkeypatch):
    table = FakeTable(
        query_responses=[{"Items": []}],
        scan_responses=[{"Items": []}],
    )
    sns = FakeSns([{"Subscriptions": [_confirmed_subscription()]}])
    module = _load_module(monkeypatch, "notify-list", table, sns)

    response = module.lambda_handler(_event(), None)

    assert response["statusCode"] == 200
    assert sns.attribute_updates == []
    assert sns.unsubscribe_requests == [{"SubscriptionArn": SUBSCRIPTION_ARN}]


def test_unsubscribe_preserves_other_identity_tags_for_same_email(monkeypatch):
    table = FakeTable(
        query_responses=[{"Items": [{"tag": "Felis_catus"}]}],
        scan_responses=[{"Items": [{"tag": "Dama_dama", "email": EMAIL}]}],
    )
    sns = FakeSns([{"Subscriptions": [_confirmed_subscription()]}])
    module = _load_module(monkeypatch, "notify-unsubscribe", table, sns)

    response = module.lambda_handler(
        _event({"tags": ["Felis_catus"]}),
        None,
    )

    assert response["statusCode"] == 200
    assert table.deletes == [{"user_sub": "current-user", "tag": "Felis_catus"}]
    assert sns.unsubscribe_requests == []
    assert json.loads(sns.attribute_updates[0]["AttributeValue"]) == {
        "tags": ["Dama_dama"]
    }
