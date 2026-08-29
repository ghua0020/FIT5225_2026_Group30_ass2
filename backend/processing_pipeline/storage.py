"""AWS storage, database, and notification adapters."""

from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer


def _dynamodb_value(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(str(round(value, 6)))
    if isinstance(value, dict):
        return {key: _dynamodb_value(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_dynamodb_value(item) for item in value]
    return value


class S3Storage:
    def __init__(self, client: Any, region: str = "us-east-1") -> None:
        self.client = client
        self.region = region

    def head(self, bucket: str, key: str) -> dict:
        return self.client.head_object(Bucket=bucket, Key=key)

    def download(self, bucket: str, key: str, destination: str | Path) -> None:
        self.client.download_file(bucket, key, str(destination))

    def upload(
        self,
        source: str | Path,
        bucket: str,
        key: str,
        content_type: str,
    ) -> None:
        self.client.upload_file(
            str(source), bucket, key, ExtraArgs={"ContentType": content_type}
        )

    def url(self, bucket: str, key: str) -> str:
        return f"https://{bucket}.s3.{self.region}.amazonaws.com/{quote(key, safe='/')}"


class DynamoMediaRepository:
    """Atomically maintains the files record and its reverse tag rows."""

    def __init__(self, client: Any, files_table: str, file_tags_table: str) -> None:
        self.client = client
        self.files_table = files_table
        self.file_tags_table = file_tags_table
        self.serializer = TypeSerializer()
        self.deserializer = TypeDeserializer()

    def _serialise_map(self, value: dict) -> dict:
        clean = _dynamodb_value(value)
        return {key: self.serializer.serialize(item) for key, item in clean.items()}

    def _previous_tags(self, file_id: str) -> set[str]:
        response = self.client.get_item(
            TableName=self.files_table,
            Key=self._serialise_map({"file_id": file_id}),
            ProjectionExpression="#tags",
            ExpressionAttributeNames={"#tags": "tags"},
            ConsistentRead=True,
        )
        item = response.get("Item")
        if not item or "tags" not in item:
            return set()
        return set(self.deserializer.deserialize(item["tags"]))

    def save_media(self, record: dict) -> None:
        new_tags = set(record["tags"])
        stale_tags = self._previous_tags(record["file_id"]) - new_tags
        actions = [
            {
                "Put": {
                    "TableName": self.files_table,
                    "Item": self._serialise_map(record),
                }
            }
        ]
        for tag in sorted(new_tags):
            tag_item = {
                "tag": tag,
                "file_id": record["file_id"],
                "count": record["tag_counts"][tag],
                "file_type": record["file_type"],
                "full_url": record["full_url"],
                "created_at": record["created_at"],
            }
            if record["file_type"] == "image":
                tag_item["thumb_url"] = record["thumb_url"]
            actions.append(
                {
                    "Put": {
                        "TableName": self.file_tags_table,
                        "Item": self._serialise_map(tag_item),
                    }
                }
            )
        for tag in sorted(stale_tags):
            actions.append(
                {
                    "Delete": {
                        "TableName": self.file_tags_table,
                        "Key": self._serialise_map(
                            {"tag": tag, "file_id": record["file_id"]}
                        ),
                    }
                }
            )
        self.client.transact_write_items(TransactItems=actions)


class SnsNotifier:
    def __init__(
        self,
        client: Any,
        topic_arn: str,
        s3_client: Any | None = None,
        url_expiry: int = 3600,
    ) -> None:
        self.client = client
        self.topic_arn = topic_arn
        self.s3_client = s3_client
        self.url_expiry = url_expiry

    @staticmethod
    def _s3_location(url: str) -> tuple[str, str]:
        parsed = urlsplit(url)
        if parsed.scheme == "s3":
            bucket = parsed.netloc
        else:
            hostname = parsed.hostname or ""
            marker = hostname.find(".s3")
            bucket = hostname[:marker] if marker > 0 else ""
        key = unquote(parsed.path.lstrip("/"))
        if not bucket or not key:
            raise ValueError("full_url is not a supported S3 object URL")
        return bucket, key

    def _temporary_url(self, full_url: str) -> str | None:
        if self.s3_client is None:
            return None
        try:
            bucket, key = self._s3_location(full_url)
            return self.s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=self.url_expiry,
            )
        except Exception:
            return None

    def publish(self, record: dict) -> None:
        tag_names = list(record.get("tags") or [])
        if not self.topic_arn or not tag_names:
            return
        message = {
            "file_id": record["file_id"],
            "tags": tag_names,
            "full_url": record["full_url"],
            "created_at": record["created_at"],
        }
        temporary_url = self._temporary_url(record["full_url"])
        if temporary_url:
            message["temporary_url"] = temporary_url
            message["temporary_url_expires_in"] = self.url_expiry
        self.client.publish(
            TopicArn=self.topic_arn,
            Message=json.dumps(message),
            MessageAttributes={
                "tags": {
                    "DataType": "String.Array",
                    "StringValue": json.dumps(tag_names),
                }
            },
        )
