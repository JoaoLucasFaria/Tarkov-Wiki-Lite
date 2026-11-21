"""Read-only station-name probe. Run: python -m tools.check_craft_station_names_live"""
import json
from urllib.request import Request, urlopen

from app.services.item_recipe_catalog import parse_station_names

BASE = 'https://api.tarkov-stammtisch.de/api'
WORKBENCH = '5d484fda654e7600681d9315'


def get_json(path):
    request = Request(BASE + path, headers={'User-Agent': 'TarkovWikiLite/1.0'})
    with urlopen(request, timeout=25) as response:
        return json.load(response)


for mode in ('regular', 'pve'):
    print(f'\n=== {mode.upper()} HIDEOUT STATION NAMES ===')
    try:
        base = get_json(f'/v2/{mode}/hideout')
        english = get_json(f'/v2/{mode}/hideout_en')
        names = parse_station_names(base, english)
        print('Resolved station names:', len(names))
        print('Gas Analyzer craft station:', names.get(WORKBENCH, '<not resolved>'))
        if names:
            for key, value in sorted(names.items(), key=lambda row: row[1])[:8]:
                print(f'  {value}: {key}')
        else:
            print('No station names found. Please send this output for schema inspection.')
            print('Base root keys:', list(base)[:12] if isinstance(base, dict) else type(base).__name__)
            print('Base data type:', type(base.get('data')).__name__ if isinstance(base, dict) else 'n/a')
            print('English root keys:', list(english)[:12] if isinstance(english, dict) else type(english).__name__)
    except Exception as error:
        print(f'API probe failed: {type(error).__name__}: {error}')
