"""Environment-backed configuration for the processing Lambda."""

from __future__ import annotations

from dataclasses import dataclass
import os


def _as_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else default


def _as_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return float(value) if value else default


@dataclass(frozen=True)
class Settings:
    files_table: str = ""
    file_tags_table: str = ""
    region: str = "us-east-1"
    upload_prefix: str = "uploads/"
    thumbnail_prefix: str = "thumbnails/"
    model_bucket: str = ""
    model_prefix: str = "models"
    model_version: str = "v1"
    md_model_name: str = "mdv5a.pt"
    species_model_name: str = "model.pt"
    labels_name: str = "labels.txt"
    model_cache_dir: str = "/tmp/pba-models"
    detector_confidence: float = 0.05
    classifier_confidence: float = 0.0
    thumbnail_max_size: int = 480
    thumbnail_quality: int = 80
    notify_topic_arn: str = ""
    local_md_model_path: str = ""
    local_species_model_path: str = ""
    local_labels_path: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            files_table=os.environ.get("FILES_TABLE", ""),
            file_tags_table=os.environ.get("FILE_TAGS_TABLE", ""),
            region=os.environ.get("AWS_REGION", "us-east-1"),
            upload_prefix=os.environ.get("UPLOAD_PREFIX", "uploads/"),
            thumbnail_prefix=os.environ.get("THUMBNAIL_PREFIX", "thumbnails/"),
            model_bucket=os.environ.get("MODEL_BUCKET", ""),
            model_prefix=os.environ.get("MODEL_PREFIX", "models"),
            model_version=os.environ.get("MODEL_VERSION", "v1"),
            md_model_name=os.environ.get("MD_MODEL_NAME", "mdv5a.pt"),
            species_model_name=os.environ.get("SPECIES_MODEL_NAME", "model.pt"),
            labels_name=os.environ.get("LABELS_NAME", "labels.txt"),
            model_cache_dir=os.environ.get("MODEL_CACHE_DIR", "/tmp/pba-models"),
            detector_confidence=_as_float("DETECTOR_CONFIDENCE", 0.05),
            classifier_confidence=_as_float("CLASSIFIER_CONFIDENCE", 0.0),
            thumbnail_max_size=_as_int("THUMBNAIL_MAX_SIZE", 480),
            thumbnail_quality=_as_int("THUMBNAIL_QUALITY", 80),
            notify_topic_arn=os.environ.get("NOTIFY_TOPIC_ARN", ""),
            local_md_model_path=os.environ.get("LOCAL_MD_MODEL_PATH", ""),
            local_species_model_path=os.environ.get("LOCAL_SPECIES_MODEL_PATH", ""),
            local_labels_path=os.environ.get("LOCAL_LABELS_PATH", ""),
        )

    def model_keys(self) -> tuple[str, str, str]:
        base = f"{self.model_prefix.strip('/')}/{self.model_version}"
        return (
            f"{base}/{self.md_model_name}",
            f"{base}/{self.species_model_name}",
            f"{base}/{self.labels_name}",
        )
