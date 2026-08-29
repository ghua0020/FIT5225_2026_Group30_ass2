from decimal import Decimal
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
        self.scans = []

    def scan(self, **kwargs):
        self.scans.append(kwargs)
        return self.responses.pop(0)


class FakeDynamoResource:
    def __init__(self, table):
        self.table = table

    def Table(self, name):
        return self.table


def _load_module(monkeypatch, responses):
    fake_s3 = FakeS3()
    fake_table = FakeTable(responses)
    monkeypatch.setenv("FILES_TABLE", "files")
    monkeypatch.setenv("MEDIA_BUCKET", "media-bucket")
    monkeypatch.setenv("PRESIGNED_URL_TTL_SECONDS", "900")
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: fake_s3)
    monkeypatch.setattr(
        boto3,
        "resource",
        lambda *args, **kwargs: FakeDynamoResource(fake_table),
    )

    module_name = "files_list_lambda_for_tests"
    sys.modules.pop(module_name, None)
    path = (
        Path(__file__).resolve().parents[2]
        / "lambdas"
        / "files-list"
        / "lambda_function.py"
    )
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module, fake_s3, fake_table


def test_lists_files_with_presigned_urls_and_json_numbers(monkeypatch) -> None:
    item = {
        "file_id": "file-1",
        "checksum": "a" * 64,
        "file_type": "image",
        "tags": ["Felis_catus"],
        "tag_counts": {"Felis_catus": Decimal("2")},
        "created_at": Decimal("1787911023000"),
        "full_url": "https://media-bucket.s3.us-east-1.amazonaws.com/uploads/cat.jpg",
        "thumb_url": "https://media-bucket.s3.us-east-1.amazonaws.com/thumbnails/cat.jpg",
    }
    module, fake_s3, fake_table = _load_module(
        monkeypatch,
        [{"Items": [item], "LastEvaluatedKey": {"file_id": "file-1"}}],
    )

    response = module.lambda_handler(
        {"queryStringParameters": {"limit": "25"}},
        None,
    )
    body = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert body["items"] == [
        {
            "file_id": "file-1",
            "checksum": "a" * 64,
            "file_type": "image",
            "file_name": "cat.jpg",
            "tags": ["Felis_catus"],
            "tag_counts": {"Felis_catus": 2},
            "created_at": 1787911023000,
            "full_url": "https://signed.invalid/uploads/cat.jpg",
            "thumb_url": "https://signed.invalid/thumbnails/cat.jpg",
        }
    ]
    assert body["next_cursor"]
    assert fake_table.scans == [{"Limit": 25}]
    assert [request[1]["Key"] for request in fake_s3.requests] == [
        "uploads/cat.jpg",
        "thumbnails/cat.jpg",
    ]


def test_cursor_is_passed_to_next_scan(monkeypatch) -> None:
    module, _, fake_table = _load_module(
        monkeypatch,
        [
            {"Items": [], "LastEvaluatedKey": {"file_id": "file-1"}},
            {"Items": []},
        ],
    )
    first = json.loads(
        module.lambda_handler({"queryStringParameters": None}, None)["body"]
    )
    response = module.lambda_handler(
        {"queryStringParameters": {"cursor": first["next_cursor"]}},
        None,
    )

    assert response["statusCode"] == 200
    assert fake_table.scans[1] == {
        "Limit": 100,
        "ExclusiveStartKey": {"file_id": "file-1"},
    }


def test_rejects_invalid_cursor_without_scanning(monkeypatch) -> None:
    module, _, fake_table = _load_module(monkeypatch, [])

    response = module.lambda_handler(
        {"queryStringParameters": {"cursor": "%%%"}},
        None,
    )

    assert response["statusCode"] == 400
    assert fake_table.scans == []
