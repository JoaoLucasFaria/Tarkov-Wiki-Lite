"""Offline regression for station names in the v2 Crafts mirror.

Run from project root: python -m tools.test_recipe_station_names
"""
import json
import tempfile
from pathlib import Path

from app.services.item_recipe_catalog import (
    ItemRecipeCatalog, parse_recipes, parse_station_names,
)

WORKBENCH = '5d484fda654e7600681d9315'
ANOTHER_STATION = '5d484fda654e7600681d9316'  # Synthetic ID for test only.
GAS_ANALYZER = '590a3efd86f77437d351a25b'
OTHER_ITEM = '5d1b376e86f774252519444e'

class FakeApi:
    def __init__(self):
        self.requests = []

    def get_json(self, url, callback):
        self.requests.append((url, callback))

    def respond(self, contains, payload, error=None):
        for index, (url, cb) in enumerate(self.requests):
            if contains in url:
                self.requests.pop(index)
                cb(payload, error)
                return
        raise AssertionError(f'No queued request matching {contains}')

v2_craft = {'data': [{
    'id': 'craft-gasan', 'station': WORKBENCH, 'level': 1,
    'duration': 3000, 'requiredItems': [{'item': OTHER_ITEM, 'count': 1}],
    'productItem': {'item': GAS_ANALYZER, 'count': 1},
}, {
    'id': 'craft-other', 'station': ANOTHER_STATION, 'level': 2,
    'requiredItems': [{'item': OTHER_ITEM, 'count': 1}],
    'productItem': {'item': GAS_ANALYZER, 'count': 1},
}]}

base = {'data': {'stations': {
    WORKBENCH: {'id': WORKBENCH, 'name': 'hideout_area_10_name'},
    ANOTHER_STATION: {'id': ANOTHER_STATION, 'name': 'hideout_area_7_name'},
}}}
english = {'data': {
    'hideout_area_10_name': 'Workbench',
    'hideout_area_7_name': 'Medstation',
}}

names = parse_station_names(base, english)
assert names == {WORKBENCH: 'Workbench', ANOTHER_STATION: 'Medstation'}, names
rest = {'data': [{'id': WORKBENCH, 'name': 'Workbench'}]}
assert parse_station_names(rest)[WORKBENCH] == 'Workbench'
assert not parse_station_names(base), 'Untranslated keys must not be displayed as names'
print('PASS: v2 Hideout station IDs resolved from English translations')

recipes = parse_recipes(v2_craft, 'crafts')
assert recipes[0]['source'] == WORKBENCH
assert recipes[1]['source'] == ANOTHER_STATION
assert recipes[0]['source_id'] == WORKBENCH
print('PASS: original station IDs retained in craft metadata')

with tempfile.TemporaryDirectory() as tmp:
    directory = Path(tmp)
    api = FakeApi()
    catalog = ItemRecipeCatalog(api, directory)
    updates = []
    catalog.ensure('regular', lambda: updates.append('refresh'))
    assert len(api.requests) == 2
    api.respond('/v2/regular/crafts', v2_craft)
    # Workbench is a verified lightweight fallback even while translation loads.
    assert catalog.source_name('regular', recipes[0]) == 'Workbench'
    assert catalog.source_name('regular', recipes[1]) == 'Unknown station'
    assert any('/v2/regular/hideout' in u for u, _ in api.requests)
    api.respond('/v2/regular/hideout', base)
    api.respond('/v2/regular/hideout_en', english)
    assert catalog.source_name('regular', recipes[1]) == 'Medstation'
    assert directory.joinpath('item_station_names_regular.json').is_file()
    assert updates
    # Cache refresh should not download v2 hideout repeatedly.
    pending = len(api.requests)
    catalog.ensure('regular', lambda: None)
    assert len(api.requests) == pending
    # Offline startup shows names from compact station cache.
    offline = ItemRecipeCatalog(FakeApi(), directory)
    saved = offline.recipes_for('regular', 'crafts', GAS_ANALYZER, 'for')
    assert saved and offline.source_name('regular', saved[1]) == 'Medstation'
    print('PASS: lazy metadata loading, cache, offline station labels')

    # PvE station metadata is fetched independently.
    cat_api = FakeApi()
    other = ItemRecipeCatalog(cat_api, directory)
    other.ensure('pve', lambda: None)
    cat_api.respond('/v2/pve/crafts', v2_craft)
    assert other.source_name('pve', recipes[1]) == 'Unknown station'
    cat_api.respond('/v2/pve/hideout', base)
    cat_api.respond('/v2/pve/hideout_en', english)
    assert other.source_name('pve', recipes[1]) == 'Medstation'
    print('PASS: station metadata remains mode-specific')

    # When name lookup fails, do not show a raw hexadecimal ID.
    failed_api = FakeApi()
    failed = ItemRecipeCatalog(failed_api, directory / 'failed')
    failed.ensure('regular', lambda: None)
    failed_api.respond('/v2/regular/crafts', v2_craft)
    failed_api.respond('/v2/regular/hideout', None, 'offline')
    failed_api.respond('/hideout?lang=en', None, 'offline')
    assert failed.source_name('regular', recipes[0]) == 'Workbench'
    assert failed.source_name('regular', recipes[1]) == 'Unknown station'
    print('PASS: offline fallback does not expose raw IDs')

print('All station-name tests passed!')
