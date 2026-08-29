from pathlib import Path
import shutil
from datetime import datetime, timezone
from io import BytesIO

from PIL import Image
import pytest

from backend.processing_pipeline.config import Settings
from backend.processing_pipeline.pipeline import ProcessingService, _aggregate_frame_results


class FakeStorage:
    def __init__(self, source: Path) -> None:
        self.source = source
        self.uploads = []

    def head(self, bucket, key):
        return {
            "ContentType": "image/jpeg",
            "Metadata": {
                "checksum": "a" * 64,
                "uploaded-by": "cognito-user-sub",
            },
            "LastModified": datetime(2026, 8, 27, tzinfo=timezone.utc),
        }

    def download(self, bucket, key, destination):
        shutil.copyfile(self.source, destination)

    def upload(self, source, bucket, key, content_type):
        self.uploads.append((bucket, key, content_type, Path(source).read_bytes()))

    @staticmethod
    def url(bucket, key):
        return f"https://{bucket}.s3.us-east-1.amazonaws.com/{key}"


class FakeRepository:
    def __init__(self) -> None:
        self.records = []

    def save_media(self, record):
        self.records.append(dict(record))


class FakeBundle:
    def predict_file(self, path):
        return {
            "model_version": "v1",
            "detection_count": 1,
            "tags": [
                {
                    "name": "Felis_catus",
                    "common_name": "domestic cat",
                    "count": 1,
                    "confidence": 0.9,
                }
            ],
            "detections": [],
        }


class FakeModelProvider:
    def get_bundle(self, bucket):
        return FakeBundle()


def test_image_pipeline_writes_thumbnail_and_completed_record(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    Image.new("RGB", (800, 400), "blue").save(source)
    storage = FakeStorage(source)
    repository = FakeRepository()
    service = ProcessingService(
        storage,
        repository,
        FakeModelProvider(),
        Settings(files_table="files", file_tags_table="file_tags"),
    )
    result = service.process("media-bucket", "uploads/abc-cat.jpg")
    assert result["tag_counts"] == {"Felis_catus": 1}
    assert result["tags"] == ["Felis_catus"]
    assert result["thumb_url"].endswith("/thumbnails/abc-cat.jpg")
    assert storage.uploads[0][2] == "image/jpeg"
    assert len(repository.records) == 1
    assert isinstance(result["created_at"], int)


def test_processing_failure_is_recorded(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"not an image")
    repository = FakeRepository()
    service = ProcessingService(
        FakeStorage(source),
        repository,
        FakeModelProvider(),
        Settings(files_table="files", file_tags_table="file_tags"),
    )
    with pytest.raises(Exception):
        service.process("media-bucket", "uploads/broken.jpg")
    assert repository.records == []


def test_video_results_are_summed() -> None:
    result = _aggregate_frame_results(
        [
            {
                "detection_count": 1,
                "tags": [{"name": "Canis_dingo", "count": 1, "confidence": 0.7}],
            },
            {
                "detection_count": 2,
                "tags": [{"name": "Canis_dingo", "count": 2, "confidence": 0.9}],
            },
        ]
    )
    assert result["detection_count"] == 3
    assert result["tags"][0]["count"] == 3
    assert result["tags"][0]["confidence"] == 0.9


def test_query_detection_returns_tags_without_storage_writes() -> None:
    raw = BytesIO()
    Image.new("RGB", (32, 24), "green").save(raw, format="PNG")
    storage = object()
    repository = FakeRepository()
    service = ProcessingService(
        storage,
        repository,
        FakeModelProvider(),
        Settings(
            files_table="files",
            file_tags_table="file_tags",
            model_bucket="media-bucket",
        ),
    )

    result = service.detect_query_image(raw.getvalue())

    assert result == {"tags": [{"name": "Felis_catus", "count": 1}]}
    assert repository.records == []


def test_query_detection_rejects_non_image_bytes() -> None:
    service = ProcessingService(
        object(),
        FakeRepository(),
        FakeModelProvider(),
        Settings(model_bucket="media-bucket"),
    )
    with pytest.raises(ValueError, match="not a valid image"):
        service.detect_query_image(b"not an image")
