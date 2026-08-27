"""MegaDetector and SpeciesNet loading/inference."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import threading
from typing import Any

from PIL import Image, ImageOps

from .config import Settings
from .labels import SpeciesLabel, load_labels


class ModelBundle:
    """Loaded detector/classifier pair reused for every warm invocation."""

    def __init__(
        self,
        detector: Any,
        classifier: Any,
        labels: list[SpeciesLabel],
        transform: Any,
        torch_module: Any,
        device: str,
        detector_confidence: float,
        classifier_confidence: float,
        model_version: str,
    ) -> None:
        self.detector = detector
        self.classifier = classifier
        self.labels = labels
        self.transform = transform
        self.torch = torch_module
        self.device = device
        self.detector_confidence = detector_confidence
        self.classifier_confidence = classifier_confidence
        self.model_version = model_version

    @classmethod
    def load(
        cls,
        md_model_path: str | Path,
        species_model_path: str | Path,
        labels_path: str | Path,
        settings: Settings,
        device: str | None = None,
    ) -> "ModelBundle":
        import torch
        import torchvision.transforms as transforms
        from megadetector.detection import run_detector

        if device is None:
            if torch.cuda.is_available():
                device = "cuda"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device = "mps"
            else:
                device = "cpu"

        detector = run_detector.load_detector(
            str(md_model_path), force_cpu=(device == "cpu"), verbose=False
        )
        classifier = torch.load(
            str(species_model_path), map_location=device, weights_only=False
        )
        classifier.eval()
        classifier.to(device)

        transform = transforms.Compose(
            [transforms.Resize((480, 480)), transforms.ToTensor()]
        )
        return cls(
            detector=detector,
            classifier=classifier,
            labels=load_labels(labels_path),
            transform=transform,
            torch_module=torch,
            device=device,
            detector_confidence=settings.detector_confidence,
            classifier_confidence=settings.classifier_confidence,
            model_version=settings.model_version,
        )

    def classify_crop(self, crop: Image.Image) -> dict:
        tensor = self.transform(crop.convert("RGB"))
        tensor = tensor.unsqueeze(0).permute(0, 2, 3, 1).to(self.device)
        with self.torch.no_grad():
            logits = self.classifier(tensor)
            if logits.shape[-1] != len(self.labels):
                raise ValueError(
                    f"Classifier returned {logits.shape[-1]} classes, "
                    f"but labels.txt contains {len(self.labels)} labels"
                )
            probabilities = self.torch.softmax(logits, dim=1)[0]
            confidence, index_tensor = self.torch.max(probabilities, dim=0)
        index = int(index_tensor.item())
        if index >= len(self.labels):
            raise ValueError(
                f"Classifier returned label index {index}, but only {len(self.labels)} labels exist"
            )
        label = self.labels[index]
        return {
            "name": label.scientific_name,
            "common_name": label.common_name,
            "confidence": float(confidence.item()),
            "label_index": index,
        }

    def predict_file(self, image_path: str | Path) -> dict:
        with Image.open(image_path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
        detection_result = self.detector.generate_detections_one_image(
            image,
            image_id=str(image_path),
            detection_threshold=self.detector_confidence,
        )
        if detection_result.get("failure"):
            raise RuntimeError(f"MegaDetector failed: {detection_result['failure']}")

        width, height = image.size
        predictions: list[dict] = []
        for detection in detection_result.get("detections", []):
            if str(detection.get("category")) != "1":
                continue
            detector_confidence = float(detection.get("conf", 0.0))
            if detector_confidence < self.detector_confidence:
                continue
            x, y, box_width, box_height = detection["bbox"]
            left = max(0, min(width, int(x * width)))
            top = max(0, min(height, int(y * height)))
            right = max(0, min(width, int((x + box_width) * width)))
            bottom = max(0, min(height, int((y + box_height) * height)))
            if right <= left or bottom <= top:
                continue
            prediction = self.classify_crop(image.crop((left, top, right, bottom)))
            if prediction["confidence"] < self.classifier_confidence:
                continue
            prediction["detector_confidence"] = detector_confidence
            prediction["bbox"] = [float(x), float(y), float(box_width), float(box_height)]
            predictions.append(prediction)

        grouped: dict[str, dict] = defaultdict(
            lambda: {"count": 0, "confidence": 0.0, "common_name": ""}
        )
        for prediction in predictions:
            group = grouped[prediction["name"]]
            group["count"] += 1
            group["confidence"] = max(group["confidence"], prediction["confidence"])
            group["common_name"] = prediction["common_name"]

        tags = [
            {
                "name": name,
                "common_name": values["common_name"],
                "count": values["count"],
                "confidence": values["confidence"],
            }
            for name, values in sorted(grouped.items())
        ]
        return {
            "model_version": self.model_version,
            "detection_count": len(predictions),
            "tags": tags,
            "detections": predictions,
        }


class ModelProvider:
    """Resolves versioned models from local paths or S3 and caches the loaded bundle."""

    _lock = threading.Lock()
    _bundle: ModelBundle | None = None
    _bundle_key: tuple[str, str, str, str] | None = None

    def __init__(self, s3_client: Any, settings: Settings) -> None:
        self.s3 = s3_client
        self.settings = settings

    def _download_if_missing(self, bucket: str, key: str, destination: Path) -> None:
        if destination.is_file() and destination.stat().st_size > 0:
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.s3.download_file(bucket, key, str(destination))

    def _resolve_paths(self, event_bucket: str) -> tuple[Path, Path, Path]:
        local = (
            self.settings.local_md_model_path,
            self.settings.local_species_model_path,
            self.settings.local_labels_path,
        )
        if all(local):
            paths = tuple(Path(value) for value in local)
            for path in paths:
                if not path.is_file():
                    raise FileNotFoundError(f"Configured model file does not exist: {path}")
            return paths  # type: ignore[return-value]
        if any(local):
            raise ValueError("All three LOCAL_* model paths must be configured together")

        bucket = self.settings.model_bucket or event_bucket
        md_key, species_key, labels_key = self.settings.model_keys()
        cache_root = Path(self.settings.model_cache_dir) / self.settings.model_version
        paths = (
            cache_root / self.settings.md_model_name,
            cache_root / self.settings.species_model_name,
            cache_root / self.settings.labels_name,
        )
        for key, destination in zip((md_key, species_key, labels_key), paths):
            self._download_if_missing(bucket, key, destination)
        return paths

    def get_bundle(self, event_bucket: str) -> ModelBundle:
        paths = self._resolve_paths(event_bucket)
        key = tuple(str(path.resolve()) for path in paths) + (self.settings.model_version,)
        with self._lock:
            if self.__class__._bundle is None or self.__class__._bundle_key != key:
                self.__class__._bundle = ModelBundle.load(
                    paths[0], paths[1], paths[2], self.settings
                )
                self.__class__._bundle_key = key
            return self.__class__._bundle
