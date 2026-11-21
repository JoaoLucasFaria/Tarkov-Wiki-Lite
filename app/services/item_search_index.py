"""Compact, asynchronously downloaded index for item name/short-name search.

The REST search endpoint documents names and normalized names, but it does
not guarantee matching the separate `shortName` field.  Download only the
small, paginated item-list records, retain four fields, and cache locally.
No full item details or images are stored in this index.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urlencode


ITEMS_URL = "https://api.tarkov-stammtisch.de/api/items"
ITEM_ID_RE = re.compile(r"^[0-9a-fA-F]{24}$")
CACHE_VERSION = 1
PAGE_SIZE = 500
MAX_PAGES = 40
CACHE_MAX_AGE = 7 * 24 * 60 * 60
MAX_CACHE_BYTES = 8 * 1024 * 1024


def _compact_item(raw: object) -> dict | None:
    """Keep only fields needed to search and show list rows."""
    if not isinstance(raw, dict):
        return None
    item_id = raw.get("id")
    name = raw.get("name")
    if not isinstance(item_id, str) or not ITEM_ID_RE.fullmatch(item_id):
        return None
    if not isinstance(name, str) or not name.strip():
        return None

    short_name = raw.get("shortName")
    category = raw.get("category")
    category_name = category.get("name") if isinstance(category, dict) else None
    return {
        "id": item_id.lower(),
        "name": name,
        "shortName": short_name if isinstance(short_name, str) else "",
        "category": (
            {"name": category_name}
            if isinstance(category_name, str) else None
        ),
    }


class ItemSearchIndex:
    """Create an on-disk search index without blocking the Qt event loop."""

    def __init__(self, api, cache_path: Path) -> None:
        self.api = api
        self.cache_path = Path(cache_path)
        self.items: list[dict] = []
        self.ready = False
        self.stale = False
        self.loading = False
        self.error: str | None = None
        self.pages_loaded = 0
        self._working: list[dict] = []
        self._working_ids: set[str] = set()
        self._callback = None
        self._load_cache()

    def _load_cache(self) -> None:
        try:
            if self.cache_path.stat().st_size > MAX_CACHE_BYTES:
                return
            document = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if not isinstance(document, dict) or document.get("version") != CACHE_VERSION:
                return
            rows = document.get("items")
            if not isinstance(rows, list) or len(rows) > 20000:
                return
            items = [_compact_item(row) for row in rows]
            if len(items) != len(rows) or not items:
                return
            self.items = items
            self.ready = True
            self.stale = (
                time.time() - self.cache_path.stat().st_mtime > CACHE_MAX_AGE
            )
        except (OSError, ValueError, TypeError):
            return

    def ensure_ready(self, on_updated, force: bool = False) -> None:
        """Build the index once, or update it after the on-disk cache expires."""
        if self.loading:
            return
        if self.ready and not self.stale and not force:
            return
        if self.error is not None and not force:
            return

        self.loading = True
        self.error = None
        self.pages_loaded = 0
        self._working = []
        self._working_ids = set()
        self._callback = on_updated
        self._request_page(0)

    def _request_page(self, offset: int) -> None:
        params = urlencode({
            "lang": "en", "limit": PAGE_SIZE, "offset": offset
        })
        self.api.get_json(
            f"{ITEMS_URL}?{params}",
            lambda data, error: self._on_page(offset, data, error),
        )

    def _on_page(self, offset: int, data: object, error: str | None) -> None:
        if error is not None:
            self._fail(f"Item index download failed: {error}")
            return
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            self._fail("Unexpected item index response")
            return

        page = data["data"]
        for raw in page:
            item = _compact_item(raw)
            if item is None or item["id"] in self._working_ids:
                continue
            self._working_ids.add(item["id"])
            self._working.append(item)

        self.pages_loaded += 1
        meta = data.get("meta")
        total = meta.get("total") if isinstance(meta, dict) else None
        next_offset = offset + len(page)
        reached_end = (
            not page
            or len(page) < PAGE_SIZE
            or (type(total) is int and next_offset >= total)
        )
        if reached_end:
            self._complete()
        elif self.pages_loaded >= MAX_PAGES:
            self._fail("Item index exceeded the safe page limit")
        else:
            self._request_page(next_offset)

    def _complete(self) -> None:
        self.loading = False
        if not self._working:
            self._fail("The API returned an empty item index")
            return
        self.items = self._working
        self.ready = True
        self.stale = False
        self.error = None
        self._working = []
        self._working_ids.clear()
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.cache_path.with_suffix(".tmp")
            tmp_path.write_text(
                json.dumps({"version": CACHE_VERSION, "items": self.items},
                           ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            tmp_path.replace(self.cache_path)
        except OSError as exc:
            # The index still works during this session without disk caching.
            print(f"Item search index cache warning: {exc}")
        self._notify()

    def _fail(self, message: str) -> None:
        self.loading = False
        self.error = message
        self._working = []
        self._working_ids.clear()
        print(f"Item search index warning: {message}")
        self._notify()

    def _notify(self) -> None:
        callback = self._callback
        self._callback = None
        if callback is not None:
            callback()


def normalize_search(text: str) -> str:
    """Search without case, punctuation or whitespace differences."""
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def search_index(items: list[dict], query: str) -> list[dict]:
    """Match and rank both `name` and `shortName`. No API requests."""
    needle = normalize_search(query)
    if not needle:
        return items[:]

    ranked: list[tuple[int, str, dict]] = []
    for item in items:
        name = normalize_search(str(item.get("name") or ""))
        short = normalize_search(str(item.get("shortName") or ""))
        if needle == name:
            rank = 0
        elif needle == short:
            rank = 1
        elif name.startswith(needle):
            rank = 2
        elif short.startswith(needle):
            rank = 3
        elif needle in name:
            rank = 4
        elif needle in short:
            rank = 5
        else:
            continue
        ranked.append((rank, str(item.get("name") or "").casefold(), item))
    ranked.sort(key=lambda value: (value[0], value[1]))
    return [item for _rank, _name, item in ranked]
