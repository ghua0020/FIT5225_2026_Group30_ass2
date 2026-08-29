import base64
from io import BytesIO
import importlib.util
import json
from pathlib import Path
import sys

import boto3


class FakeLambda:
    def __init__(self, response):
        self.response = response
        self.invocations = []

    def invoke(self, **kwargs):
        self.invocations.append(kwargs)
        response = dict(self.response)
        response["Payload"] = BytesIO(json.dumps(response.pop("payload")).encode("utf-8"))
        return response


class FakeS3:
    def __init__(self):
        self.requests = []

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        self.requests.append((operation, Params, ExpiresIn))
        return f"https://signed.invalid/{Params['Key']}"


class FakeTable:
    def __init__(self, responses):
        self.responses = list(responses)
        self.queries = []

    def query(self, **kwargs):
        self.queries.append(kwargs)
        return self.responses.pop(0)


class FakeDynamoResource:
    def __init__(self, table):
        self.table = table

    def Table(self, name):
        return self.table


def _load_module(monkeypatch, lambda_response, table_responses):
    fake_lambda = FakeLambda(lambda_response)
    fake_s3 = FakeS3()
    fake_table = FakeTable(table_responses)

    monkeypatch.setenv("DETECT_FUNCTION", "pba-processing")
    monkeypatch.setenv("MEDIA_BUCKET", "media-bucket")
    monkeypatch.setenv("FILE_TAGS_TABLE", "file_tags")

    def fake_client(service_name, *args, **kwargs):
        if service_name == "lambda":
            return fake_lambda
        if service_name == "s3":
            return fake_s3
        raise AssertionError(f"unexpected boto3 client: {service_name}")

    monkeypatch.setattr(boto3, "client", fake_client)
    monkeypatch.setattr(
        boto3,
        "resource",
        lambda service_name, *args, **kwargs: FakeDynamoResource(fake_table),
    )

    module_name = "query_by_file_lambda_for_tests"
    sys.modules.pop(module_name, None)
    path = (
        Path(__file__).resolve().parents[2]
        / "lambdas"
        / "query-by-file"
        / "lambda_function.py"
    )
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module, fake_lambda, fake_s3, fake_table


def test_query_by_file_invokes_detect_operation_and_returns_presigned_urls(
    monkeypatch,
) -> None:
    lambda_response = {
        "StatusCode": 200,
        "payload": {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "tags": [
                        {"name": "Felis_catus", "count": 1},
                        {"name": "Animal", "count": 1},
                    ]
                }
            ),
        },
    }
    image_item = {
        "file_id": "image-1",
        "file_type": "image",
        "full_url": "https://media-bucket.s3.us-east-1.amazonaws.com/uploads/cat.jpg",
        "thumb_url": "https://media-bucket.s3.us-east-1.amazonaws.com/thumbnails/cat.jpg",
    }
    module, fake_lambda, fake_s3, fake_table = _load_module(
        monkeypatch,
        lambda_response,
        [
            {"Items": [image_item]},
            {"Items": [image_item]},
        ],
    )

    encoded = base64.b64encode(b"query-image-bytes").decode("ascii")
    response = module.lambda_handler(
        {"body": json.dumps({"base64": encoded})},
        None,
    )
    body = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert body == {
        "detected": ["Felis_catus", "Animal"],
        "count": 1,
        "thumbnails": ["https://signed.invalid/thumbnails/cat.jpg"],
        "thumbnail_sources": [
            "https://media-bucket.s3.us-east-1.amazonaws.com/thumbnails/cat.jpg"
        ],
        "full_images": ["https://signed.invalid/uploads/cat.jpg"],
        "videos": [],
    }
    invoke_payload = json.loads(fake_lambda.invocations[0]["Payload"])
    assert invoke_payload == {"operation": "detect-query", "base64": encoded}
    assert len(fake_table.queries) == 2
    assert [request[1]["Key"] for request in fake_s3.requests] == [
        "thumbnails/cat.jpg",
        "uploads/cat.jpg",
    ]


def test_query_by_file_treats_lambda_function_error_as_failure(monkeypatch) -> None:
    module, _, _, fake_table = _load_module(
        monkeypatch,
        {
            "StatusCode": 200,
            "FunctionError": "Unhandled",
            "payload": {"errorMessage": "model failed"},
        },
        [],
    )

    encoded = base64.b64encode(b"query-image-bytes").decode("ascii")
    response = module.lambda_handler(
        {"body": json.dumps({"base64": encoded})},
        None,
    )

    assert response["statusCode"] == 502
    assert "model failed" in json.loads(response["body"])["detail"]
    assert fake_table.queries == []


def test_query_by_file_rejects_invalid_base64_before_invoking_detection(
    monkeypatch,
) -> None:
    module, fake_lambda, _, _ = _load_module(
        monkeypatch,
        {"StatusCode": 200, "payload": {}},
        [],
    )

    response = module.lambda_handler(
        {"body": json.dumps({"base64": "not-base64%%%"})},
        None,
    )

    assert response["statusCode"] == 400
    assert fake_lambda.invocations == []
