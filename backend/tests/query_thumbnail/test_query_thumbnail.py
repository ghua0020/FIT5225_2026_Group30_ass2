import importlib.util
import json
from pathlib import Path
import sys

import boto3


class FakeS3:
    def __init__(self):
        self.requests = []

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        self.requests.append((operation, Params, ExpiresIn))
        return f"https://signed.invalid/{Params['Key']}"


class FakeTable:
    def __init__(self, item):
        self.item = item
        self.query_kwargs = None

    def query(self, **kwargs):
        self.query_kwargs = kwargs
        return {"Items": [self.item]}


class FakeDynamoResource:
    def __init__(self, table):
        self.table = table

    def Table(self, name):
        return self.table


def _load_module(monkeypatch, item):
    fake_s3 = FakeS3()
    fake_table = FakeTable(item)
    monkeypatch.setenv("MEDIA_BUCKET", "media-bucket")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: fake_s3)
    monkeypatch.setattr(
        boto3,
        "resource",
        lambda *args, **kwargs: FakeDynamoResource(fake_table),
    )

    module_name = "query_thumbnail_lambda_for_tests"
    sys.modules.pop(module_name, None)
    path = (
        Path(__file__).resolve().parents[2]
        / "lambdas"
        / "query-thumbnail"
        / "lambda_function.py"
    )
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module, fake_s3, fake_table


def test_thumbnail_lookup_accepts_presigned_url_and_returns_fresh_urls(
    monkeypatch,
) -> None:
    item = {
        "file_id": "image-1",
        "full_url": "https://media-bucket.s3.us-east-1.amazonaws.com/uploads/cat.jpg",
        "thumb_url": "https://media-bucket.s3.us-east-1.amazonaws.com/thumbnails/cat.jpg",
    }
    module, fake_s3, fake_table = _load_module(monkeypatch, item)

    response = module.lambda_handler(
        {
            "queryStringParameters": {
                "url": (
                    "https://media-bucket.s3.us-east-1.amazonaws.com/"
                    "thumbnails/cat.jpg?X-Amz-Signature=expired"
                )
            }
        },
        None,
    )
    body = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert body["full_url"] == "https://signed.invalid/uploads/cat.jpg"
    assert body["thumb_url"] == "https://signed.invalid/thumbnails/cat.jpg"
    expression = fake_table.query_kwargs["KeyConditionExpression"].get_expression()
    assert expression["values"][1] == (
        "https://media-bucket.s3.us-east-1.amazonaws.com/thumbnails/cat.jpg"
    )
    assert [request[1]["Key"] for request in fake_s3.requests] == [
        "uploads/cat.jpg",
        "thumbnails/cat.jpg",
    ]


def test_thumbnail_lookup_rejects_url_from_another_bucket(monkeypatch) -> None:
    module, _, fake_table = _load_module(monkeypatch, {})

    response = module.lambda_handler(
        {
            "queryStringParameters": {
                "url": "https://other-bucket.s3.us-east-1.amazonaws.com/x.jpg"
            }
        },
        None,
    )

    assert response["statusCode"] == 400
    assert fake_table.query_kwargs is None
