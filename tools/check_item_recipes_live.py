"""Read-only diagnosis of public Crafts & Barters API responses.

Run: python -m tools.check_item_recipes_live
No files are written; only response types, sample keys, and parsed counts print.
"""
import json
from urllib.request import Request, urlopen

from app.services.item_recipe_catalog import parse_recipes

API = "https://api.tarkov-stammtisch.de/api"
for kind, source, url in (
    ("crafts", "v2 PvP", f"{API}/v2/regular/crafts"),
    ("crafts", "REST", f"{API}/crafts?lang=en"),
    ("barters", "REST PvP", f"{API}/barters?game=eft&lang=en"),
    ("barters", "v2 PvP", f"{API}/v2/regular/barters"),
):
    print(f"\n=== {kind.upper()} / {source} ===")
    try:
        req = Request(url, headers={"User-Agent": "TarkovWikiLite/0.2"})
        with urlopen(req, timeout=25) as res:
            payload = json.load(res)
        print("Root type:", type(payload).__name__)
        if isinstance(payload, dict):
            print("Root keys:", list(payload)[:12])
            data = payload.get("data", payload)
            print("Data type:", type(data).__name__)
            if isinstance(data, dict) and kind in data:
                data = data[kind]
            if isinstance(data, list) and data and isinstance(data[0], dict):
                print("First record keys:", list(data[0])[:24])
                for field in ("productItem", "offeredItem", "requiredItems"):
                    if field in data[0]:
                        value = data[0][field]
                        print(f"{field}: type={type(value).__name__}, sample={str(value)[:240]}")
            elif isinstance(data, dict):
                first_key = next((k for k, v in data.items() if isinstance(v, dict)), None)
                print("Data keys sample:", list(data)[:8])
                if first_key is not None:
                    print("First record keys:", list(data[first_key])[:24])
                    for field in ("productItem", "offeredItem", "requiredItems"):
                        if field in data[first_key]:
                            value = data[first_key][field]
                            print(f"{field}: type={type(value).__name__}, sample={str(value)[:240]}")
        parsed = parse_recipes(payload, kind)
        print("Parsed recipes:", len(parsed))
        print("First parsed source:", parsed[0]["source"])
        print("First required items:", len(parsed[0]["required"]))
        print("First reward items:", len(parsed[0]["rewards"]))
    except Exception as err:
        print("ERROR:", type(err).__name__, str(err))
