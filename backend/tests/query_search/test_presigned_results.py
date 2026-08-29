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
    def __init__(self, responses):
        self.responses = list(responses)

    def query(self, **kwargs):
        return self.responses.pop(0)


class FakeDynamoResource:
    def __init__(self, table):
        self.table = table

    def Table(self, name):
        return self.table


def _load_module(monkeypatch, directory, responses):
    fake_s3 = FakeS3()
    fake_table = FakeTable(responses)
    monkeypatch.setenv("MEDIA_BUCKET", "media-bucket")
    monkeypatch.setenv("FILE_TAGS_TABLE", "file_tags")
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: fake_s3)
    monkeypatch.setattr(
        boto3,
        "resource",
        lambda *args, **kwargs: FakeDynamoResource(fake_table),
    )

    module_name = f"{directory.replace('-', '_')}_lambda_for_tests"
    sys.modules.pop(module_name, None)
    path = (
        Path(__file__).resolve().parents[2]
        / "lambdas"
        / directory
        / "lambda_function.py"
    )
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module, fake_s3


def test_species_search_returns_browser_readable_urls(monkeypatch) -> None:
    image = {
        "file_id": "image-1",
        "file_type": "image",
        "full_url": "https://media-bucket.s3.us-east-1.amazonaws.com/uploads/deer.jpg",
        "thumb_url": "https://media-bucket.s3.us-east-1.amazonaws.com/thumbnails/deer.jpg",
    }
    module, fake_s3 = _load_module(
        monkeypatch,
        "query-by-species",
        [{"Items": [image]}],
    )

    response = module.lambda_handler(
        {"queryStringParameters": {"species": "Dama_dama"}},
        None,
    )
    body = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert body["thumbnails"] == ["https://signed.invalid/thumbnails/deer.jpg"]
    assert body["thumbnail_sources"] == [image["thumb_url"]]
    assert body["full_images"] == ["https://signed.invalid/uploads/deer.jpg"]
    assert [request[1]["Key"] for request in fake_s3.requests] == [
        "thumbnails/deer.jpg",
        "uploads/deer.jpg",
    ]


def test_tag_count_search_returns_browser_readable_urls(monkeypatch) -> None:
    image = {
        "file_id": "image-1",
        "file_type": "image",
        "full_url": "https://media-bucket.s3.us-east-1.amazonaws.com/uploads/cat.jpg",
        "thumb_url": "https://media-bucket.s3.us-east-1.amazonaws.com/thumbnails/cat.jpg",
        "count": 2,
    }
    module, fake_s3 = _load_module(
        monkeypatch,
        "query-by-tags",
        [{"Items": [image]}],
    )

    response = module.lambda_handler(
        {"body": json.dumps({"Felis_catus": 1})},
        None,
    )
    body = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert body["count"] == 1
    assert body["thumbnails"] == ["https://signed.invalid/thumbnails/cat.jpg"]
    assert body["thumbnail_sources"] == [image["thumb_url"]]
    assert body["full_images"] == ["https://signed.invalid/uploads/cat.jpg"]
    assert [request[1]["Key"] for request in fake_s3.requests] == [
        "thumbnails/cat.jpg",
        "uploads/cat.jpg",
    ]
