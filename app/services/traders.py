
"""Trader identification and display names."""

# Trader IDs mapped to their display names
TRADER_NAMES = {
    "54cb50c76803fa8b248b4571": "Prapor",
    "54cb57776803fa99248b456e": "Therapist",
    "579dc571d53a0658a154fbec": "Fence",
    "58330581ace78e27b8b10cee": "Skier",
    "5935c25fb3acc3127c3d8cd9": "Peacekeeper",
    "5a7c2eca46aef81a7ca2145d": "Mechanic",
    "5ac3b934156ae10c4430e83c": "Ragman",
    "5c0647fdd443bc2504c2d371": "Jaeger",
    "638f541a29ffd1183d187f57": "Lightkeeper",
    "6617beeaa9cfa777ca915b7c": "Ref",
    "656f0f98d80a697f855d34b1": "BTR Driver",
    "6864e812f9fe664cb8b8e152": "Storyteller",
}


def get_trader_name(trader: object) -> str:
    """Return the display name associated with a trader."""

    if isinstance(trader, dict):
        trader_id = str(
            trader.get("id") or trader.get("name") or ""
        )
    elif trader is None:
        trader_id = ""
    else:
        trader_id = str(trader)

    return TRADER_NAMES.get(
        trader_id,
        trader_id or "Unknown trader"
    )
