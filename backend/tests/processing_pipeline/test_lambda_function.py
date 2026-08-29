import base64
import json

from backend.processing_pipeline import lambda_function
from backend.processing_pipeline.config import Settings


class FakeQueryService:
    def __init__(self) -> None:
        self.settings = Settings(query_image_max_bytes=16)
        self.received = None

    def detect_query_image(self, raw: bytes) -> dict:
        self.received = raw
        return {"tags": [{"name": "Felis_catus", "count": 1}]}


def test_lambda_routes_explicit_query_operation(monkeypatch) -> None:
    service = FakeQueryService()
    monkeypatch.setattr(lambda_function, "_get_service", lambda: service)
    response = lambda_function.lambda_handler(
        {
            "operation": "detect-query",
            "base64": base64.b64encode(b"image-bytes").decode("ascii"),
        },
        None,
    )

    assert response["statusCode"] == 200
    assert json.loads(response["body"])["tags"][0]["name"] == "Felis_catus"
    assert service.received == b"image-bytes"


def test_lambda_rejects_invalid_query_base64(monkeypatch) -> None:
    service = FakeQueryService()
    monkeypatch.setattr(lambda_function, "_get_service", lambda: service)
    response = lambda_function.lambda_handler(
        {"operation": "detect-query", "base64": "not valid%%%"}, None
    )

    assert response["statusCode"] == 400
    assert service.received is None


def test_lambda_rejects_query_payload_above_limit(monkeypatch) -> None:
    service = FakeQueryService()
    monkeypatch.setattr(lambda_function, "_get_service", lambda: service)
    response = lambda_function.lambda_handler(
        {
            "operation": "detect-query",
            "base64": base64.b64encode(b"x" * 17).decode("ascii"),
        },
        None,
    )

    assert response["statusCode"] == 413
    assert service.received is None
