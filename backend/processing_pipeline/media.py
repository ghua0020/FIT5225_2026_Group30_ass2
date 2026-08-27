"""Image thumbnail and one-frame-per-second video utilities."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageOps


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


def detect_media_type(key: str, content_type: str = "") -> str:
    normalised_type = (content_type or "").lower()
    if normalised_type.startswith("image/"):
        return "image"
    if normalised_type.startswith("video/"):
        return "video"
    suffix = Path(key).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in VIDEO_SUFFIXES:
        return "video"
    raise ValueError(f"Unsupported media type for {key!r} ({content_type or 'unknown'})")


def create_thumbnail(
    source_path: str | Path,
    output_path: str | Path,
    max_size: int = 480,
    quality: int = 80,
) -> tuple[int, int]:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        size = image.size
        image.save(output, format="JPEG", quality=quality, optimize=True)
    return size


def extract_video_frames(
    video_path: str | Path, output_dir: str | Path
) -> list[Path]:
    """Extract one decoded frame at each whole second, starting at second zero."""
    import cv2

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError(f"Unable to open video: {video_path}")

    fps = float(capture.get(cv2.CAP_PROP_FPS))
    if not math.isfinite(fps) or fps <= 0:
        capture.release()
        raise ValueError(f"Video reports an invalid frame rate: {fps}")

    frames: list[Path] = []
    frame_index = 0
    next_sample_second = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            timestamp = frame_index / fps
            if timestamp + (0.5 / fps) >= next_sample_second:
                frame_path = output / f"frame-{next_sample_second:06d}.jpg"
                if not cv2.imwrite(str(frame_path), frame):
                    raise RuntimeError(f"Failed to write extracted frame: {frame_path}")
                frames.append(frame_path)
                next_sample_second += 1
            frame_index += 1
    finally:
        capture.release()
    if not frames:
        raise ValueError(f"No frames could be extracted from video: {video_path}")
    return frames

