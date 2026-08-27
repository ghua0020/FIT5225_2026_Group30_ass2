"""Species label parsing and model-index mapping."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class SpeciesLabel:
    index: int
    taxon_id: str
    class_name: str
    order: str
    family: str
    genus: str
    species: str
    common_name: str

    @property
    def scientific_name(self) -> str:
        genus = self.genus[:1].upper() + self.genus[1:]
        return f"{genus}_{self.species}" if self.species else genus

    def to_dict(self) -> dict:
        value = asdict(self)
        value["scientific_name"] = self.scientific_name
        return value


def load_labels(path: str | Path) -> list[SpeciesLabel]:
    labels: list[SpeciesLabel] = []
    for line_number, raw_line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split(";")]
        if len(parts) != 7:
            raise ValueError(
                f"Invalid labels row {line_number}: expected 7 fields, got {len(parts)}"
            )
        labels.append(
            SpeciesLabel(
                index=len(labels),
                taxon_id=parts[0],
                class_name=parts[1],
                order=parts[2],
                family=parts[3],
                genus=parts[4],
                species=parts[5],
                common_name=parts[6],
            )
        )
    if not labels:
        raise ValueError("No species labels were loaded")
    return labels

