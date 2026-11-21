"""Regression test for names in Crafts & Barters when Hideout knows the station.

Run from project root: python -m tools.test_craft_station_hideout_fallback
"""
import tempfile
from pathlib import Path

from app.services.item_hideout_requirements import ItemHideoutRequirements
from app.services.item_recipe_catalog import (
    ItemRecipeCatalog, resolve_recipe_source_name,
)


class OfflineApi:
    def get_json(self, url, callback):
        raise AssertionError(f"Station-name display must not fetch data: {url}")


MEDSTATION = "5d494a3f5b56502f18c98a0f"  # synthetic mapping for isolated test
WORKBENCH = "5d484fda654e7600681d9315"

with tempfile.TemporaryDirectory() as folder:
    cache = Path(folder)
    api = OfflineApi()
    recipes = ItemRecipeCatalog(api, cache)
    hideout = ItemHideoutRequirements(api, cache)
    craft = {
        "kind": "crafts", "source": MEDSTATION,
        "source_id": MEDSTATION, "level": 3,
    }
    assert recipes.source_name("regular", craft) == "Unknown station"

    hideout._set_data("regular", [{
        "station_id": MEDSTATION,
        "station_name": "Medstation",
        "levels": [],
    }], 0)
    hideout._set_data("pve", [{
        "station_id": MEDSTATION,
        "station_name": "Lavatory",  # deliberately different: proves isolation
        "levels": [],
    }], 0)
    assert resolve_recipe_source_name("regular", craft, recipes, hideout) == "Medstation"
    assert resolve_recipe_source_name("pve", craft, recipes, hideout) == "Lavatory"
    print("PASS: craft labels use translated Hideout station names per game mode")

    barter = {"kind": "barters", "source": "Jaeger", "level": 3}
    assert resolve_recipe_source_name("regular", barter, recipes, hideout) == "Jaeger"
    print("PASS: trader barter names are unchanged")

    missing = {"kind": "crafts", "source": WORKBENCH, "source_id": WORKBENCH}
    assert resolve_recipe_source_name("regular", missing, recipes, hideout) == "Workbench"
    unknown = {"kind": "crafts", "source": MEDSTATION, "source_id": MEDSTATION}
    hideout._set_data("regular", [], 0)
    assert resolve_recipe_source_name("regular", unknown, recipes, hideout) == "Unknown station"
    print("PASS: original recipe name fallback remains available offline")

    hideout._set_data("regular", [{
        "station_id": MEDSTATION, "station_name": "hideout_area_7_name",
        "levels": [],
    }], 0)
    assert resolve_recipe_source_name("regular", craft, recipes, hideout) == "Unknown station"
    print("PASS: unresolved translation keys are never displayed")

print("All Crafts station label regression tests passed!")
