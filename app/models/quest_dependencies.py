"""Quest prerequisite and dependency relationships."""

def get_quest_id(value: object) -> str:
    """Extract a quest ID from a string or object."""
    if isinstance(value, dict):
        value = value.get("id")

    return value if isinstance(value, str) else ""


def get_task_requirements(
    task: dict
) -> list[tuple[str, list[str]]]:
    """Return required quest IDs and their accepted states."""

    requirements = task.get("taskRequirements") or []

    if not isinstance(requirements, list):
        return []

    result = []

    for entry in requirements:
        if not isinstance(entry, dict):
            continue

        quest_id = get_quest_id(entry.get("task"))

        if not quest_id:
            continue

        statuses = entry.get("status") or []

        if isinstance(statuses, str):
            statuses = [statuses]

        if not isinstance(statuses, list):
            statuses = []

        statuses = [
            status.lower()
            for status in statuses
            if isinstance(status, str)
        ]

        result.append((quest_id, statuses))

    return result


def build_reverse_requirements(
    tasks: list[dict]
) -> dict[str, list[tuple[dict, list[str]]]]:
    """Find quests that reference each quest as a requirement."""

    reverse = {}

    for task in tasks:
        if not isinstance(task, dict):
            continue

        for required_id, statuses in get_task_requirements(task):
            reverse.setdefault(required_id, []).append(
                (task, statuses)
            )

    return reverse
