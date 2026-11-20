
"""Lightweight item name lookup with local caching."""

import json
import string
from pathlib import Path

from app.services.tarkov_api import TarkovApi


ITEM_API_URL = "https://api.tarkov-stammtisch.de/api/items"


class ItemCatalog:
    """Resolve item IDs into English names on demand."""

    def __init__(
        self,
        api: TarkovApi,
        cache_path: Path,
    ) -> None:
        self.api = api
        self.cache_path = cache_path
        self.names: dict[str, str] = {}
        self.pending: set[str] = set()
        self.failed: set[str] = set()

        self._load_cache()

    def _load_cache(self) -> None:
        try:
            data = json.loads(
                self.cache_path.read_text(encoding="utf-8")
            )

            if isinstance(data, dict):
                self.names = {
                    key: value
                    for key, value in data.items()
                    if isinstance(key, str)
                    and isinstance(value, str)
                }

        except (OSError, ValueError):
            self.names = {}

    def _save_cache(self) -> None:
        try:
            self.cache_path.parent.mkdir(
                parents=True, exist_ok=True
            )

            self.cache_path.write_text(
                json.dumps(self.names, ensure_ascii=False),
                encoding="utf-8",
            )

        except OSError as error:
            print(f"Item cache warning: {error}")

    def ensure_names(
        self,
        item_ids: set[str],
        on_updated,
    ) -> None:
        """Request missing names without blocking the interface."""

        for item_id in item_ids:
            if (
                item_id in self.names
                or item_id in self.pending
                or item_id in self.failed
            ):
                continue

            # Accept only standard Tarkov item IDs
            if (
                len(item_id) != 24
                or any(c not in string.hexdigits for c in item_id)
            ):
                continue

            self.pending.add(item_id)

            url = f"{ITEM_API_URL}/{item_id}?lang=en"

            self.api.get_json(
                url,
                lambda data, error, iid=item_id:
                    self._on_item_loaded(
                        iid, data, error, on_updated
                    ),
            )

    def _on_item_loaded(
        self,
        item_id: str,
        data: object,
        error: str | None,
        on_updated,
    ) -> None:
        self.pending.discard(item_id)

        if (
            error is None
            and isinstance(data, dict)
            and isinstance(data.get("name"), str)
            and data["name"]
        ):
            self.names[item_id] = data["name"]
            self._save_cache()
        else:
            self.failed.add(item_id)
            print(f"Could not resolve item {item_id}: {error}")

        on_updated()
