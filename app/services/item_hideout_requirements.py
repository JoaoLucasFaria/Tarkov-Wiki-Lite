"""Mode-aware Hideout construction material requirements.

Public encyclopedia data only. No player levels, inventory or quest progress are
stored here. My PMC can later use the per-station/per-level records to compute
remaining materials from the player's manually recorded station levels.
"""
from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Callable

from app.services.item_recipe_catalog import _items, _valid_id, _first, parse_station_names

API_ROOT = "https://api.tarkov-stammtisch.de/api"
MODES = {"regular", "pve"}
CACHE_VERSION = 2
CACHE_TTL = 24 * 60 * 60
CACHE_MAX_BYTES = 750_000


def _records(payload: object) -> list[dict]:
    data = payload
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    if isinstance(data, dict) and "stations" in data:
        data = data["stations"]
    if isinstance(data, list):
        return [v for v in data if isinstance(v, dict)]
    if isinstance(data, dict):
        return [dict(v, id=v.get("id", key)) for key, v in data.items() if isinstance(v, dict)]
    raise ValueError(f"Unexpected Hideout data type: {type(data).__name__}")


def _levels(value: object) -> list[dict]:
    if isinstance(value, list):
        return [entry for entry in value if isinstance(entry, dict)]
    if isinstance(value, dict):
        return [dict(entry, level=entry.get("level", int(key) if str(key).isdigit() else None))
                for key, entry in value.items() if isinstance(entry, dict)]
    return []


def parse_hideout_requirements(payload: object) -> list[dict]:
    """Extract station levels, required items and independent upgrade conditions.

    Unknown response shapes raise rather than silently showing zero requirements.
    """
    records = _records(payload)
    if not records:
        raise ValueError("No Hideout stations in API response")
    result = []
    for station in records:
        station_id = _first(station, "id", "stationId", "_id")
        station_id = station_id.lower() if _valid_id(station_id) else ""
        if not station_id:
            continue
        raw_levels = _levels(_first(station, "levels", "stationLevels", "upgrades"))
        if not raw_levels:
            continue
        levels = []
        for position, entry in enumerate(raw_levels, start=1):
            level = _first(entry, "level", "stationLevel", "id")
            if type(level) is str and level.isdecimal():
                level = int(level)
            if type(level) is not int or level < 1:
                # Avoid invented upgrade levels. Parser diagnostics can reveal
                # stations that need a separate schema adapter.
                continue
            raw_required = _first(
                entry, "itemRequirements", "requiredItems", "itemsRequired",
                "constructionItems", "items",
            )
            required = _items(raw_required)
            # Preserve explicit FIR restrictions; an absent flag means unknown.
            fir_flags = {}
            if isinstance(raw_required, list):
                for raw in raw_required:
                    if isinstance(raw, dict) and type(raw.get("foundInRaid")) is bool:
                        for normalized in _items([raw]):
                            fir_flags[normalized["id"]] = raw["foundInRaid"]
            item_rows = []
            for row in required:
                count = row.get("count")
                if type(count) not in (int, float) or count <= 0:
                    continue
                item_rows.append({
                    "id": row["id"],
                    "count": count,
                    "found_in_raid": fir_flags.get(row["id"]),
                })
            # Keep level conditions separate from item quantities; these
            # become explicit blocks in the later My PMC Hideout Planner.
            other = {}
            for target, keys in (
                ("station", ("stationLevelRequirements", "stationRequirements")),
                ("trader", ("traderRequirements",)),
                ("skill", ("skillRequirements",)),
            ):
                value = _first(entry, *keys)
                if isinstance(value, (list, dict)):
                    other[target] = value
            duration = _first(entry, "constructionTime", "duration", "constructionTimeSeconds")
            levels.append({
                "level": level,
                "items": item_rows,
                "other": other,
                "construction_time": duration if type(duration) is int and duration >= 0 else None,
            })
        if levels:
            # Keep the original translation key so metadata can be resolved
            # before the requirements enter the cache. Do not display keys.
            raw_name = _first(station, "name", "stationName", "title", "nameId")
            raw_name = raw_name.strip() if isinstance(raw_name, str) else ""
            readable = (
                raw_name if raw_name and not raw_name.startswith("hideout_area_")
                and not _valid_id(raw_name) else ""
            )
            result.append({
                "station_id": station_id,
                "name_key": raw_name,
                "station_name": readable,
                "levels": sorted(levels, key=lambda r: r["level"]),
            })
    if not result or not any(level["items"] for station in result for level in station["levels"]):
        first = records[0]
        levels = _levels(_first(first, "levels", "stationLevels", "upgrades"))
        level_keys = list(levels[0])[:16] if levels else []
        raise ValueError(f"Could not parse Hideout materials; station_keys={list(first)[:15]}, "
                         f"level_keys={level_keys}")
    return result


def index_hideout_items(stations: list[dict]) -> dict[str, list[dict]]:
    index = defaultdict(list)
    for station in stations:
        station_id = station["station_id"]
        station_name = station.get("station_name") or ""
        for level in station["levels"]:
            grouped = {}
            for entry in level["items"]:
                item_id = entry["id"]
                if item_id not in grouped:
                    grouped[item_id] = {"station_id": station_id,
                                        "station_name": station_name,
                                        "level": level["level"],
                                        "count": 0, "found_in_raid": None}
                grouped[item_id]["count"] += entry["count"]
                flag = entry.get("found_in_raid")
                if flag is True:
                    grouped[item_id]["found_in_raid"] = True
                elif flag is False and grouped[item_id]["found_in_raid"] is None:
                    grouped[item_id]["found_in_raid"] = False
            for item_id, entry in grouped.items():
                index[item_id].append(entry)
    for rows in index.values():
        rows.sort(key=lambda x: (x["station_id"], x["level"]))
    return dict(index)


def _read(path: Path) -> tuple[list[dict] | None, float]:
    try:
        if path.stat().st_size > CACHE_MAX_BYTES:
            return None, 0.0
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") != CACHE_VERSION or not isinstance(payload.get("stations"), list):
            return None, 0.0
        stamp = payload.get("fetched_at")
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
            return None, 0.0
        if not all(isinstance(x, dict) and "levels" in x and "station_id" in x
                   for x in payload["stations"]):
            return None, 0.0
        return payload["stations"], float(stamp)
    except (OSError, TypeError, AttributeError, ValueError):
        return None, 0.0


def _write(path: Path, stations: list[dict], timestamp: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps({"version": CACHE_VERSION, "fetched_at": timestamp,
                                   "stations": stations}, ensure_ascii=False,
                                  separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


class ItemHideoutRequirements:
    """Keep game-specific Hideout requirements isolated and cached."""
    def __init__(self, api, cache_dir: Path):
        self.api = api
        self.cache_dir = Path(cache_dir)
        self._stations: dict[str, list[dict]] = {}
        self._index: dict[str, dict[str, list[dict]]] = {}
        self._times: dict[str, float] = {}
        self._loading: set[str] = set()
        self._errors: dict[str, str] = {}
        self._listeners: dict[str, Callable[[], None]] = {}
        self._failed_at: dict[str, float] = {}
        for mode in MODES:
            records, stamp = _read(self._path(mode))
            if records is not None:
                self._set_data(mode, records, stamp)

    def _path(self, mode: str) -> Path:
        return self.cache_dir / f"item_hideout_requirements_{mode}.json"

    def _set_data(self, mode: str, stations: list[dict], timestamp: float) -> None:
        self._stations[mode] = stations
        self._index[mode] = index_hideout_items(stations)
        self._times[mode] = timestamp

    def ensure(self, mode: str, on_updated: Callable[[], None], force: bool = False) -> None:
        if mode not in MODES or mode in self._loading:
            return
        if not force and mode in self._stations and time.time() - self._times[mode] < CACHE_TTL:
            return
        if not force and time.time() - self._failed_at.get(mode, 0) < 60:
            return
        self._loading.add(mode)
        self._listeners[mode] = on_updated
        self._errors.pop(mode, None)
        url = f"{API_ROOT}/v2/{mode}/hideout"

        def finish(stations: list[dict] | None, error: str | None) -> None:
            self._loading.discard(mode)
            if error is None and stations is not None:
                stamp = time.time()
                self._set_data(mode, stations, stamp)
                self._failed_at.pop(mode, None)
                try:
                    _write(self._path(mode), stations, stamp)
                except OSError as exc:
                    print(f"Hideout cache warning: {exc}")
            else:
                self._errors[mode] = str(error or "Unknown Hideout data error")
                self._failed_at[mode] = time.time()
            callback = self._listeners.pop(mode, None)
            if callback is not None:
                callback()

        def apply_names(stations: list[dict], names: dict[str, str]) -> list[dict]:
            for station in stations:
                label = names.get(station["station_id"], "")
                if isinstance(label, str) and label.strip():
                    station["station_name"] = label.strip()
            return stations

        def receive_english(stations: list[dict], base: object, translations: object,
                            error: str | None) -> None:
            names = parse_station_names(base, translations) if error is None else {}
            # The translated mirror is authoritative. REST is used only for
            # missing English labels, never for construction requirements.
            missing = {station["station_id"] for station in stations
                       if not (names.get(station["station_id"]) or station.get("station_name"))}
            if not missing:
                finish(apply_names(stations, names), None)
                return

            def rest_received(rest: object, rest_error: str | None) -> None:
                if rest_error is None:
                    try:
                        rest_names = parse_station_names(rest)
                        for station_id in missing:
                            if station_id in rest_names:
                                names[station_id] = rest_names[station_id]
                    except (ValueError, TypeError):
                        pass
                # Requirements remain usable even when labels are unavailable.
                finish(apply_names(stations, names), None)

            self.api.get_json(f"{API_ROOT}/hideout?lang=en", rest_received)

        def received(data: object, error: str | None) -> None:
            if error is not None:
                finish(None, str(error))
                return
            try:
                stations = parse_hideout_requirements(data)
            except (ValueError, TypeError, KeyError) as exc:
                finish(None, str(exc))
                return

            self.api.get_json(
                f"{API_ROOT}/v2/{mode}/hideout_en",
                lambda english, err, records=stations, base=data: receive_english(
                    records, base, english, err
                ),
            )

        self.api.get_json(url, received)

    def status(self, mode: str) -> str:
        if mode in self._loading:
            return "refreshing" if mode in self._stations else "loading"
        if mode in self._stations:
            return "stale" if mode in self._errors else "ready"
        if mode in self._errors:
            return "error"
        return "empty"

    def for_item(self, mode: str, item_id: str) -> list[dict]:
        return self._index.get(mode, {}).get(item_id.lower(), [])

    def stations(self, mode: str) -> list[dict]:
        """Future My PMC integration: all levels and their requirements."""
        return self._stations.get(mode, [])

    def error(self, mode: str) -> str:
        return self._errors.get(mode, "")
