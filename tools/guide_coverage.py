
"""Generate a prioritized visual guide coverage report."""

import csv
import json
import sys
from collections import Counter
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT_DIR / "cache"

sys.path.insert(0, str(ROOT_DIR))

from app.models.guide_catalog import get_quest_guide
from app.models.quest import name_of


HIGH_PRIORITY_TYPES = {
    "visit",
    "plantItem",
    "findQuestItem",
    "mark",
    "plantQuestItem",
    "useItem",
}

MEDIUM_PRIORITY_TYPES = {
    "shoot",
    "extract",
    "buildWeapon",
    "globalVariable",
    "dialogue",
}

LOW_PRIORITY_TYPES = {
    "giveItem",
    "findItem",
    "giveQuestItem",
    "taskStatus",
    "traderLevel",
    "skill",
    "sellItem",
    "experience",
    "traderStanding",
}

KNOWN_TYPES = (
    HIGH_PRIORITY_TYPES
    | MEDIUM_PRIORITY_TYPES
    | LOW_PRIORITY_TYPES
)

PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}


def load_tasks(mode: str) -> list[dict]:
    """Read locally cached quest data."""

    path = CACHE_DIR / f"tasks_{mode}.json"

    if not path.exists():
        print(f"Missing cache: {path.name}")
        return []

    try:
        tasks = json.loads(path.read_text(encoding="utf-8"))

        if not isinstance(tasks, list):
            raise ValueError("Expected a list of quests.")

        return [task for task in tasks if isinstance(task, dict)]

    except (OSError, ValueError) as error:
        print(f"Cannot read {path.name}: {error}")
        return []


def classify_priority(objective_types: set[str]) -> str:
    """Suggest a review priority based on quest objective types."""

    if objective_types & HIGH_PRIORITY_TYPES:
        return "High"

    if objective_types & MEDIUM_PRIORITY_TYPES:
        return "Medium"

    if objective_types - KNOWN_TYPES:
        return "Medium"

    return "Low"


def build_inventory() -> dict:
    """Combine PvP and PvE quests by their unique IDs."""

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
                    "id": quest_id,
                    "name": name_of(task.get("name")) or quest_id,
                    "modes": set(),
                    "types": set(),
                    "objective_keys": set(),
                    "location_objectives": 0,
                    "wiki_link": "",
                    "task_image_link": "",
                }

            quest = quests[quest_id]
            quest["modes"].add(mode)

            for source_field, target_field in (
                ("wikiLink", "wiki_link"),
                ("taskImageLink", "task_image_link"),
            ):
                value = task.get(source_field)

                if isinstance(value, str) and value:
                    quest[target_field] = value

            for objective in task.get("objectives") or []:
                if not isinstance(objective, dict):
                    continue

                objective_type = str(
                    objective.get("type") or "unknown"
                )

                quest["types"].add(objective_type)

                objective_key = (
                    str(
                        objective.get("id")
                        or objective.get("description")
                        or ""
                    ),
                    objective_type,
                )

                if objective_key in quest["objective_keys"]:
                    continue

                quest["objective_keys"].add(objective_key)

                if (
                    objective.get("zones")
                    or objective.get("possibleLocations")
                ):
                    quest["location_objectives"] += 1

    return quests


def main() -> None:
    """Create the prioritized coverage CSV."""

    quests = build_inventory()

    if not quests:
        print("No quests found in local cache.")
        return

    rows = []
    unknown_types = set()

    for quest in quests.values():
        types = quest["types"]
        unknown_types.update(types - KNOWN_TYPES)

        images = get_quest_guide({"id": quest["id"]})

        rows.append({
            "quest_id": quest["id"],
            "name": quest["name"],
            "modes": ", ".join(sorted(quest["modes"])),
            "priority": classify_priority(types),
            "status": (
                "Has guide images" if images else "Needs review"
            ),
            "image_count": len(images),
            "objective_types": ", ".join(sorted(types)),
            "location_objectives": quest["location_objectives"],
            "wiki_link": quest["wiki_link"],
            "task_image_link": quest["task_image_link"],
        })

    rows.sort(key=lambda row: (
        row["status"] != "Needs review",
        PRIORITY_ORDER[row["priority"]],
        row["name"].casefold(),
    ))

    output_path = CACHE_DIR / "guide_coverage.csv"

    with output_path.open(
        "w", newline="", encoding="utf-8-sig"
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "quest_id",
                "name",
                "modes",
                "priority",
                "status",
                "image_count",
                "objective_types",
                "location_objectives",
                "wiki_link",
                "task_image_link",
            ],
        )

        writer.writeheader()
        writer.writerows(rows)

    priorities = Counter(row["priority"] for row in rows)

    print("\n=== GUIDE COVERAGE ===")
    print(f"Unique quests: {len(rows)}")
    print(f"Guides with images: {sum(row['image_count'] > 0 for row in rows)}")
    print(f"Registered images: {sum(row['image_count'] for row in rows)}")

    print("\n=== REVIEW PRIORITIES ===")

    for priority in ("High", "Medium", "Low"):
        print(f"{priority}: {priorities[priority]} quests")

    print("\n=== FIRST 10 QUESTS TO REVIEW ===")

    for row in rows[:10]:
        print(
            f"[{row['priority']}] {row['name']} "
            f"({row['location_objectives']} location objectives)"
        )

    if unknown_types:
        print("\nUnrecognized objective types:")
        print(", ".join(sorted(unknown_types)))

    print(f"\nReport saved: {output_path}")


if __name__ == "__main__":
    main()
