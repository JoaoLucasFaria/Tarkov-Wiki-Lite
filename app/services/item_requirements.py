
"""Extract item requirements from Tarkov quest objectives."""

import re
from collections import defaultdict


ITEM_ID_PATTERN = re.compile(r"^[0-9a-fA-F]{24}$")

DIRECT_ITEM_TYPES = {
    "giveItem",
    "findItem",
    "plantItem",
}


def valid_item_ids(values: object) -> list[str]:
    """Return valid, unique Tarkov item IDs."""

    if not isinstance(values, list):
        return []

    result = []
    seen = set()

    for value in values:
        if not isinstance(value, str):
            continue

        item_id = value.lower()

        if not ITEM_ID_PATTERN.fullmatch(item_id):
            continue

        if item_id in seen:
            continue

        seen.add(item_id)
        result.append(item_id)

    return result


def extract_item_requirements(
    tasks: list[dict],
) -> list[dict]:
    """Extract raw item-related requirements from quest data.

    This function does not calculate final item totals.
    Objectives that refer to the same items remain separate.
    """

    requirements = []

    for task in tasks:
        if not isinstance(task, dict):
            continue

        quest_id = str(task.get("id") or "")
        quest_name = str(task.get("name") or quest_id)

        for objective in task.get("objectives") or []:
            if not isinstance(objective, dict):
                continue

            objective_type = objective.get("type")

            if objective_type in DIRECT_ITEM_TYPES:
                item_ids = valid_item_ids(
                    objective.get("items")
                )

                selection = ("one_of" if len(item_ids) > 1 else "direct")

            elif objective_type == "mark":
                marker = objective.get("markerItem")

                item_ids = valid_item_ids(
                    [marker] if marker else []
                )

                selection = "marker"

            elif objective_type == "useItem":
                item_ids = valid_item_ids(
                    objective.get("useAny")
                )

                selection = "one_of"

            else:
                continue

            if not item_ids:
                continue

            count = objective.get("count", 1)

            if type(count) is not int or count < 1:
                count = 1

            requirements.append({
                "quest_id": quest_id,
                "quest_name": quest_name,
                "objective_id": str(
                    objective.get("id") or ""
                ),
                "description": str(
                    objective.get("description") or ""
                ),
                "objective_type": objective_type,
                "item_ids": item_ids,
                "count": count,
                "optional": bool(
                    objective.get("optional", False)
                ),
                "found_in_raid": bool(
                    objective.get("foundInRaid", False)
                ),
                "selection": selection,
            })

    return requirements


def index_requirements_by_item(
    requirements: list[dict],
) -> dict[str, list[dict]]:
    """Index raw quest requirements by item ID."""

    index = defaultdict(list)

    for requirement in requirements:
        for item_id in requirement["item_ids"]:
            index[item_id].append(requirement)

    return dict(index)
