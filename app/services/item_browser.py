
"""Lightweight asynchronous item search and detail loading."""

import re
from pathlib import Path
from collections import OrderedDict
from urllib.parse import urlencode

from app.services.tarkov_api import TarkovApi
from app.services.item_search_index import ItemSearchIndex, search_index


ITEM_API_URL = "https://api.tarkov-stammtisch.de/api/items"
ITEM_ID_PATTERN = re.compile(r"^[0-9a-fA-F]{24}$")


class ItemBrowser:
    """Browse Tarkov items without downloading the full catalog."""

    PAGE_SIZE = 30
    DETAIL_CACHE_SIZE = 24

    def __init__(self, api: TarkovApi, cache_path: Path | None = None) -> None:
        self.api = api
        self.index = ItemSearchIndex(api, cache_path) if cache_path else None
        self._search_callback = None

        self.results: list[dict] = []
        self.meta: dict = {}
        self.query = ""
        self.offset = 0
        self.limit = self.PAGE_SIZE
        self.searching = False
        self.search_error: str | None = None

        self.selected_item_id: str | None = None
        self.selected_item: dict | None = None
        self.details_loading = False
        self.details_error: str | None = None

        self._search_request = 0
        self._detail_request = 0
        self._detail_cache: OrderedDict[str, dict] = (
            OrderedDict()
        )

    def search_items(
        self,
        query: str,
        on_updated,
        offset: int = 0,
    ) -> None:
        """Search one page of items asynchronously."""

        self.query = query.strip()
        self.offset = max(0, offset)

        self._search_request += 1
        request_id = self._search_request

        self.results = []
        self.meta = {}
        self.search_error = None
        self.searching = True
        self._search_callback = on_updated
        on_updated()

        if self.query and self.index is not None:
            if self.index.ready:
                self._local_search(on_updated)
                if self.index.stale:
                    self.index.ensure_ready(self._on_index_updated)
                return
            # Until the compact index is built, retain the normal API search.
            # The index is fetched asynchronously and covers shortName too.
            if len(self.query) >= 2:
                self.index.ensure_ready(self._on_index_updated)
                if self.index.ready:
                    self._local_search(on_updated)
                    return

        params = {
            "lang": "en",
            "limit": self.limit,
            "offset": self.offset,
        }

        if self.query:
            params["search"] = self.query

        url = f"{ITEM_API_URL}?{urlencode(params)}"

        self.api.get_json(
            url,
            lambda data, error: self._on_search_loaded(
                request_id,
                data,
                error,
                on_updated,
            ),
        )

    def _on_search_loaded(
        self,
        request_id: int,
        data: object,
        error: str | None,
        on_updated,
    ) -> None:
        # Ignore responses from older searches.
        if request_id != self._search_request:
            return

        # A completed index has more complete matching than the remote search.
        if self.query and self.index is not None and self.index.ready:
            self._local_search(on_updated)
            return

        self.searching = False

        if error is not None:
            self.search_error = str(error)

        elif isinstance(data, dict) and isinstance(
            data.get("data"), list
        ):
            self.results = [
                item
                for item in data["data"]
                if isinstance(item, dict)
            ]

            if isinstance(data.get("meta"), dict):
                self.meta = data["meta"]

        else:
            self.search_error = "Unexpected item search response."

        on_updated()

    def _local_search(self, on_updated) -> None:
        """Search names and short names using the compact cached index."""
        if self.index is None or not self.index.ready:
            return
        matches = search_index(self.index.items, self.query)
        self.results = matches[self.offset:self.offset + self.limit]
        self.meta = {"total": len(matches)}
        self.searching = False
        self.search_error = None
        on_updated()

    def _on_index_updated(self) -> None:
        """Refresh visible results after the one-time index download."""
        callback = self._search_callback
        if callback is None or self.index is None:
            return
        if self.query and self.index.ready:
            self._local_search(callback)
        else:
            # Name search remains available even if index building failed.
            callback()

    def load_item_details(
        self,
        item_id: str,
        on_updated,
    ) -> None:
        """Load one item's details, using a small memory cache."""

        self._detail_request += 1
        request_id = self._detail_request

        self.selected_item_id = item_id
        self.selected_item = None
        self.details_error = None
        self.details_loading = False

        if not ITEM_ID_PATTERN.fullmatch(item_id):
            self.details_error = "Invalid item ID."
            on_updated()
            return

        if item_id in self._detail_cache:
            self._detail_cache.move_to_end(item_id)
            self.selected_item = self._detail_cache[item_id]
            on_updated()
            return

        self.details_loading = True
        on_updated()

        url = f"{ITEM_API_URL}/{item_id}?lang=en"

        self.api.get_json(
            url,
            lambda data, error: self._on_details_loaded(
                request_id,
                item_id,
                data,
                error,
                on_updated,
            ),
        )

    def _on_details_loaded(
        self,
        request_id: int,
        item_id: str,
        data: object,
        error: str | None,
        on_updated,
    ) -> None:
        # Avoid showing details of a previously selected item.
        if request_id != self._detail_request:
            return

        self.details_loading = False

        if error is not None:
            self.details_error = str(error)

        elif (
            isinstance(data, dict)
            and data.get("id") == item_id
        ):
            self.selected_item = data
            self._detail_cache[item_id] = data
            self._detail_cache.move_to_end(item_id)

            while len(self._detail_cache) > self.DETAIL_CACHE_SIZE:
                self._detail_cache.popitem(last=False)

        else:
            self.details_error = "Unexpected item details response."

        on_updated()

