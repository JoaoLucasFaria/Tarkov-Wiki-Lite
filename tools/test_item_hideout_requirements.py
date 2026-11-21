"""Run: python -m tools.test_item_hideout_requirements (offline)."""
import tempfile
from pathlib import Path

from app.services.item_hideout_requirements import (
    ItemHideoutRequirements, parse_hideout_requirements, index_hideout_items,
)

STATION_A = "5d484fda654e7600681d9315"
STATION_B = "5d494a445b56502f18c98a10"
ITEM_A = "590a3efd86f77437d351a25b"
ITEM_B = "5d1b376e86f774252519444e"


def sample(count=3):
    return {
        "data": [
            {"id": STATION_A, "name": "hideout_area_10_name",
             "levels": [
                 {"level": 1, "itemRequirements": [
                     {"item": ITEM_A, "count": count},
                     {"item": ITEM_B, "count": 2},
                 ], "stationLevelRequirements": [{"station": STATION_B,"level": 1}],
                  "constructionTime": 3600},
                 {"level": 2, "itemRequirements": [{"item": {"id": ITEM_A}, "count": 5}],
                  "traderRequirements": [{"trader": "Mechanic", "level": 2}]},
             ]},
            {"id": STATION_B, "name": "hideout_area_9_name", "levels": [
                {"level": 1, "itemRequirements": {ITEM_A: 1}},
            ]},
        ]
    }


def check():
    stations = parse_hideout_requirements(sample())
    assert len(stations) == 2
    assert stations[0]["levels"][0]["items"][0]["count"] == 3
    assert stations[0]["levels"][0]["other"]["station"]
    assert stations[0]["levels"][1]["other"]["trader"]
    index = index_hideout_items(stations)
    assert sum(r["count"] for r in index[ITEM_A]) == 9
    assert sum(r["count"] for r in index[ITEM_B]) == 2
    assert len(index[ITEM_A]) == 3
    assert index[ITEM_A][0]["station_name"] == ""
    print("PASS: Hideout station levels, item counts, dependencies, item index")

    for invalid in ({"data": [{"id": STATION_A, "levels": [{"level": 1}]}]},
                    {"data": {}},
                    {"data": []}):
        try:
            parse_hideout_requirements(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("Unrecognized schema must not report zero requirements")
    print("PASS: Invalid API schema raises explicit error")

    class FakeApi:
        def __init__(self):
            self.calls = []

        def get_json(self, url, callback):
            self.calls.append((url, callback))

        def respond(self, path, payload, error=None):
            for i, (url, callback) in enumerate(self.calls):
                if path in url:
                    self.calls.pop(i)
                    callback(payload, error)
                    return
            raise AssertionError(f"Missing pending request: {path}")

    english = {"data": {
        "hideout_area_10_name": "Workbench",
        "hideout_area_9_name": "Bitcoin Farm",
    }}

    with tempfile.TemporaryDirectory() as tmp:
        api = FakeApi()
        svc = ItemHideoutRequirements(api, Path(tmp))
        updates = []
        svc.ensure("regular", lambda: updates.append("regular"))
        assert svc.status("regular") == "loading"
        api.respond("/v2/regular/hideout", sample())
        assert svc.status("regular") == "loading", "Names must finish before showing requirements"
        api.respond("/v2/regular/hideout_en", english)
        assert updates == ["regular"]
        assert svc.status("regular") == "ready"
        assert sum(x["count"] for x in svc.for_item("regular", ITEM_A)) == 9
        labels = {x["station_name"] for x in svc.for_item("regular", ITEM_A)}
        assert labels == {"Workbench", "Bitcoin Farm"}, labels
        assert svc.stations("regular")[0]["levels"][0]["other"]["station"]

        # PvE uses a distinct endpoint, index, labels and on-disk cache.
        svc.ensure("pve", lambda: updates.append("pve"))
        api.respond("/v2/pve/hideout", sample(7))
        api.respond("/v2/pve/hideout_en", english)
        assert sum(x["count"] for x in svc.for_item("pve", ITEM_A)) == 13
        assert sum(x["count"] for x in svc.for_item("regular", ITEM_A)) == 9

        # The same translated labels survive offline startup.
        offline = ItemHideoutRequirements(FakeApi(), Path(tmp))
        offline.ensure("regular", lambda: None)
        assert offline.status("regular") == "ready"
        assert {x["station_name"] for x in offline.for_item("regular", ITEM_A)} == labels

        # A refresh failure keeps the last known good cache and labels.
        offline.ensure("regular", lambda: None, force=True)
        offline.api.respond("/v2/regular/hideout", None, "offline")
        assert offline.status("regular") == "stale"
        assert sum(x["count"] for x in offline.for_item("regular", ITEM_A)) == 9
        assert {x["station_name"] for x in offline.for_item("regular", ITEM_A)} == labels
    print("PASS: translated station names, PvP/PvE isolation, offline cache, stale fallback")

    # If the translation file is unavailable, use English REST station names.
    with tempfile.TemporaryDirectory() as tmp:
        api = FakeApi()
        svc = ItemHideoutRequirements(api, Path(tmp))
        svc.ensure("regular", lambda: None)
        api.respond("/v2/regular/hideout", sample())
        api.respond("/v2/regular/hideout_en", None, "temporarily offline")
        assert svc.status("regular") == "loading"
        rest = {"data": [{"id": STATION_A, "name": "Workbench"},
                         {"id": STATION_B, "name": "Bitcoin Farm"}]}
        api.respond("/hideout?lang=en", rest)
        assert svc.status("regular") == "ready"
        assert {x["station_name"] for x in svc.for_item("regular", ITEM_A)} == {
            "Workbench", "Bitcoin Farm"
        }
    print("PASS: REST names fallback without changing mode-specific requirements")

    with tempfile.TemporaryDirectory() as tmp:
        api = FakeApi()
        svc = ItemHideoutRequirements(api, Path(tmp))
        svc.ensure("regular", lambda: None)
        api.respond("/v2/regular/hideout", sample())
        api.respond("/v2/regular/hideout_en", None, "offline")
        api.respond("/hideout?lang=en", None, "offline")
        assert svc.status("regular") == "ready"
        assert sum(x["count"] for x in svc.for_item("regular", ITEM_A)) == 9
        assert all(x["station_name"] == "" for x in svc.for_item("regular", ITEM_A))
    print("PASS: missing labels never corrupt construction quantities")


if __name__ == "__main__":
    check()
    print("All Hideout requirement tests passed!")
