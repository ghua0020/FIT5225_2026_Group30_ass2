"""Core S3 media processing orchestration."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any
from urllib.parse import unquote
from uuid import NAMESPACE_URL, uuid5

from PIL import Image, UnidentifiedImageError

from .config import Settings
from .media import create_thumbnail, detect_media_type, extract_video_frames


def _epoch_milliseconds(value: Any | None = None) -> int:
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _aggregate_frame_results(results: list[dict]) -> dict:
    grouped: dict[str, dict] = {}
    detection_count = 0
    for result in results:
        detection_count += int(result.get("detection_count", 0))
        for tag in result.get("tags", []):
            current = grouped.setdefault(
                tag["name"],
                {
                    "name": tag["name"],
                    "common_name": tag.get("common_name", ""),
                    "count": 0,
                    "confidence": 0.0,
                },
            )
            current["count"] += int(tag.get("count", 0))
            current["confidence"] = max(
                current["confidence"], float(tag.get("confidence", 0.0))
            )
    return {
        "detection_count": detection_count,
        "tags": [grouped[name] for name in sorted(grouped)],
    }


class ProcessingService:
    def __init__(
        self,
        storage: Any,
        repository: Any,
        model_provider: Any,
        settings: Settings,
        notifier: Any | None = None,
    ) -> None:
        self.storage = storage
        self.repository = repository
        self.model_provider = model_provider
        self.settings = settings
        self.notifier = notifier

    def _thumbnail_key(self, source_key: str) -> str:
        relative = source_key[len(self.settings.upload_prefix) :]
        relative_path = PurePosixPath(relative)
        target = relative_path.with_suffix(".jpg")
        return f"{self.settings.thumbnail_prefix.rstrip('/')}/{target.as_posix()}"

    def detect_query_image(self, raw: bytes) -> dict:
        """Detect tags in an API query image without writing S3, DynamoDB or SNS."""
        if not raw:
            raise ValueError("query image is empty")
        if len(raw) > self.settings.query_image_max_bytes:
            raise ValueError(
                f"query image exceeds {self.settings.query_image_max_bytes} bytes"
            )
        try:
            with Image.open(BytesIO(raw)) as image:
                image.verify()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ValueError("query payload is not a valid image") from exc

        local_models = (
            self.settings.local_md_model_path,
            self.settings.local_species_model_path,
            self.settings.local_labels_path,
        )
        if not self.settings.model_bucket and not all(local_models):
            raise RuntimeError("MODEL_BUCKET must be configured for query detection")

        with tempfile.TemporaryDirectory(prefix="pba-query-") as temp_dir:
            image_path = Path(temp_dir) / "query-image"
            image_path.write_bytes(raw)
            bundle = self.model_provider.get_bundle(self.settings.model_bucket)
            inference = bundle.predict_file(image_path)

        return {
            "tags": [
                {"name": tag["name"], "count": int(tag.get("count", 0))}
                for tag in inference.get("tags", [])
                if tag.get("name")
            ]
        }

    def process(self, bucket: str, key: str) -> dict:
        if not key.startswith(self.settings.upload_prefix):
            return {"status": "IGNORED", "reason": "outside upload prefix", "key": key}

        head = self.storage.head(bucket, key)
        metadata = head.get("Metadata") or {}
        media_type = detect_media_type(key, head.get("ContentType", ""))
        file_id = str(uuid5(NAMESPACE_URL, f"s3://{bucket}/{key}"))
        checksum = str(metadata.get("checksum", "")).lower()
        uploaded_by = str(metadata.get("uploaded-by", ""))
        original_filename = unquote(str(metadata.get("original-filename", "")))
        original_filename = original_filename.replace("\\", "/")
        file_name = PurePosixPath(original_filename).name if original_filename else ""
        if file_name in {"", ".", ".."}:
            file_name = PurePosixPath(key).name
        if not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise ValueError("S3 object metadata checksum must be a complete SHA-256")
        if not uploaded_by:
            raise ValueError("S3 object metadata uploaded-by is required")

        with tempfile.TemporaryDirectory(prefix="pba-processing-") as temp_dir:
            temp = Path(temp_dir)
            # New checksum-addressed S3 keys intentionally have no extension.
            # Preserve the original filename locally so video decoders and the
            # Gallery still receive a useful name. Legacy objects fall back to
            # their key basename above.
            local_media = temp / file_name
            self.storage.download(bucket, key, local_media)
            bundle = self.model_provider.get_bundle(bucket)

            if media_type == "image":
                thumbnail_path = temp / "thumbnail.jpg"
                create_thumbnail(
                    local_media,
                    thumbnail_path,
                    max_size=self.settings.thumbnail_max_size,
                    quality=self.settings.thumbnail_quality,
                )
                thumbnail_key = self._thumbnail_key(key)
                self.storage.upload(
                    thumbnail_path, bucket, thumbnail_key, content_type="image/jpeg"
                )
                inference = bundle.predict_file(local_media)
                thumb_url = self.storage.url(bucket, thumbnail_key)
            else:
                frame_paths = extract_video_frames(local_media, temp / "frames")
                frame_results = [bundle.predict_file(path) for path in frame_paths]
                inference = _aggregate_frame_results(frame_results)
                thumb_url = None

            tag_counts = {
                tag["name"]: tag["count"] for tag in inference["tags"]
            }
            record = {
                "file_id": file_id,
                "checksum": checksum,
                "file_name": file_name,
                "file_type": media_type,
                "tags": sorted(tag_counts),
                "tag_counts": tag_counts,
                "full_url": self.storage.url(bucket, key),
                "uploaded_by": uploaded_by,
                "created_at": _epoch_milliseconds(head.get("LastModified")),
            }
            if media_type == "image":
                record["thumb_url"] = thumb_url
            self.repository.save_media(record)
            if self.notifier is not None:
                self.notifier.publish(record)
            return record
