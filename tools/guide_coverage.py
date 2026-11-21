
"""Generate a coverage report for curated quest guides."""

import csv
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT_DIR / "cache"

sys.path.insert(0, str(ROOT_DIR))

from app.models.guide_catalog import get_quest_guide
from app.models.quest import name_of


def load_tasks(mode: str) -> list[dict]:
    """Read quests from the existing local cache."""

    path = CACHE_DIR / f"tasks_{mode}.json"

    if not path.is_file():
        print(f"Cache not found: {path.name}")
        return []

    try:
        tasks = json.loads(path.read_text(encoding="utf-8"))

        if not isinstance(tasks, list):
            raise ValueError("Expected a list of quests.")

        return [task for task in tasks if isinstance(task, dict)]

    except (OSError, ValueError) as error:
        print(f"Cannot read {path.name}: {error}")
        return []


def main() -> None:
    """Build a unique quest inventory across both game modes."""

    quests = {}

    for mode in ("regular", "pve"):
        tasks = load_tasks(mode)
        print(f"{mode.upper()}: {len(tasks)} quests loaded")

        for task in tasks:
            quest_id = str(task.get("id") or "")

            if not quest_id:
                continue

            if quest_id not in quests:
                quests[quest_id] = {
                    "quest_id": quest_id,
                    "name": name_of(task.get("name")),
                    "modes": set(),
                }

            quests[quest_id]["modes"].add(mode)

    if not quests:
        print("No cached quests available. Open the Quests page first.")
        return

    rows = []

    for quest in quests.values():
        images = get_quest_guide({"id": quest["quest_id"]})
        has_guide = bool(images)

        rows.append({
            "quest_id": quest["quest_id"],
            "name": quest["name"],
            "modes": ", ".join(sorted(quest["modes"])),
            "image_count": len(images),
            "status": "Guide available" if has_guide else "Needs review",
        })

    rows.sort(key=lambda row: row["name"].casefold())

    output_path = CACHE_DIR / "guide_coverage.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open(
        "w", newline="", encoding="utf-8-sig"
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "quest_id",
                "name",
                "modes",
                "image_count",
                "status",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    available = sum(
        row["status"] == "Guide available" for row in rows
    )

    print()
    print("=== GUIDE COVERAGE ===")
    print(f"Unique quests: {len(rows)}")
    print(f"Guides available: {available}")
    print(f"Needs review: {len(rows) - available}")
    print(f"Registered images: {sum(row['image_count'] for row in rows)}")
    print(f"Report saved: {output_path}")


if __name__ == "__main__":
    main()
