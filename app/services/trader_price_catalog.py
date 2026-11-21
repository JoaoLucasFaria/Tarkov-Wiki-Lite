"""Trader-only resale prices for the Items encyclopedia.

The compact local cache is built from tarkov.dev's public JSON mirror. A
background thread downloads the bulk data so the GUI is never blocked by it.
No Flea Market prices are read or used by this module.
"""

from __future__ import annotations

import gzip
import json
import math
import os
import time
import threading
from pathlib import Path
from urllib.request import Request, urlopen

from PySide6.QtCore import QObject, Signal, Slot


API_ROOT = "https://api.tarkov-stammtisch.de/api/v2"
CACHE_VERSION = 1
CACHE_TTL_SECONDS = 12 * 60 * 60
MAX_RESPONSE_BYTES = 24 * 1024 * 1024
VALID_MODES = {"regular", "pve"}


def _item_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 24
        and all(char in "0123456789abcdefABCDEF" for char in value)
    )


def _positive_price(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    rounded = int(value)
    return rounded if rounded > 0 else None


def _records(payload: object, collection: str) -> list[tuple[str | None, dict]]:
    """Read JSON API records from either ID-keyed objects or arrays.

    Supported responses include data.<collection>, <collection>, data and
    direct ID-keyed dictionaries/lists. Metadata entries are skipped later.
    Unexpected shapes raise a useful error instead of silently using basePrice.
    """
    value = payload
    if isinstance(value, dict) and "data" in value:
        value = value["data"]
    if isinstance(value, dict) and collection in value:
        value = value[collection]

    if isinstance(value, list):
        return [(None, record) for record in value if isinstance(record, dict)]

    if isinstance(value, dict):
        return [
            (key if isinstance(key, str) else None, record)
            for key, record in value.items()
            if isinstance(record, dict)
        ]

    root_keys = list(payload)[:8] if isinstance(payload, dict) else []
    raise ValueError(
        f"Unsupported {collection} response shape: "
        f"root={type(payload).__name__}, value={type(value).__name__}, "
        f"root_keys={root_keys!r}"
    )


def parse_trader_prices(items_payload: object, traders_payload: object) -> dict[str, list[dict]]:
    """Extract trader resale prices in RUB from the v2 JSON mirror.

    Handles array and ID-keyed dictionary collections. Never uses basePrice,
    flea market prices, buy offers or inferred prices.
    """
    items = _records(items_payload, "items")
    traders = _records(traders_payload, "traders")

    trader_names: dict[str, str] = {}
    for key, record in traders:
        trader_id = record.get("id") or key
        if not isinstance(trader_id, str) or not trader_id:
            continue
        slug = record.get("normalizedName")
        if not isinstance(slug, str) or not slug.strip():
            slug = record.get("name")
        if isinstance(slug, str) and slug.strip():
            trader_names[trader_id] = slug.replace("-", " ").title()

    result: dict[str, list[dict]] = {}
    for key, item in items:
        item_id = item.get("id") or key
        if not _item_id(item_id):
            continue
        raw_offers = item.get("sellToTrader")
        if not isinstance(raw_offers, list):
            continue

        by_trader: dict[str, int] = {}
        for offer in raw_offers:
            if not isinstance(offer, dict):
                continue
            trader_id = offer.get("trader")
            if isinstance(trader_id, dict):
                trader_id = trader_id.get("id")
            price = _positive_price(offer.get("priceRUB"))
            if not isinstance(trader_id, str) or price is None:
                continue
            name = trader_names.get(trader_id, f"Trader ({trader_id})")
            if name.casefold() in {"flea market", "flea-market"}:
                continue
            by_trader[name] = max(price, by_trader.get(name, 0))

        if by_trader:
            result[item_id.lower()] = [
                {"trader": trader, "price_rub": price}
                for trader, price in sorted(
                    by_trader.items(), key=lambda pair: (-pair[1], pair[0])
                )
            ]
    return result


def _fetch_json(url: str) -> object:
    request = Request(
        url,
        headers={
            "User-Agent": "TarkovWikiLite/0.2 (personal companion)",
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        },
    )
    with urlopen(request, timeout=65) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("Price API response exceeds safety limit")
        if response.headers.get("Content-Encoding", "").lower() == "gzip":
            raw = gzip.decompress(raw)
        if len(raw) > 75 * 1024 * 1024:
            raise ValueError("Decompressed JSON exceeds safety limit")
    return json.loads(raw)


def save_price_cache(path: Path, prices: dict[str, list[dict]], fetched_at: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_text(
            json.dumps(
                {"version": CACHE_VERSION, "fetched_at": fetched_at, "prices": prices},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def load_price_cache(path: Path) -> tuple[dict[str, list[dict]], float]:
    try:
        if path.stat().st_size > 8 * 1024 * 1024:
            return {}, 0.0
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("version") != CACHE_VERSION:
            return {}, 0.0
        prices = payload.get("prices")
        timestamp = payload.get("fetched_at", 0)
        if not isinstance(prices, dict) or not isinstance(timestamp, (int, float)):
            return {}, 0.0
        clean: dict[str, list[dict]] = {}
        for item_id, entries in prices.items():
            if not _item_id(item_id) or not isinstance(entries, list):
                continue
            normalized = []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                price = _positive_price(entry.get("price_rub"))
                trader = entry.get("trader")
                if price and isinstance(trader, str) and trader:
                    normalized.append({"trader": trader, "price_rub": price})
            if normalized:
                clean[item_id.lower()] = sorted(
                    normalized, key=lambda record: -record["price_rub"]
                )
        return clean, float(timestamp)
    except (OSError, ValueError, TypeError, OverflowError):
        return {}, 0.0


def _download_in_background(mode: str, destination: Path, notify) -> None:
    """Daemon worker; no QObject or GUI methods are called on this thread."""
    try:
        traders = _fetch_json(f"{API_ROOT}/{mode}/traders")
        items = _fetch_json(f"{API_ROOT}/{mode}/items")
        prices = parse_trader_prices(items, traders)
        if len(prices) < 200:
            raise ValueError(
                f"Only {len(prices)} items with trader prices; API schema may have changed"
            )
        fetched_at = time.time()
        save_price_cache(destination, prices, fetched_at)
        notify(mode, prices, fetched_at, "")
    except Exception as error:
        notify(mode, {}, 0.0, str(error))


class TraderPriceCatalog(QObject):
    """Tiny per-mode cache and lazy asynchronous refresh of trader sell prices."""

    updated = Signal(str)
    _loaded = Signal(str, object, float, str)

    def __init__(self, cache_dir: Path, parent: QObject | None = None):
        super().__init__(parent)
        self.cache_dir = cache_dir
        self._prices: dict[str, dict[str, list[dict]]] = {}
        self._timestamps: dict[str, float] = {}
        self._errors: dict[str, str] = {}
        self._loading: set[str] = set()
        self._threads: dict[str, threading.Thread] = {}
        self._loaded.connect(self._on_loaded)
        for mode in VALID_MODES:
            cached, timestamp = load_price_cache(self._path(mode))
            if cached:
                self._prices[mode] = cached
                self._timestamps[mode] = timestamp

    def _path(self, mode: str) -> Path:
        return self.cache_dir / f"trader_sell_prices_{mode}.json"

    def ensure(self, mode: str, force: bool = False) -> None:
        """Start a refresh only if needed; returns without waiting."""
        if mode not in VALID_MODES or mode in self._loading:
            return
        age = time.time() - self._timestamps.get(mode, 0)
        if not force and self._prices.get(mode) and age < CACHE_TTL_SECONDS:
            return
        # Don't repeatedly retry failed downloads while the user re-renders.
        if not force and mode in self._errors:
            return
        self._errors.pop(mode, None)
        self._loading.add(mode)
        worker = threading.Thread(
            target=_download_in_background,
            args=(mode, self._path(mode), self._notify_from_worker),
            daemon=True,
            name=f"TarkovTraderPrices-{mode}",
        )
        self._threads[mode] = worker
        worker.start()

    def _notify_from_worker(
        self, mode: str, prices: dict[str, list[dict]], timestamp: float, error: str
    ) -> None:
        # Qt queues delivery to this QObject's GUI thread.
        try:
            self._loaded.emit(mode, prices, timestamp, error)
        except RuntimeError:
            # The application may have closed while the request was running.
            pass

    @Slot(str, object, float, str)
    def _on_loaded(self, mode: str, prices: object, timestamp: float, error: str) -> None:
        self._loading.discard(mode)
        self._threads.pop(mode, None)
        if error:
            self._errors[mode] = error
        elif isinstance(prices, dict):
            self._prices[mode] = prices
            self._timestamps[mode] = timestamp
            self._errors.pop(mode, None)
        self.updated.emit(mode)

    def offers_for(self, mode: str, item_id: str) -> list[dict]:
        return self._prices.get(mode, {}).get(item_id.lower(), [])

    def is_loading(self, mode: str) -> bool:
        return mode in self._loading

    def has_prices(self, mode: str) -> bool:
        return bool(self._prices.get(mode))

    def fetched_at(self, mode: str) -> float:
        return self._timestamps.get(mode, 0.0)

    def error(self, mode: str) -> str | None:
        return self._errors.get(mode)
