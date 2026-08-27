import importlib
import json
import sys

import boto3


class FakeS3:
    def list_objects_v2(self, **kwargs):
        return {"KeyCount": 0}

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        self.operation = operation
        self.params = Params
        self.expires_in = ExpiresIn
        return "https://example.invalid/presigned"


class FakeDynamoResource:
    pass


def _load_upload_module(monkeypatch):
    fake_s3 = FakeS3()
    monkeypatch.setenv("BUCKET_NAME", "media-bucket")
    monkeypatch.delenv("FILES_TABLE", raising=False)
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: fake_s3)
    monkeypatch.setattr(boto3, "resource", lambda *args, **kwargs: FakeDynamoResource())
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
    assert body["uploadHeaders"] == {
        "Content-Type": "image/jpeg",
        "x-amz-meta-checksum": checksum,
        "x-amz-meta-uploaded-by": "cognito-user-sub",
    }
    assert fake_s3.params["Metadata"] == {
        "checksum": checksum,
        "uploaded-by": "cognito-user-sub",
    }


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
