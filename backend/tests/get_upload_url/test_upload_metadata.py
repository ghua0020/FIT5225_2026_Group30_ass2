import importlib
import json
import sys

import boto3
from botocore.exceptions import ClientError


class FakeS3:
    def __init__(self, existing_keys=None):
        self.existing_keys = set(existing_keys or [])
        self.presigned = []

    def head_object(self, Bucket, Key):
        if Key in self.existing_keys:
            return {"Metadata": {}}
        raise ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}},
            "HeadObject",
        )

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        self.operation = operation
        self.params = Params
        self.expires_in = ExpiresIn
        self.presigned.append((operation, Params, ExpiresIn))
        return "https://example.invalid/presigned"


class FakeDynamoResource:
    def __init__(self, table=None):
        self.table = table

    def Table(self, name):
        assert self.table is not None
        return self.table


class FakeTable:
    def __init__(self, items=None):
        self.items = list(items or [])
        self.queries = []

    def query(self, **kwargs):
        self.queries.append(kwargs)
        return {"Items": list(self.items)}


def _load_upload_module(monkeypatch, table=None, fake_s3=None):
    fake_s3 = fake_s3 or FakeS3()
    monkeypatch.setenv("BUCKET_NAME", "media-bucket")
    monkeypatch.setenv("UPLOAD_PREFIX", "uploads/by-checksum/")
    if table is None:
        monkeypatch.delenv("FILES_TABLE", raising=False)
        monkeypatch.delenv("CHECKSUM_INDEX", raising=False)
    else:
        monkeypatch.setenv("FILES_TABLE", "files")
        monkeypatch.setenv("CHECKSUM_INDEX", "checksum-index")
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: fake_s3)
    monkeypatch.setattr(
        boto3,
        "resource",
        lambda *args, **kwargs: FakeDynamoResource(table),
    )
    module_name = "backend.lambdas.get_upload_url.lambda_function"
    sys.modules.pop(module_name, None)
    module = importlib.import_module(module_name)
    return module, fake_s3


def test_presigned_upload_carries_schema_metadata(monkeypatch) -> None:
    module, fake_s3 = _load_upload_module(monkeypatch)
    checksum = "a" * 64
    response = module.lambda_handler(
        {
            "queryStringParameters": {
                "filename": "cat.jpg",
                "content_type": "image/jpeg",
                "checksum": checksum,
            },
            "requestContext": {
                "authorizer": {"claims": {"sub": "cognito-user-sub"}}
            },
        },
        None,
    )
    body = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert body["fileKey"] == "uploads/by-checksum/" + checksum
    assert body["uploadHeaders"] == {
        "Content-Type": "image/jpeg",
        "If-None-Match": "*",
        "x-amz-meta-checksum": checksum,
        "x-amz-meta-uploaded-by": "cognito-user-sub",
        "x-amz-meta-original-filename": "cat.jpg",
    }
    assert fake_s3.params["Metadata"] == {
        "checksum": checksum,
        "uploaded-by": "cognito-user-sub",
        "original-filename": "cat.jpg",
    }
    assert fake_s3.params["IfNoneMatch"] == "*"


def test_upload_rejects_missing_cognito_sub(monkeypatch) -> None:
    module, _ = _load_upload_module(monkeypatch)
    response = module.lambda_handler(
        {
            "queryStringParameters": {
                "filename": "cat.jpg",
                "content_type": "image/jpeg",
                "checksum": "a" * 64,
            },
            "requestContext": {"authorizer": {}},
        },
        None,
    )
    assert response["statusCode"] == 401


def test_same_checksum_uses_same_key_for_different_filenames(monkeypatch) -> None:
    module, _ = _load_upload_module(monkeypatch)
    checksum = "b" * 64

    keys = []
    for filename in ("cat.jpg", "renamed-copy.png"):
        response = module.lambda_handler(
            {
                "queryStringParameters": {
                    "filename": filename,
                    "content_type": "image/jpeg",
                    "checksum": checksum,
                },
                "requestContext": {"authorizer": {"claims": {"sub": "user-1"}}},
            },
            None,
        )
        keys.append(json.loads(response["body"])["fileKey"])

    assert keys == ["uploads/by-checksum/" + checksum] * 2


def test_database_gsi_rejects_processed_duplicate(monkeypatch) -> None:
    table = FakeTable([{"file_id": "existing-file"}])
    module, fake_s3 = _load_upload_module(monkeypatch, table=table)
    checksum = "c" * 64

    response = module.lambda_handler(
        {
            "queryStringParameters": {
                "filename": "copy.jpg",
                "content_type": "image/jpeg",
                "checksum": checksum,
            },
            "requestContext": {"authorizer": {"claims": {"sub": "user-2"}}},
        },
        None,
    )
    body = json.loads(response["body"])

    assert body["duplicate"] is True
    assert body["checksum"] == checksum
    assert len(table.queries) == 1
    assert table.queries[0]["IndexName"] == "checksum-index"
    assert fake_s3.presigned == []
