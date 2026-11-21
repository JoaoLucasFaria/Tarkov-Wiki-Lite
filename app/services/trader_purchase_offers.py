"""Lazy cash purchases and barter costs offered by Tarkov traders.

Distinct from trader_price_catalog: this module answers 'what must the PLAYER
PAY TO BUY this item from a trader?', not 'what will a trader pay the player?'.
No Flea Market prices, base values or player data are used.
"""
from __future__ import annotations

import json
import os
import time
from collections import OrderedDict
from pathlib import Path
from typing import Callable
from urllib.parse import quote

API_ROOT = "https://api.tarkov-stammtisch.de/api"
CURRENCY = {
    "5449016a4bdc2d6f028b456f": "₽",
    "5696686a4bdc2da3298b456a": "$",
    "569668774bdc2da2298b4568": "€",
}
MODES = {"regular": "eft", "pve": "pve"}
CACHE_VERSION = 1
CACHE_TTL = 10 * 60
MAX_CACHE_BYTES = 120_000
MAX_MEMORY_ITEMS = 32
ERROR_COOLDOWN = 45


def valid_id(value: object) -> bool:
    return isinstance(value, str) and len(value) == 24 and all(
        c in "0123456789abcdefABCDEF" for c in value
    )


def _positive_count(raw: object) -> float | int | None:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    if raw <= 0 or raw > 1e12:
        return None
    return int(raw) if raw == int(raw) else float(raw)


def parse_trader_offers(payload: object, item_id: str, mode: str) -> list[dict]:
    """Read live per-item REST offers, preserving exact cost requirements.

    `itemsCost` and `summaryCost` are not assumed to be cash prices. Their
    meanings vary by offer and can represent aggregate values or conversions.
    """
    if mode not in MODES or not valid_id(item_id):
        raise ValueError("Invalid mode or item ID")
    if not isinstance(payload, dict) or not isinstance(payload.get("offers"), list):
        raise ValueError("Unexpected trader offers response (missing offers list)")
    game_type = payload.get("gameType")
    if game_type and str(game_type).lower() not in (MODES[mode], "regular" if mode == "regular" else "pve"):
        raise ValueError(f"Trader offers belong to wrong mode: {game_type}")
    item_data = payload.get("item")
    if isinstance(item_data, dict) and valid_id(item_data.get("id")):
        if item_data["id"].lower() != item_id.lower():
            raise ValueError("Trader offers response is for another item")

    offers = []
    for row in payload["offers"]:
        if not isinstance(row, dict):
            continue
        if valid_id(row.get("itemTpl")) and row["itemTpl"].lower() != item_id.lower():
            continue
        trader_name = row.get("traderName")
        if not isinstance(trader_name, str) or not trader_name.strip():
            trader_name = "Unknown trader"
        raw_requirements = row.get("requirements")
        if not isinstance(raw_requirements, list) or not raw_requirements:
            # An unpriced offer must never be displayed as free or absent.
            raise ValueError("Trader offer is missing required payment details")
        requirements = []
        cash_only = True
        for part in raw_requirements:
            if not isinstance(part, dict):
                cash_only = False
                continue
            tpl = part.get("_tpl", part.get("itemId", ""))
            tpl = tpl.lower() if valid_id(tpl) else ""
            amount = _positive_count(part.get("count"))
            req_type = str(part.get("type") or "").strip()
            level = part.get("level")
            level = level if type(level) is int and level >= 0 else None
            side = str(part.get("side") or "").strip()
            currency = CURRENCY.get(tpl) if req_type in ("", "ItemRequirement") else None
            if not currency or amount is None:
                cash_only = False
            requirements.append({
                "item_id": tpl,
                "count": amount,
                "type": req_type,
                "currency": currency,
                "level": level,
                "side": side[:32],
            })
        if not requirements:
            raise ValueError("Trader offer contains no readable payment entries")
        ll = row.get("loyaltyLevel")
        pmc = row.get("minTraderLevel")
        stack = row.get("stackCount")
        limit = row.get("buyRestrictionMax")
        offers.append({
            "trader": trader_name.strip()[:100],
            "trader_id": row.get("traderId", "") if valid_id(row.get("traderId")) else "",
            "loyalty": ll if type(ll) is int and ll > 0 else None,
            "pmc_level": pmc if type(pmc) is int and pmc > 0 else None,
            "stack_count": stack if type(stack) is int and stack > 0 else 1,
            "buy_limit": limit if type(limit) is int and limit > 0 else None,
            "cash_only": cash_only,
            "requirements": requirements,
        })
    offers.sort(key=lambda x: (not x["cash_only"], x["trader"].casefold(), x["loyalty"] or 0))
    return offers


def _read_cache(path: Path) -> tuple[list[dict] | None, float]:
    try:
        if path.stat().st_size > MAX_CACHE_BYTES:
            return None, 0.0
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != CACHE_VERSION or not isinstance(data.get("offers"), list):
            return None, 0.0
        stamp = data.get("fetched_at", 0)
        if isinstance(stamp, bool) or not isinstance(stamp, (float, int)):
            return None, 0.0
        if not all(isinstance(x, dict) and "requirements" in x for x in data["offers"]):
            return None, 0.0
        return data["offers"], float(stamp)
    except (OSError, ValueError, TypeError, AttributeError):
        return None, 0.0


def _write_cache(path: Path, offers: list[dict], timestamp: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        temp.write_text(
            json.dumps({"version": CACHE_VERSION, "fetched_at": timestamp, "offers": offers},
                       separators=(",", ":"), ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


class TraderPurchaseOffers:
    """On-demand per-item fetch via existing TarkovApi.get_json callback."""

    def __init__(self, api, cache_dir: Path):
        self.api = api
        self.cache_dir = Path(cache_dir)
        self._data: OrderedDict[tuple[str, str], list[dict]] = OrderedDict()
        self._timestamps: dict[tuple[str, str], float] = {}
        self._loading: set[tuple[str, str]] = set()
        self._errors: dict[tuple[str, str], str] = {}
        self._failed_at: dict[tuple[str, str], float] = {}
        self._listeners: dict[tuple[str, str], Callable[[], None]] = {}

    def _path(self, key: tuple[str, str]) -> Path:
        mode, item_id = key
        return self.cache_dir / "trader_purchase_offers" / mode / f"{item_id}.json"

    def _set_data(self, key: tuple[str, str], offers: list[dict], timestamp: float) -> None:
        self._data[key] = offers
        self._data.move_to_end(key)
        self._timestamps[key] = timestamp
        while len(self._data) > MAX_MEMORY_ITEMS:
            old_key, _ = self._data.popitem(last=False)
            self._timestamps.pop(old_key, None)

    def ensure(self, mode: str, item_id: str, on_updated: Callable[[], None], force=False) -> None:
        if mode not in MODES or not valid_id(item_id):
            return
        key = (mode, item_id.lower())
        self._listeners[key] = on_updated
        if key not in self._data:
            cached, stamp = _read_cache(self._path(key))
            if cached is not None:
                self._set_data(key, cached, stamp)
        if key in self._loading:
            return
        now = time.time()
        if not force and key in self._data and now - self._timestamps[key] < CACHE_TTL:
            return
        if not force and now - self._failed_at.get(key, 0) < ERROR_COOLDOWN:
            return
        self._loading.add(key)
        self._errors.pop(key, None)
        url = f"{API_ROOT}/traders/offers/item/{quote(item_id.lower())}?game={MODES[mode]}&lang=en"

        def received(data, error):
            self._loading.discard(key)
            if error is None:
                try:
                    offers = parse_trader_offers(data, item_id, mode)
                except (ValueError, TypeError, KeyError) as exc:
                    error = str(exc)
            if error is None:
                stamp = time.time()
                self._set_data(key, offers, stamp)
                self._failed_at.pop(key, None)
                try:
                    _write_cache(self._path(key), offers, stamp)
                except OSError as exc:
                    print(f"Purchase offer cache warning: {exc}")
            else:
                self._errors[key] = str(error)
                self._failed_at[key] = time.time()
            callback = self._listeners.pop(key, None)
            if callback is not None:
                callback()

        self.api.get_json(url, received)

    def status(self, mode: str, item_id: str) -> str:
        key = (mode, item_id.lower())
        if key in self._loading:
            return "refreshing" if key in self._data else "loading"
        if key in self._data:
            return "stale" if key in self._errors else "ready"
        if key in self._errors:
            return "error"
        return "empty"

    def offers_for(self, mode: str, item_id: str) -> list[dict]:
        return self._data.get((mode, item_id.lower()), [])

    def error(self, mode: str, item_id: str) -> str:
        return self._errors.get((mode, item_id.lower()), "")

    def fetched_at(self, mode: str, item_id: str) -> float:
        return self._timestamps.get((mode, item_id.lower()), 0.0)
