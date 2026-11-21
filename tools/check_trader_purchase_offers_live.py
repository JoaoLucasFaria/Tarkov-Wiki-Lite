"""Inspect live REST trader offers without dumping huge payloads.

Run: python -m tools.check_trader_purchase_offers_live
"""
import json
from urllib.request import Request, urlopen
from app.services.trader_purchase_offers import parse_trader_offers

ITEM = "57371f2b24597761224311f1"  # ammo with known trader cash offer
BASE = "https://api.tarkov-stammtisch.de/api/traders/offers/item"
for mode, game in (("regular", "eft"), ("pve", "pve")):
    print(f"\n=== {mode.upper()} - TRADER PURCHASE OFFERS ===")
    url = f"{BASE}/{ITEM}?game={game}&lang=en"
    try:
        request = Request(url, headers={"User-Agent":"TarkovWikiLite/0.2"})
        with urlopen(request, timeout=20) as response:
            data = json.load(response)
        print("Root keys:", list(data.keys()) if isinstance(data, dict) else type(data).__name__)
        print("API game mode:", data.get("gameType") if isinstance(data, dict) else "unknown")
        offers = parse_trader_offers(data, ITEM, mode)
        print("Offers:", len(offers))
        for offer in offers[:4]:
            print(offer["trader"], "LL", offer["loyalty"],
                  "stack", offer["stack_count"], "cash:",offer["cash_only"])
            for price in offer["requirements"][:3]:
                print("  payment:",price["count"],price["currency"] or price["item_id"] or price["type"])
    except Exception as exc:
        print("ERROR:", type(exc).__name__, str(exc)[:220])
