"""Read-only check of Hideout station IDs and English labels in both modes.

Run from project root: python -m tools.check_hideout_station_labels_live
"""
import json
from urllib.request import Request, urlopen

from app.services.item_hideout_requirements import parse_hideout_requirements
from app.services.item_recipe_catalog import parse_station_names

BASE = "https://api.tarkov-stammtisch.de/api"


def get(path):
    request = Request(BASE + path, headers={"User-Agent": "TarkovWikiLite/0.2"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


for mode in ("regular", "pve"):
    print(f"\n=== {mode.upper()} HIDEOUT LABELS ===")
    try:
        base = get(f"/v2/{mode}/hideout")
        english = get(f"/v2/{mode}/hideout_en")
        stations = parse_hideout_requirements(base)
        names = parse_station_names(base, english)
        unresolved = [station for station in stations
                      if station["station_id"] not in names and not station["station_name"]]
        print("Stations with material data:", len(stations))
        print("English names resolved:", len(names))
        print("Unresolved station IDs:", len(unresolved))
        for station in unresolved[:12]:
            print(f"  {station['station_id']} | key={station.get('name_key')!r}")
        for station in stations[:5]:
            sid = station["station_id"]
            print(f"  {names.get(sid) or station['station_name'] or 'Unknown'}: {sid}")
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
