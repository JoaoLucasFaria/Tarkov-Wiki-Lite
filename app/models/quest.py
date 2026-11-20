
"""Quest data processing and localization."""

def extract_tasks(payload: object) -> list[dict]:
    """Extract quests from an API response."""

    if not isinstance(payload, dict):
        raise ValueError("Unexpected API response format.")

    root = payload.get("data", payload)

    if isinstance(root, dict):
        raw = root.get("tasks", root.get("task", []))
    else:
        raw = root

    if isinstance(raw, dict):
        raw = list(raw.values())

    if not isinstance(raw, list):
        raise ValueError("Could not find the quest list.")

    tasks = [
        obj for obj in raw
        if isinstance(obj, dict) and obj.get("name")
    ]

    if not tasks:
        raise ValueError("The API returned an empty quest list.")

    return tasks


def extract_translations(payload: object) -> dict[str, str]:
    """Extract English localization strings."""

    if not isinstance(payload, dict):
        return {}

    root = payload.get("data", payload)

    if (
        isinstance(root, dict)
        and isinstance(root.get("translations"), dict)
    ):
        root = root["translations"]

    if not isinstance(root, dict):
        return {}

    return {
        str(key): value
        for key, value in root.items()
        if isinstance(value, str)
    }


def localize(
    value: object,
    translations: dict[str, str]
) -> object:
    """Replace localization keys with English text."""

    if isinstance(value, str):
        return translations.get(value, value)

    if isinstance(value, list):
        return [
            localize(entry, translations)
            for entry in value
        ]

    if isinstance(value, dict):
        return {
            key: localize(entry, translations)
            for key, entry in value.items()
        }

    return value


def name_of(value: object) -> str:
    """Return the display name of an object."""

    if isinstance(value, dict):
        value = value.get("name", "")

    return str(value) if value is not None else ""
