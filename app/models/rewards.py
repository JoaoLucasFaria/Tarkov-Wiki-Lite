"""Quest reward formatting and item references."""

import html

from app.services.traders import get_trader_name


def escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def format_quantity(value: object) -> str:
    """Format numeric quantities with thousands separators."""

    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"

    if isinstance(value, float):
        return f"{value:,.0f}" if value.is_integer() else f"{value:,}"

    return escape(value)


def get_reward_item_ids(task: dict) -> set[str]:
    """Find item IDs used by quest completion rewards."""

    rewards = task.get("finishRewards") or {}
    if not isinstance(rewards, dict):
        return set()

    item_ids = set()

    for entry in rewards.get("items") or []:
        if isinstance(entry, dict):
            item_id = entry.get("item")
            if isinstance(item_id, str):
                item_ids.add(item_id)

    for entry in rewards.get("offerUnlock") or []:
        if isinstance(entry, dict):
            item_id = entry.get("item")
            if isinstance(item_id, str):
                item_ids.add(item_id)

    return item_ids


def render_reward_html(
    task: dict,
    item_names: dict[str, str],
) -> str:
    """Build the HTML section for quest completion rewards."""

    parts = ["<h3>Rewards</h3>"]

    xp = task.get("experience")
    if isinstance(xp, (int, float)) and not isinstance(xp, bool):
        parts.append(f"<p><b>Experience:</b> {format_quantity(xp)} XP</p>")

    rewards = task.get("finishRewards") or {}
    if not isinstance(rewards, dict):
        return "".join(parts)

    def item_name(item_id: object) -> str:
        item_id = str(item_id or "")
        name = item_names.get(item_id)

        if name:
            return escape(name)

        return f"Item ID: {escape(item_id)} (name unavailable)"

    # Items and currency
    items = rewards.get("items") or []

    if items:
        parts.append("<h4>Items & Currency</h4><ul>")

        for entry in items:
            if not isinstance(entry, dict):
                continue

            name = item_name(entry.get("item"))
            count = format_quantity(entry.get("count", 1))

            parts.append(
                f"<li>{count}x {name}</li>"
            )

        parts.append("</ul>")

    # Trader reputation
    standing = rewards.get("traderStanding") or []

    if standing:
        parts.append("<h4>Trader Reputation</h4><ul>")

        for entry in standing:
            if not isinstance(entry, dict):
                continue

            trader = escape(get_trader_name(entry.get("trader")))
            value = entry.get("standing")

            if isinstance(value, (int, float)) and not isinstance(value, bool):
                value_text = f"{value:+g}"
            else:
                value_text = escape(value)

            parts.append(
                f"<li>{trader}: {value_text}</li>"
            )

        parts.append("</ul>")

    # Trader offer unlocks
    offers = rewards.get("offerUnlock") or []

    if offers:
        parts.append("<h4>Trader Offer Unlocks</h4><ul>")

        for entry in offers:
            if not isinstance(entry, dict):
                continue

            name = item_name(entry.get("item"))
            trader = escape(get_trader_name(entry.get("trader")))
            level = escape(entry.get("level", "?"))
            count = format_quantity(entry.get("count", 1))

            parts.append(
                f"<li>{count}x {name} - "
                f"{trader} (LL{level})</li>"
            )

        parts.append("</ul>")

    # Skill rewards
    skills = rewards.get("skillLevelReward") or []

    if skills:
        parts.append("<h4>Skill Rewards</h4><ul>")

        for entry in skills:
            if not isinstance(entry, dict):
                continue

            skill = escape(entry.get("skill", "Unknown"))
            level = escape(entry.get("level", "?"))

            parts.append(
                f"<li>{skill} - Level {level}</li>"
            )

        parts.append("</ul>")

    # Categories requiring additional data-specific formatting
    additional = {
        "traderUnlock": "Trader unlocks",
        "craftUnlock": "Craft unlocks",
        "achievement": "Achievements",
        "customization": "Customization",
        "traderDialogueUnlock": "Dialogue unlocks",
        "locationUnlock": "Location unlocks",
    }

    for key, label in additional.items():
        entries = rewards.get(key) or []

        if entries:
            parts.append(
                f"<p><b>{label}:</b> "
                f"{len(entries)} reward entries "
                "(details not yet implemented)</p>"
            )

    return "".join(parts)
