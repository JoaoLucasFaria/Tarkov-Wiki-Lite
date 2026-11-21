
"""Consolidate quest item requirements without double counting."""

from collections import defaultdict


RESOURCE_TYPES = {
    "giveItem",
    "plantItem",
    "useItem",
    "mark",
}


def summarize_quest_requirements(
    requirements: list[dict],
) -> list[dict]:
    """Summarize requirements for each quest and item group.

    A matching findItem and giveItem pair is not counted twice.
    Alternative item IDs remain grouped as one requirement.
    """

    grouped = defaultdict(list)

    for requirement in requirements:
        item_ids = tuple(sorted(requirement["item_ids"]))

        key = (
            requirement["quest_id"],
            item_ids,
        )

        grouped[key].append(requirement)

    summaries = []

    for (quest_id, item_ids), objectives in grouped.items():
        required_actions = [
            obj
            for obj in objectives
            if obj["objective_type"] in RESOURCE_TYPES
            and not obj["optional"]
        ]

        required_find = [
            obj["count"]
            for obj in objectives
            if obj["objective_type"] == "findItem"
            and not obj["optional"]
        ]

        optional_actions = [
            obj
            for obj in objectives
            if obj["objective_type"] in RESOURCE_TYPES
            and obj["optional"]
        ]


        # An optional findItem objective may simply describe
        # the acquisition stage of a mandatory handover.
        has_required_handover = any(
            obj["objective_type"] == "giveItem"
            and not obj["optional"]
            for obj in objectives
        )
        
        optional_find = (
            []
            if has_required_handover
            else [
                obj["count"]
                for obj in objectives
                if obj["objective_type"] == "findItem"
                and obj["optional"]
            ]
        )
        

        action_count = sum(
            obj["count"] for obj in required_actions
        )

        find_count = max(required_find, default=0)

        # Finding items and handing them over may be
        # two stages of the same requirement.
        required_count = max(action_count, find_count)

        # Optional objectives are never added to mandatory totals.
        optional_count = max(
            sum(obj["count"] for obj in optional_actions),
            max(optional_find, default=0),
        )

        required_objectives = [
            obj for obj in objectives
            if not obj["optional"]
        ]

        summaries.append({
            "quest_id": quest_id,
            "quest_name": objectives[0]["quest_name"],
            "item_ids": list(item_ids),
            "selection": (
                "one_of" if len(item_ids) > 1 else "direct"
            ),
            "required_count": required_count,
            "optional_count": optional_count,
            "found_in_raid": any(
                obj["found_in_raid"]
                for obj in required_objectives
            ),
            "objective_types": sorted({
                obj["objective_type"]
                for obj in objectives
            }),
            "objective_ids": [
                obj["objective_id"]
                for obj in objectives
            ],
        })

    return sorted(
        summaries,
        key=lambda item: (
            item["quest_name"].casefold(),
            item["item_ids"],
        ),
    )


def get_item_requirements(
    item_id: str,
    summaries: list[dict],
) -> dict:
    """Separate exact item needs from alternative choices."""

    direct = []
    alternatives = []

    for summary in summaries:
        if item_id not in summary["item_ids"]:
            continue

        if summary["selection"] == "direct":
            direct.append(summary)
        else:
            alternatives.append(summary)

    return {
        "item_id": item_id,
        "required_total": sum(
            entry["required_count"] for entry in direct
        ),
        "direct_requirements": direct,
        "alternative_requirements": alternatives,
    }
