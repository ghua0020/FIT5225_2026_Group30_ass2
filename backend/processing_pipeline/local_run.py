"""Run the refactored image pipeline locally with the supplied models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import Settings
from .media import create_thumbnail
from .models import ModelBundle


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Pacific BioArchive image inference")
    parser.add_argument("image")
    parser.add_argument("--md-model", required=True)
    parser.add_argument("--species-model", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--model-version", default="v1")
    parser.add_argument("--thumbnail")
    parser.add_argument("--output")
    args = parser.parse_args()

    settings = Settings(model_version=args.model_version)
    bundle = ModelBundle.load(
        args.md_model, args.species_model, args.labels, settings
    )
    result = bundle.predict_file(args.image)
    if args.thumbnail:
        width, height = create_thumbnail(args.image, args.thumbnail)
        result["thumbnail"] = {
            "path": str(Path(args.thumbnail)),
            "width": width,
            "height": height,
        }
    output = json.dumps(result, indent=2)
    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()

