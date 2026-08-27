"""AWS Lambda entry point for S3 ObjectCreated events."""

from __future__ import annotations

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


def lambda_handler(event: dict, context: Any) -> dict:
    results = []
    service = _get_service()
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
