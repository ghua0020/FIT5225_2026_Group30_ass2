from pathlib import Path

from PIL import Image
import cv2
import numpy as np
import pytest

from backend.processing_pipeline.media import (
    create_thumbnail,
    detect_media_type,
    extract_video_frames,
)


def test_thumbnail_preserves_aspect_ratio(tmp_path: Path) -> None:
    source = tmp_path / "wide.png"
    output = tmp_path / "thumbnail.jpg"
    Image.new("RGB", (1200, 600), "green").save(source)
    assert create_thumbnail(source, output, max_size=480) == (480, 240)
    with Image.open(output) as image:
        assert image.size == (480, 240)


@pytest.mark.parametrize(
    ("key", "content_type", "expected"),
    [
        ("uploads/example.JPG", "", "image"),
        ("uploads/example.bin", "image/jpeg", "image"),
        ("uploads/example.mp4", "", "video"),
    ],
)
def test_detect_media_type(key: str, content_type: str, expected: str) -> None:
    assert detect_media_type(key, content_type) == expected


def test_extracts_one_frame_per_second(tmp_path: Path) -> None:
    video = tmp_path / "sample.avi"
    writer = cv2.VideoWriter(
        str(video), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (64, 48)
    )
    assert writer.isOpened()
    for index in range(25):
        writer.write(np.full((48, 64, 3), index, dtype=np.uint8))
    writer.release()

    frames = extract_video_frames(video, tmp_path / "frames")
    assert [path.name for path in frames] == [
        "frame-000000.jpg",
        "frame-000001.jpg",
        "frame-000002.jpg",
    ]
