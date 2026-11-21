
"""Curated visual guide catalog backed by per-quest JSON files."""

import json
import re
from functools import lru_cache
from pathlib import Path


GUIDES_DIR = Path(__file__).resolve().parents[2] / "guides"


@lru_cache(maxsize=512)
def _read_guide(quest_id: str) -> tuple[dict, ...]:
    """Load metadata only; images are downloaded by GuideImageCache."""

    path = GUIDES_DIR / f"{quest_id}.json"

    if not path.is_file():
        return ()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))

        if not isinstance(data, dict) or data.get("quest_id") != quest_id:
            raise ValueError("Quest ID does not match the filename.")

        images = data.get("images")

        if not isinstance(images, list):
            raise ValueError("The images field must be a list.")

        required_fields = ("title", "description", "url", "source")

        for index, image in enumerate(images, start=1):
            if not isinstance(image, dict) or any(
                not isinstance(image.get(field), str)
                or not image[field].strip()
                for field in required_fields
            ):
                raise ValueError(f"Invalid image entry #{index}.")

        return tuple(images)

    except (OSError, ValueError) as error:
        print(f"Invalid guide '{path.name}': {error}")
        return ()


def get_quest_guide(task: dict) -> list[dict]:
    """Return curated images for the quest, or an empty list."""

    quest_id = str(task.get("id") or "")

    if not re.fullmatch(r"[0-9a-f]{24}", quest_id):
        return []

    return [dict(image) for image in _read_guide(quest_id)]
