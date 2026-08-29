"""AWS Lambda entry point for S3 ObjectCreated events."""

from __future__ import annotations

import base64
import binascii
import json
import logging
from typing import Any
from urllib.parse import unquote_plus

import boto3

from .config import Settings
from .models import ModelProvider
from .pipeline import ProcessingService
from .storage import DynamoMediaRepository, S3Storage, SnsNotifier


logger = logging.getLogger()
logger.setLevel(logging.INFO)

_service: ProcessingService | None = None
QUERY_OPERATION = "detect-query"


def _build_service() -> ProcessingService:
    settings = Settings.from_env()
    if not settings.files_table:
        raise RuntimeError("FILES_TABLE must be configured")
    if not settings.file_tags_table:
        raise RuntimeError("FILE_TAGS_TABLE must be configured")
    s3_client = boto3.client("s3")
    dynamodb = boto3.client("dynamodb")
    sns_client = boto3.client("sns") if settings.notify_topic_arn else None
    notifier = (
        SnsNotifier(sns_client, settings.notify_topic_arn) if sns_client is not None else None
    )
    return ProcessingService(
        storage=S3Storage(s3_client, settings.region),
        repository=DynamoMediaRepository(
            dynamodb, settings.files_table, settings.file_tags_table
        ),
        model_provider=ModelProvider(s3_client, settings),
        settings=settings,
        notifier=notifier,
    )


def _get_service() -> ProcessingService:
    global _service
    if _service is None:
        _service = _build_service()
    return _service


def _proxy_response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "body": json.dumps(body, ensure_ascii=False),
    }


def _handle_query_image(event: dict, service: ProcessingService) -> dict:
    encoded = event.get("base64")
    if not isinstance(encoded, str) or not encoded.strip():
        return _proxy_response(400, {"error": "base64 image is required"})
    encoded = encoded.strip()

    max_bytes = service.settings.query_image_max_bytes
    max_encoded_length = 4 * ((max_bytes + 2) // 3)
    if len(encoded) > max_encoded_length:
        return _proxy_response(413, {"error": "query image exceeds 4 MiB"})
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return _proxy_response(400, {"error": "base64 image is invalid"})
    if len(raw) > max_bytes:
        return _proxy_response(413, {"error": "query image exceeds 4 MiB"})

    try:
        return _proxy_response(200, service.detect_query_image(raw))
    except ValueError as exc:
        return _proxy_response(400, {"error": str(exc)})
    except Exception:
        logger.exception("Query image detection failed")
        return _proxy_response(500, {"error": "query image detection failed"})


def lambda_handler(event: dict, context: Any) -> dict:
    service = _get_service()
    if event.get("operation") == QUERY_OPERATION:
        return _handle_query_image(event, service)

    results = []
    for event_record in event.get("Records", []):
        if event_record.get("eventSource") != "aws:s3":
            logger.info("Ignoring non-S3 event record")
            continue
        bucket = event_record["s3"]["bucket"]["name"]
        key = unquote_plus(event_record["s3"]["object"]["key"])
        logger.info("Processing s3://%s/%s", bucket, key)
        results.append(service.process(bucket, key))
    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "processed": len(
                    [result for result in results if result.get("status") != "IGNORED"]
                ),
                "results": results,
            }
        ),
    }
