"""Small PvP/PvE-aware index of Hideout crafts and trader barter recipes.

Crafts prioritize the game-mode-specific v2 mirror; barter offers use the
mode-aware REST endpoint with v2 fallback. Both REST and v2 data are parsed.
No Flea Market values, profitability, or player inventory are used here.
"""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Callable

API_ROOT = "https://api.tarkov-stammtisch.de/api"
CACHE_VERSION = 2
STATION_CACHE_VERSION = 1
STATION_CACHE_TTL = 7 * 24 * 60 * 60
# Confirmed Tarkov Workbench identifier; remaining stations resolve from the API.
KNOWN_STATION_NAMES = {
    "5d484fda654e7600681d9315": "Workbench",
}
CACHE_TTL = 24 * 60 * 60
CACHE_MAX_BYTES = 6 * 1024 * 1024
MODES = {"regular", "pve"}
KINDS = ("crafts", "barters")


def _valid_id(value: object) -> bool:
    return isinstance(value, str) and len(value) == 24 and all(
        c in "0123456789abcdefABCDEF" for c in value
    )


def _first(obj: dict, *fields: str) -> object:
    for field in fields:
        value = obj.get(field)
        if value is not None:
            return value
    return None


def _text(value: object) -> str:
    if isinstance(value, dict):
        for key in ("name", "shortName", "normalizedName", "title"):
            v = value.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""
    if isinstance(value, str):
        return value.strip()
    return ""


def _qty(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return int(value) if value == int(value) else round(value, 6)


def _item_ref(value: object) -> tuple[str | None, str]:
    if isinstance(value, dict):
        id_value = _first(value, "id", "itemId", "item_id", "_id")
        return (id_value.lower() if _valid_id(id_value) else None, _text(value))
    if _valid_id(value):
        return value.lower(), ""
    return None, ""


def _items(raw: object) -> list[dict]:
    """Normalize {item,count} and {itemId:count} recipe ingredient formats."""
    if isinstance(raw, dict):
        if "items" in raw and isinstance(raw["items"], (list, dict)):
            raw = raw["items"]
        elif "item" in raw or "itemId" in raw or "id" in raw:
            raw = [raw]
        else:
            raw = [
                {"item": key, "count": count}
                for key, count in raw.items() if _valid_id(key)
            ]
    if not isinstance(raw, list):
        return []
    found: list[dict] = []
    for value in raw:
        if isinstance(value, str):
            value = {"item": value, "count": 1}
        if not isinstance(value, dict):
            continue
        ref = _first(value, "item", "itemId", "item_id", "itemID", "id")
        item_id, name = _item_ref(ref)
        if not item_id:
            continue
        if not name:
            name = _text(value) if _text(value) != item_id else ""
        count = _qty(_first(value, "count", "quantity", "amount", "qty", "itemCount"))
        # Missing quantity is shown as unknown; never invent item counts.
        found.append({
            "id": item_id,
            "name": name,
            "count": count,
            "reusable": bool(_first(value, "isTool", "isReusable", "reusable", "tool")),
        })
    return found


def _collection(payload: object, kind: str) -> list[tuple[str | None, dict]]:
    value = payload
    for _ in range(4):
        if not isinstance(value, dict):
            break
        if "data" in value and isinstance(value["data"], (dict, list)):
            value = value["data"]
        elif kind in value and isinstance(value[kind], (dict, list)):
            value = value[kind]
        elif "results" in value and isinstance(value["results"], (dict, list)):
            value = value["results"]
        else:
            break
    if isinstance(value, list):
        return [(None, row) for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        return [
            (key, row) for key, row in value.items()
            if isinstance(row, dict)
        ]
    raise ValueError(f"Unexpected {kind} response: {type(value).__name__}")



def _v2_single_reward(row: dict, kind: str) -> list[dict]:
    """Normalize v2 singular craft product / barter offered item.

    REST uses rewardItems; v2 uses productItem / offeredItem instead.
    Preserve quantities only when supplied by the source.
    """
    field = "productItem" if kind == "crafts" else "offeredItem"
    raw = row.get(field)
    if raw is None:
        return []

    if isinstance(raw, (list, dict)):
        if isinstance(raw, dict) and _valid_id(_first(raw, "id", "itemId", "_id")):
            values = _items([raw])
        else:
            values = _items(raw)
        if values:
            # Some v2 sources put the output count at recipe level.
            # If absent everywhere, keep it unknown rather than guessing.
            top_count = _qty(_first(row,
                "productCount", "producedCount", "offeredCount", "rewardCount",
                "productQuantity", "offeredQuantity", "count", "quantity"))
            if len(values) == 1 and values[0]["count"] is None:
                values[0]["count"] = top_count
            return values
        # Raw might be an item metadata object with nested item ID.
        if isinstance(raw, dict):
            values = _items([{"item": raw, "count": _first(row,
                "productCount", "producedCount", "offeredCount", "rewardCount",
                "productQuantity", "offeredQuantity", "count", "quantity")}])
            if values:
                return values
        return []

    if _valid_id(raw):
        count = _first(row, "productCount", "producedCount", "offeredCount",
                       "rewardCount", "productQuantity", "offeredQuantity",
                       "count", "quantity")
        return _items([{"item": raw, "count": count}])
    return []

def parse_recipes(payload: object, kind: str) -> list[dict]:
    """Parse REST and v2 recipe responses, raising on unknown schemas."""
    if kind not in KINDS:
        raise ValueError("Unknown recipe kind")
    rows = _collection(payload, kind)
    if not rows:
        raise ValueError(f"No {kind} records in API response")
    result: list[dict] = []
    for key, row in rows:
        needed = _items(_first(
            row, "requiredItems", "inputItems", "ingredients", "inputs",
            "itemsRequired", "neededItems",
        ))
        rewards = _items(_first(
            row, "rewardItems", "outputItems", "producedItems", "outputs",
            "itemsRewarded", "itemsReceived", "rewards",
        ))
        if not rewards:
            rewards = _v2_single_reward(row, kind)
        if not needed or not rewards:
            continue
        source = _first(row, "station", "trader", "source")
        source_name = _text(source)
        source_id = source_name.lower() if _valid_id(source_name) else None
        if not source_name:
            source_name = _text(_first(row, "stationName", "traderName", "sourceName"))
        if not source_name:
            source_name = "Unknown station" if kind == "crafts" else "Unknown trader"
        lvl = _first(row, "level", "stationLevel", "loyaltyLevel", "minTraderLevel", "traderLevel")
        if isinstance(lvl, dict):
            lvl = _first(lvl, "level", "value")
        level = lvl if type(lvl) is int and lvl > 0 else None
        duration = _first(row, "duration", "durationSeconds", "craftTimeSeconds", "time")
        duration = duration if type(duration) is int and duration >= 0 else None
        unlock = _first(row, "taskUnlock", "unlockTask", "questUnlock", "requiredQuest")
        recipe_id = _first(row, "id", "_id") or key or ""
        result.append({
            "id": str(recipe_id),
            "kind": kind,
            "source": source_name,
            "source_id": source_id,
            "level": level,
            "duration": duration,
            "unlock": bool(unlock),
            "required": needed,
            "rewards": rewards,
        })
    if not result:
        examples = list(rows[0][1])[:12]
        raise ValueError(
            f"No {kind} records with readable ingredients and outputs; "
            f"first_record_keys={examples!r}"
        )
    return result


def parse_station_names(payload: object, translations: object = None) -> dict[str, str]:
    """Resolve hideout station IDs to English names, without depending on order.

    Supports both API v2 (names may be translation keys) and REST hideout
    (names already translated). We only collect station metadata, not levels.
    """
    translation_map = translations.get("data", translations) if isinstance(translations, dict) else {}
    if not isinstance(translation_map, dict):
        translation_map = {}
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    resolved: dict[str, str] = {}
    pending = [(data, 0, None)]
    while pending:
        current, depth, parent_key = pending.pop()
        if depth > 5:
            continue
        if isinstance(current, list):
            pending.extend((entry, depth + 1, None) for entry in current if isinstance(entry, (dict, list)))
            continue
        if not isinstance(current, dict):
            continue
        station_id = _first(current, "id", "stationId", "_id")
        if not _valid_id(station_id) and _valid_id(parent_key):
            station_id = parent_key
        if _valid_id(station_id):
            raw_name = _first(current, "name", "stationName", "title", "nameId")
            name = _text(raw_name)
            if name in translation_map:
                name = _text(translation_map[name])
            # A translation key is not an English station name.
            if name and not name.startswith("hideout_area_") and not _valid_id(name):
                resolved[station_id.lower()] = name
        for key, value in current.items():
            if isinstance(value, (dict, list)):
                pending.append((value, depth + 1, key))
    return resolved



def resolve_recipe_source_name(
    mode: str,
    recipe: dict,
    recipes: "ItemRecipeCatalog",
    hideout_requirements: object,
) -> str:
    """Prefer the already-translated Hideout station labels for craft recipes.

    The Hideout requirements service independently resolves all station names
    using v2 translations and REST metadata. Reusing those names prevents
    partially populated recipe-station caches from showing "Unknown station".
    The lookup is mode-specific and does not trigger network requests.
    Trader barter labels are left untouched.
    """
    fallback = recipes.source_name(mode, recipe)
    if recipe.get("kind") != "crafts":
        return fallback
    station_id = recipe.get("source_id") or recipe.get("source")
    if not _valid_id(station_id):
        return fallback

    # ItemHideoutRequirements.stations() returns the cached records for the
    # selected game mode. When absent (e.g. offline first run), keep the
    # recipe catalog's existing translated-name/fallback behavior.
    records = hideout_requirements.stations(mode)
    for station in records:
        if not isinstance(station, dict):
            continue
        if str(station.get("station_id") or "").lower() != station_id.lower():
            continue
        label = station.get("station_name")
        if (isinstance(label, str) and label.strip()
                and not label.startswith("hideout_area_")
                and not _valid_id(label)):
            return label.strip()
    return fallback


def _read_station_cache(path: Path) -> tuple[dict[str, str], float]:
    try:
        if path.stat().st_size > 100_000:
            return {}, 0.0
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("version") != STATION_CACHE_VERSION:
            return {}, 0.0
        names = value.get("names")
        if not isinstance(names, dict):
            return {}, 0.0
        clean = {
            key.lower(): val for key, val in names.items()
            if _valid_id(key) and isinstance(val, str) and val.strip()
        }
        fetched = value.get("fetched_at")
        return clean, float(fetched) if type(fetched) in (int, float) else 0.0
    except (OSError, ValueError, TypeError, AttributeError):
        return {}, 0.0


def _write_station_cache(path: Path, names: dict[str, str], stamp: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        temp.write_text(json.dumps({"version": STATION_CACHE_VERSION,
                                    "fetched_at": stamp, "names": names},
                                   ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def build_recipe_index(recipes: list[dict]) -> dict[str, dict[str, list[int]]]:
    """For any item, index recipes that produce it vs require it."""
    index: dict[str, dict[str, list[int]]] = {}
    for i, recipe in enumerate(recipes):
        for field, side in (("required", "using"), ("rewards", "for")):
            for ingredient in recipe[field]:
                item_id = ingredient["id"]
                groups = index.setdefault(item_id, {"for": [], "using": []})
                if i not in groups[side]:
                    groups[side].append(i)
    return index


def _read_cache(path: Path) -> tuple[list[dict] | None, float]:
    try:
        if path.stat().st_size > CACHE_MAX_BYTES:
            return None, 0.0
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") != CACHE_VERSION:
            return None, 0.0
        recipes = payload.get("recipes")
        fetched_at = payload.get("fetched_at")
        if not isinstance(recipes, list) or not recipes:
            return None, 0.0
        if not isinstance(fetched_at, (float, int)):
            return None, 0.0
        if not all(isinstance(row, dict) and "required" in row and "rewards" in row
                   for row in recipes):
            return None, 0.0
        return recipes, float(fetched_at)
    except (OSError, ValueError, TypeError, AttributeError):
        return None, 0.0


def _write_cache(path: Path, recipes: list[dict], fetched_at: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        temp.write_text(
            json.dumps({"version": CACHE_VERSION, "fetched_at": fetched_at,
                        "recipes": recipes}, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


class ItemRecipeCatalog:
    """Lazy, nonblocking recipe index with independent PvP/PvE caches.

    Depends on the existing async TarkovApi.get_json(url, callback) interface.
    """

    def __init__(self, api, cache_dir: Path):
        self.api = api
        self.cache_dir = cache_dir
        self._recipes: dict[tuple[str, str], list[dict]] = {}
        self._indexes: dict[tuple[str, str], dict] = {}
        self._timestamps: dict[tuple[str, str], float] = {}
        self._loading: set[tuple[str, str]] = set()
        self._errors: dict[tuple[str, str], str] = {}
        self._listeners: list[Callable[[], None]] = []
        self._station_names: dict[str, dict[str, str]] = {}
        self._station_fetched: dict[str, float] = {}
        self._station_loading: set[str] = set()
        self._station_failed: set[str] = set()
        for mode in MODES:
            names, stamp = _read_station_cache(self._station_cache_path(mode))
            self._station_names[mode] = names
            self._station_fetched[mode] = stamp
        for mode in MODES:
            for kind in KINDS:
                key = (mode, kind)
                data, stamp = _read_cache(self._cache_path(mode, kind))
                if data:
                    self._set_data(key, data, stamp)

    def _cache_path(self, mode: str, kind: str) -> Path:
        return self.cache_dir / f"item_{kind}_{mode}.json"

    def _station_cache_path(self, mode: str) -> Path:
        return self.cache_dir / f"item_station_names_{mode}.json"

    def source_name(self, mode: str, recipe: dict) -> str:
        """Give the UI a readable station name, never a raw internal ID."""
        raw = str(recipe.get("source") or "").strip()
        if recipe.get("kind") != "crafts" or not _valid_id(raw):
            return raw or "Unknown"
        name = self._station_names.get(mode, {}).get(raw.lower())
        return name or KNOWN_STATION_NAMES.get(raw.lower(), "Unknown station")

    def _needs_station_names(self, mode: str) -> bool:
        crafts = self._recipes.get((mode, "crafts"), ())
        return any(_valid_id(str(row.get("source") or "")) for row in crafts)

    def _ensure_station_names(self, mode: str) -> None:
        if not self._needs_station_names(mode):
            return
        if mode in self._station_loading or mode in self._station_failed:
            return
        names = self._station_names.get(mode, {})
        if names and time.time() - self._station_fetched.get(mode, 0) < STATION_CACHE_TTL:
            return
        self._station_loading.add(mode)
        # v2 hideout has station IDs. Its _en companion maps translation keys
        # (e.g. hideout_area_10_name) to names, without mixing PvP and PvE.
        self.api.get_json(
            f"{API_ROOT}/v2/{mode}/hideout",
            lambda data, error, m=mode: self._on_station_base(m, data, error),
        )

    def _on_station_base(self, mode: str, data: object, error: str | None) -> None:
        if error is not None or not isinstance(data, (dict, list)):
            self._station_rest_fallback(mode)
            return
        self.api.get_json(
            f"{API_ROOT}/v2/{mode}/hideout_en",
            lambda translations, err, m=mode, base=data:
                self._on_station_translations(m, base, translations, err),
        )

    def _on_station_translations(
        self, mode: str, base: object, translations: object, error: str | None
    ) -> None:
        names = parse_station_names(base, translations if error is None else None)
        if names:
            self._finish_stations(mode, names)
        else:
            self._station_rest_fallback(mode)

    def _station_rest_fallback(self, mode: str) -> None:
        # Names only: shared REST metadata is safe even for PvE. Never use
        # this endpoint to replace mode-specific *craft recipe* data.
        self.api.get_json(
            f"{API_ROOT}/hideout?lang=en",
            lambda data, error, m=mode: self._finish_stations(
                m, parse_station_names(data) if error is None else {}
            ),
        )

    def _finish_stations(self, mode: str, names: dict[str, str]) -> None:
        self._station_loading.discard(mode)
        if names:
            stamp = time.time()
            self._station_names[mode] = names
            self._station_fetched[mode] = stamp
            try:
                _write_station_cache(self._station_cache_path(mode), names, stamp)
            except OSError as exc:
                print(f"Station cache warning: {exc}")
        else:
            self._station_failed.add(mode)
            print(f"Station name warning: couldn't resolve names for {mode}")
        self._signal()

    def _set_data(self, key: tuple[str, str], recipes: list[dict], stamp: float) -> None:
        self._recipes[key] = recipes
        self._indexes[key] = build_recipe_index(recipes)
        self._timestamps[key] = stamp

    def ensure(self, mode: str, on_updated: Callable[[], None], force: bool = False) -> None:
        """Load missing/stale recipes without blocking the GUI."""
        if mode not in MODES:
            return
        if on_updated not in self._listeners:
            self._listeners.append(on_updated)
        for kind in KINDS:
            key = (mode, kind)
            if key in self._loading:
                continue
            if not force and key in self._errors:
                continue
            if not force and key in self._recipes and (
                time.time() - self._timestamps.get(key, 0) < CACHE_TTL
            ):
                continue
            self._errors.pop(key, None)
            self._loading.add(key)
            game = "eft" if mode == "regular" else "pve"
            if kind == "crafts":
                # The v2 mirror is mode-aware. The REST crafts endpoint isn't.
                url = f"{API_ROOT}/v2/{mode}/crafts"
            else:
                url = f"{API_ROOT}/barters?game={game}&lang=en"
            self._request(key, url, fallback=False)
        self._ensure_station_names(mode)

    def _request(self, key: tuple[str, str], url: str, fallback: bool) -> None:
        def received(payload, error) -> None:
            if error is None:
                try:
                    recipes = parse_recipes(payload, key[1])
                except (ValueError, KeyError, TypeError) as exc:
                    error_text = str(exc)
                else:
                    fetched = time.time()
                    self._set_data(key, recipes, fetched)
                    try:
                        _write_cache(self._cache_path(*key), recipes, fetched)
                    except OSError as exc:
                        print(f"Recipe cache warning: {exc}")
                    self._loading.discard(key)
                    self._errors.pop(key, None)
                    if key[1] == "crafts":
                        self._ensure_station_names(key[0])
                    self._signal()
                    return
            else:
                error_text = str(error)
            if not fallback:
                # Barters: REST -> mode-specific v2 mirror.
                # Crafts: mode-specific v2 -> normalized REST, but only for
                # regular mode. REST crafts has no game mode argument and
                # must not be silently reused as PvE-specific data.
                if key[1] == "barters":
                    alternative = f"{API_ROOT}/v2/{key[0]}/barters"
                elif key[0] == "regular":
                    alternative = f"{API_ROOT}/crafts?lang=en"
                else:
                    self._loading.discard(key)
                    self._errors[key] = (
                        f"PvE crafts unavailable: {error_text}; "
                        "global REST craft data was not substituted."
                    )
                    self._signal()
                    return
                self._request(key, alternative, fallback=True)
                return
            self._loading.discard(key)
            self._errors[key] = f"Recipe source(s) failed: {error_text}"
            self._signal()

        self.api.get_json(url, received)

    def _signal(self) -> None:
        for listener in list(self._listeners):
            listener()

    def status(self, mode: str, kind: str) -> str:
        key = (mode, kind)
        if key in self._recipes:
            return "refreshing" if key in self._loading else "ready"
        if key in self._loading:
            return "loading"
        if key in self._errors:
            return "error"
        return "empty"

    def error(self, mode: str, kind: str) -> str:
        return self._errors.get((mode, kind), "")

    def recipes_for(self, mode: str, kind: str, item_id: str, side: str) -> list[dict]:
        if mode not in MODES or kind not in KINDS or side not in {"for", "using"}:
            return []
        key = (mode, kind)
        ids = self._indexes.get(key, {}).get(item_id.lower(), {}).get(side, [])
        recipes = self._recipes.get(key, [])
        return [recipes[i] for i in ids]

    def timestamp(self, mode: str, kind: str) -> float:
        return self._timestamps.get((mode, kind), 0.0)
