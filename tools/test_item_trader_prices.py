"""Offline smoke test for PvP/PvE trader-only pricing (no network calls)."""

import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from app.services.trader_price_catalog import (
    TraderPriceCatalog,
    load_price_cache,
    parse_trader_prices,
    save_price_cache,
)


ITEM_ID = "590a3efd86f77437d351a25b"
TRADER_A = "54cb57776803fa99248b456e"
TRADER_B = "5a7c2eca46aef81a7ca2145d"


def sample_items(price_a, price_b):
    return {
        "data": {
            "items": {
                ITEM_ID: {
                    "id": ITEM_ID,
                    "basePrice": 99999999,  # must NEVER be used as resale price
                    "sellToTrader": [
                        {"trader": TRADER_A, "priceRUB": price_a},
                        {"trader": TRADER_B, "priceRUB": price_b},
                        {"trader": TRADER_A, "priceRUB": price_a - 100},
                        {"trader": "flea-id", "priceRUB": 88888888},
                        {"trader": TRADER_B, "priceRUB": -50},
                    ],
                },
            }
        }
    }


traders = {
    "data": {
        "traders": {
            TRADER_A: {"normalizedName": "therapist"},
            TRADER_B: {"normalizedName": "mechanic"},
            "flea-id": {"normalizedName": "flea-market"},
        }
    }
}

pvp = parse_trader_prices(sample_items(18_000, 14_000), traders)
pve = parse_trader_prices(sample_items(9_000, 21_000), traders)

assert pvp[ITEM_ID] == [
    {"trader": "Therapist", "price_rub": 18_000},
    {"trader": "Mechanic", "price_rub": 14_000},
]
assert pve[ITEM_ID][0] == {"trader": "Mechanic", "price_rub": 21_000}
assert pvp[ITEM_ID][0]["price_rub"] != 99999999
assert pvp[ITEM_ID][0]["price_rub"] / (1 * 2) == 9000
print("PASS: Trader prices, comparison, best buyer and RUB/slot")
print("PASS: Base value and Flea Market never used")

# The real v2 API may return ID-keyed dictionaries OR arrays.
# The previous implementation only accepted dictionaries.
trader_list = [
    {"id": TRADER_A, "normalizedName": "therapist"},
    {"id": TRADER_B, "normalizedName": "mechanic"},
    {"id": "flea-id", "normalizedName": "flea-market"},
]
item_list = list(sample_items(18_000, 14_000)["data"]["items"].values())

for items_payload, traders_payload in (
    ({"data": {"items": item_list}}, {"data": {"traders": trader_list}}),
    ({"data": {"items": item_list}}, {"data": {"traders": traders["data"]["traders"]}}),
    ({"items": item_list}, {"traders": trader_list}),
    ({"data": item_list}, {"data": trader_list}),
    ({"data": sample_items(18_000, 14_000)["data"]["items"]},
     {"data": traders["data"]["traders"]}),
):
    parsed = parse_trader_prices(items_payload, traders_payload)
    assert parsed == pvp, ("Unexpected result for response shape", parsed)

try:
    parse_trader_prices({"data": "invalid"}, {"data": {"traders": trader_list}})
except ValueError:
    pass
else:
    raise AssertionError("Malformed API response was not rejected")
print("PASS: List/dict and wrapped/unwrapped API response formats")


with tempfile.TemporaryDirectory() as folder:
    directory = Path(folder)
    now = time.time()
    save_price_cache(directory / "trader_sell_prices_regular.json", pvp, now)
    save_price_cache(directory / "trader_sell_prices_pve.json", pve, now)
    stored, stored_at = load_price_cache(directory / "trader_sell_prices_regular.json")
    assert stored == pvp and stored_at == now

    application = QCoreApplication.instance() or QCoreApplication([])
    catalog = TraderPriceCatalog(directory)
    assert catalog.has_prices("regular") and catalog.has_prices("pve")
    assert catalog.offers_for("regular", ITEM_ID)[0]["trader"] == "Therapist"
    assert catalog.offers_for("pve", ITEM_ID)[0]["trader"] == "Mechanic"
    catalog.ensure("regular")  # fresh cache: MUST NOT download
    assert not catalog.is_loading("regular")
    print("PASS: PvP/PvE isolated, compact cache, offline startup")

print("All trader price tests passed!")
