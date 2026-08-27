from pathlib import Path

import pytest

from backend.processing_pipeline.labels import load_labels


def test_load_labels(tmp_path: Path) -> None:
    labels_file = tmp_path / "labels.txt"
    labels_file.write_text(
        "id;mammalia;carnivora;felidae;felis;catus;domestic cat\n",
        encoding="utf-8",
    )
    labels = load_labels(labels_file)
    assert len(labels) == 1
    assert labels[0].scientific_name == "Felis_catus"
    assert labels[0].common_name == "domestic cat"


def test_rejects_invalid_label_row(tmp_path: Path) -> None:
    labels_file = tmp_path / "labels.txt"
    labels_file.write_text("not;enough;fields\n", encoding="utf-8")
    with pytest.raises(ValueError, match="expected 7 fields"):
        load_labels(labels_file)

