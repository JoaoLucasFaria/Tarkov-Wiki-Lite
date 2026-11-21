
"""Analyze objective types from the local quest cache."""

import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT_DIR / "cache"

LOCATION_FIELDS = (
    "possibleLocations",
    "zones",
    "maps",
    "requiredKeys",
)


def main() -> None:
    """Summarize objective types across unique quests."""

    quests = {}

    for mode in ("regular", "pve"):
        path = CACHE_DIR / f"tasks_{mode}.json"

        if not path.exists():
            print(f"Missing cache: {path.name}")
            continue

        tasks = json.loads(path.read_text(encoding="utf-8"))

        for task in tasks:
            quest_id = task.get("id")

            if quest_id and quest_id not in quests:
                quests[quest_id] = task

    type_counts = Counter()
    quests_by_type = defaultdict(set)
    examples = {}
    location_counts = defaultdict(Counter)

    for quest_id, task in quests.items():
        for objective in task.get("objectives", []):
            objective_type = objective.get("type", "unknown")

            type_counts[objective_type] += 1
            quests_by_type[objective_type].add(quest_id)

            examples.setdefault(
                objective_type,
                objective.get("description", "")
            )

            for field in LOCATION_FIELDS:
                if objective.get(field):
                    location_counts[objective_type][field] += 1

    print(f"\nUnique quests: {len(quests)}")
    print(f"Total objectives: {sum(type_counts.values())}")
    print(f"Objective types: {len(type_counts)}")

    print("\n=== OBJECTIVE TYPE INVENTORY ===")

    for objective_type, count in type_counts.most_common():
        quest_count = len(quests_by_type[objective_type])

        print(f"\n{objective_type}")
        print(f"  Objectives: {count}")
        print(f"  Quests: {quest_count}")
        print(f"  Example: {examples[objective_type]}")

        if location_counts[objective_type]:
            print("  Location metadata:")

            for field, amount in location_counts[
                objective_type
            ].items():
                print(f"    {field}: {amount}")


if __name__ == "__main__":
    main()
