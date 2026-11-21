"""Offline regression tests for Crafts & Barters. Run: python -m tools.test_item_recipes"""
import json
import tempfile
from pathlib import Path

from app.services.item_recipe_catalog import (
    ItemRecipeCatalog,
    _read_cache,
    build_recipe_index,
    parse_recipes,
)

A = "590a3efd86f77437d351a25b"  # Gas analyzer
B = "5d1b376e86f774252519444e"
C = "5991b51486f77447b112d44f"


class FakeApi:
    def __init__(self):
        self.requests = []
        self.responses = []

    def get_json(self, url, callback):
        self.requests.append((url, callback))

    def respond(self, index, payload, error=None):
        self.requests[index][1](payload, error)


rest_crafts = {"data": [{
    "id": "craft-a", "station": {"name": "Workbench"}, "level": 2,
    "duration": 3600,
    "requiredItems": [
        {"item": {"id": B, "name": "Moonshine"}, "count": 2},
        {"item": {"id": C, "name": "Marker"}, "count": 0.42, "isTool": True},
    ],
    "rewardItems": [{"item": {"id": A, "name": "Gas analyzer"}, "count": 1}],
}]}
rest_barters = {"data": [{
    "id": "barter-a", "trader": {"name": "Therapist"}, "level": 3,
    "taskUnlock": {"id": "quest-1"},
    "requiredItems": [{"item": B, "quantity": 4}],
    "rewardItems": [{"item": A, "quantity": 2}],
}]}

craft = parse_recipes(rest_crafts, "crafts")
assert len(craft) == 1
assert craft[0]["source"] == "Workbench"
assert craft[0]["duration"] == 3600
assert craft[0]["required"][1]["count"] == 0.42
assert craft[0]["required"][1]["reusable"]
index = build_recipe_index(craft)
assert index[A]["for"] == [0]
assert index[B]["using"] == [0]
print("PASS: REST crafts, output/ingredients, station and reusable tools")

barter = parse_recipes(rest_barters, "barters")
assert barter[0]["level"] == 3
assert barter[0]["unlock"]
print("PASS: REST barters, trader loyalty and quest unlock")

mirror = {"data": {"crafts": {
    "craft-x": {
        "station": "Workbench", "stationLevel": 1,
        "requiredItems": {B: 2},
        "rewardItems": [{"itemId": A, "amount": 3}],
    }
}}}
parsed = parse_recipes(mirror, "crafts")
assert parsed[0]["required"][0]["count"] == 2
assert parsed[0]["rewards"][0]["count"] == 3
print("PASS: V2 mirror ID-keyed responses and ingredient dictionaries")

# The live v2 mirror (Nov 2026) uses productItem/offeredItem instead
# of rewardItems. These tests would fail with the original parser.
v2_crafts = {"data": [{
    "id": "v2-craft", "station": "Workbench", "level": 2,
    "duration": 5400, "gameEditions": [], "requiredQuestItems": [],
    "requiredItems": [{"item": B, "count": 2}],
    "productItem": {"item": A, "count": 3},
}]}
v2_barters = {"data": [{
    "id": "v2-barter", "trader": "Mechanic", "minTraderLevel": 3,
    "taskUnlock": None, "restockAmount": 1, "buyLimit": 2,
    "requiredItems": [{"item": C, "count": 5}],
    "offeredItem": {"item": A, "count": 1},
}]}
parsed_crafts = parse_recipes(v2_crafts, "crafts")
parsed_barters = parse_recipes(v2_barters, "barters")
assert len(parsed_crafts) == 1 and parsed_crafts[0]["rewards"][0]["id"] == A
assert parsed_crafts[0]["rewards"][0]["count"] == 3
assert parsed_barters[0]["rewards"][0]["id"] == A
assert parsed_barters[0]["level"] == 3
assert build_recipe_index(parsed_crafts)[A]["for"] == [0]
print("PASS: real v2 field layout (productItem/offeredItem)")

# String item IDs must not receive a fabricated quantity.
v2_string_craft = {"data": [{
    "id": "v2-string", "station": "Lavatory",
    "requiredItems": [{"item": B, "count": 1}],
    "productItem": A,
}]}
assert parse_recipes(v2_string_craft, "crafts")[0]["rewards"][0]["count"] is None
print("PASS: unknown v2 reward quantity stays unknown")

with tempfile.TemporaryDirectory() as folder:
    api = FakeApi()
    directory = Path(folder)
    catalog = ItemRecipeCatalog(api, directory)
    updates = []
    catalog.ensure("regular", lambda: updates.append("regular"))
    assert len(api.requests) == 2
    assert "/api/v2/regular/crafts" in api.requests[0][0]
    assert "game=eft" in api.requests[1][0]
    api.respond(0, rest_crafts)
    api.respond(1, rest_barters)
    assert catalog.status("regular", "crafts") == "ready"
    assert catalog.recipes_for("regular", "crafts", A, "for")
    assert catalog.recipes_for("regular", "barters", B, "using")
    assert updates
    assert directory.joinpath("item_crafts_regular.json").is_file()
    assert directory.joinpath("item_barters_regular.json").is_file()

    initial_calls = len(api.requests)
    catalog.ensure("regular", lambda: None)
    assert len(api.requests) == initial_calls, "Valid cache re-downloaded"

    # PvE must use a separate endpoint and independent cache.
    catalog.ensure("pve", lambda: None)
    assert len(api.requests) == 4
    assert "game=pve" in api.requests[3][0]
    api.respond(2, v2_crafts)
    api.respond(3, {"data": [{
        "trader": {"name": "Prapor"},
        "requiredItems": [{"item": B, "count": 3}],
        "rewardItems": [{"item": C, "count": 1}],
    }]})
    assert catalog.recipes_for("regular", "barters", A, "for")
    assert not catalog.recipes_for("pve", "barters", A, "for")

    offline = ItemRecipeCatalog(FakeApi(), directory)
    assert offline.recipes_for("regular", "crafts", A, "for")
    assert offline.recipes_for("pve", "barters", C, "for")
    print("PASS: cache, lazy requests, offline startup and PvP/PvE isolation")

    # Invalid REST payload triggers documented v2 fallback.
    failure_api = FakeApi()
    failure_cat = ItemRecipeCatalog(failure_api, directory / "other")
    failure_cat.ensure("regular", lambda: None)
    failure_api.respond(0, {"data": [{"id": "unexpected"}]})
    assert len(failure_api.requests) == 3
    assert "/api/crafts?" in failure_api.requests[2][0]
    failure_api.respond(2, rest_crafts)
    assert failure_cat.status("regular", "crafts") == "ready"
    failure_api.respond(1, None, "network unavailable")
    assert len(failure_api.requests) == 4
    failure_api.respond(3, None, "still unavailable")
    assert failure_cat.status("regular", "barters") == "error"
    # PvE crafts never fall back to the global REST craft list.
    pve_failure = FakeApi()
    pve_catalog = ItemRecipeCatalog(pve_failure, directory / "otherpve")
    pve_catalog.ensure("pve", lambda: None)
    pve_failure.respond(0, None, "v2 unavailable")
    assert len(pve_failure.requests) == 2
    assert pve_catalog.status("pve", "crafts") == "error"
    print("PASS: safe fallbacks and honest errors on failure")

print("All Crafts & Barters tests passed!")
