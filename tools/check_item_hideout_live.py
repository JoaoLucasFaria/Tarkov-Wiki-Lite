"""Inspect live mode-specific Hideout requirements without saving full dump.

Run: python -m tools.check_item_hideout_live
"""
import json
from urllib.request import urlopen, Request
from app.services.item_hideout_requirements import parse_hideout_requirements, index_hideout_items

ITEM = "590a3efd86f77437d351a25b"  # Gas analyzer

for mode in ("regular", "pve"):
    print(f"\n=== {mode.upper()} HIDEOUT ===")
    url = f"https://api.tarkov-stammtisch.de/api/v2/{mode}/hideout"
    try:
        with urlopen(Request(url,headers={"User-Agent":"TarkovWikiLite/0.2"}),timeout=20) as r:
            data = json.load(r)
        print("Root type:",type(data).__name__)
        print("Root keys:",list(data)[:10] if isinstance(data,dict) else "-")
        d = data.get("data") if isinstance(data,dict) else data
        print("Data type:",type(d).__name__)
        sample = next(iter(d.values()),None) if isinstance(d,dict) else (d[0] if isinstance(d,list) and d else None)
        print("First station keys:",list(sample)[:15] if isinstance(sample,dict) else "-")
        levels = sample.get("levels") if isinstance(sample,dict) else None
        first_lvl = (levels[0] if isinstance(levels,list) and levels else
                     next(iter(levels.values()),None) if isinstance(levels,dict) else None)
        print("First level keys:",list(first_lvl)[:15] if isinstance(first_lvl,dict) else "-")
        stations = parse_hideout_requirements(data)
        index = index_hideout_items(stations)
        print("Stations parsed:",len(stations))
        print("Item IDs indexed:",len(index))
        print("Gas analyzer material entries:",len(index.get(ITEM,[])))
    except Exception as exc:
        print("ERROR:",type(exc).__name__,str(exc)[:400])
