"""Run: python -m tools.test_trader_purchase_offers (offline, no Qt)."""
import json
import tempfile
from pathlib import Path

from app.services.trader_purchase_offers import (
    TraderPurchaseOffers, parse_trader_offers, _read_cache, _write_cache,
)

ITEM = "57371f2b24597761224311f1"
RUB = "5449016a4bdc2d6f028b456f"
DOG = "59f32c3b86f77472a31742f0"


def sample(game="eft"):
    return {
        "gameType": game,
        "item": {"id": ITEM, "name": "Example ammunition"},
        "count": 2,
        "offers": [
            {
                "itemTpl": ITEM, "traderName": "Prapor", "traderId": "54cb50c76803fa8b248b4571",
                "stackCount": 30, "summaryCost": 99999999, "itemsCost": 1111,
                "loyaltyLevel": 2, "minTraderLevel": 15,
                "requirements": [{"_tpl": RUB, "type": "ItemRequirement", "count": 2100}],
            },
            {
                "itemTpl": ITEM, "traderName": "Therapist", "loyaltyLevel": 3,
                "requirements": [{"_tpl": DOG, "type": "DogtagRequirement", "count": 2,
                                  "level": 20, "side": "Usec"}],
            },
        ]
    }


def check():
    parsed = parse_trader_offers(sample(), ITEM, "regular")
    assert len(parsed) == 2
    assert parsed[0]["cash_only"] is True
    assert parsed[0]["requirements"][0]["count"] == 2100
    assert parsed[0]["requirements"][0]["currency"] == "₽"
    assert parsed[0]["stack_count"] == 30
    assert parsed[1]["cash_only"] is False
    assert parsed[1]["requirements"][0]["level"] == 20
    assert parsed[1]["requirements"][0]["side"] == "Usec"
    print("PASS: Actual REST offers shape, cash, dogtags and LL")

    assert parse_trader_offers({"gameType":"eft", "offers":[]}, ITEM, "regular") == []
    try:
        parse_trader_offers(sample("eft"), ITEM, "pve")
        raise AssertionError("Mode should reject mismatched data")
    except ValueError:
        pass
    try:
        parse_trader_offers({"data": {"offers": []}}, ITEM, "regular")
        raise AssertionError("Unknown response schema must not silently succeed")
    except ValueError:
        pass
    try:
        parse_trader_offers({"offers":[{"itemTpl":ITEM,"traderName":"X","summaryCost":99}]}, ITEM, "regular")
    except ValueError:
        pass
    else:
        raise AssertionError("Missing payment details must raise, never claim no offers")
    assert parse_trader_offers({"offers":[{"itemTpl":"0"*24,"traderName":"X","requirements":[{"_tpl":RUB,"count":2}]}]}, ITEM, "regular") == []
    print("PASS: No invented cash prices, mismatched mode, unknown schema")

    class FakeApi:
        def __init__(self):
            self.requests = []
        def get_json(self, url, callback):
            self.requests.append((url, callback))

    with tempfile.TemporaryDirectory() as directory:
        api = FakeApi()
        catalog = TraderPurchaseOffers(api, Path(directory))
        updates = []
        catalog.ensure("regular", ITEM, lambda:updates.append("pvp"))
        assert catalog.status("regular", ITEM) == "loading"
        assert len(api.requests) == 1 and "game=eft" in api.requests[0][0]
        api.requests[0][1](sample(), None)
        assert updates == ["pvp"]
        assert catalog.status("regular",ITEM) == "ready"
        assert catalog.offers_for("regular", ITEM) == parsed
        assert len(api.requests) == 1
        catalog.ensure("regular", ITEM, lambda:None)
        assert len(api.requests) == 1

        catalog.ensure("pve", ITEM, lambda: updates.append("pve"))
        assert len(api.requests) == 2 and "game=pve" in api.requests[1][0]
        api.requests[1][1](sample("pve"), None)
        assert updates[-1] == "pve"
        assert catalog.offers_for("pve",ITEM)
        cached = Path(directory) / "trader_purchase_offers" / "regular" / f"{ITEM}.json"
        assert cached.exists()
        assert _read_cache(cached)[0] == parsed

        restarted = TraderPurchaseOffers(FakeApi(),Path(directory))
        restarted.ensure("regular", ITEM, lambda:None)
        assert restarted.status("regular",ITEM) == "ready"
        assert restarted.offers_for("regular",ITEM) == parsed
        restarted.ensure("regular",ITEM,lambda:None,force=True)
        assert restarted.status("regular",ITEM) == "refreshing"
        restarted.api.requests[0][1](None,"Offline")
        assert restarted.status("regular",ITEM) == "stale"
        assert restarted.offers_for("regular",ITEM) == parsed
    print("PASS: PvP/PvE isolation, async calls, disk cache, offline fallback")


if __name__ == "__main__":
    check()
    print("All trader purchase offer tests passed!")
