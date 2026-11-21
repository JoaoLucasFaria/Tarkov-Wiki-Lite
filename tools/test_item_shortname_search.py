"""Offline tests for Items search by full name and short name.

Run from the project root:
    python -m tools.test_item_shortname_search
"""

import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlsplit

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.services.item_browser import ItemBrowser
from app.ui.items_page import ItemsPage


GAS = "590a3efd86f77437d351a25b"
EXAMPLE = "588892092459774ac91d4b11"


class FakeApi:
    """Emulates API pages and a server that does NOT search short names."""

    def __init__(self):
        self.urls = []
        self.rows = [
            {
                "id": GAS,
                "name": "Gas analyzer",
                "shortName": "GasAn",
                "category": {"name": "Electronics"},
            },
            {
                "id": EXAMPLE,
                "name": "An unrelated example item",
                "shortName": "SECRET-ALIAS",
                "category": {"name": "Miscellaneous"},
            },
        ]
        # Extra records verify pagination and short-name matching.
        for n in range(61):
            self.rows.append({
                "id": f"{n+300:024x}",
                "name": f"Example row {n:02d}",
                "shortName": f"TestPrefix-{n:02d}",
                "category": {"name": "Test"},
            })

    def get_json(self, url, callback):
        self.urls.append(url)
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)
        if parsed.path.endswith("/items"):
            query = params.get("search", [None])[0]
            limit = int(params.get("limit", [100])[0])
            offset = int(params.get("offset", [0])[0])
            if query is None:
                # Initial complete catalog, delivered in a single API page.
                rows = self.rows
            else:
                # Intentionally emulate a remote search that ignores shortName.
                rows = [
                    item for item in self.rows
                    if query.casefold() in item["name"].casefold()
                ]
            callback({"data": rows[offset:offset+limit],
                      "meta": {"total": len(rows)}}, None)
            return
        if parsed.path.endswith(f"/items/{GAS}"):
            callback({**self.rows[0], "description": "Test item"}, None)
            return
        if parsed.path.endswith(f"/items/{EXAMPLE}"):
            callback({**self.rows[1], "description": "Test item"}, None)
            return
        callback(None, "Unknown test URL")


class FakeCache:
    def load_tasks(self, mode):
        return []


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    with TemporaryDirectory() as temp:
        api = FakeApi()
        path = Path(temp) / "items_search_index_en.json"
        browser = ItemBrowser(api, cache_path=path)

        browser.search_items("gas analyzer", lambda: None)
        assert [x["id"] for x in browser.results] == [GAS]
        print("PASS: Search by full name")

        browser.search_items("GASAN", lambda: None)
        assert [x["id"] for x in browser.results] == [GAS]
        browser.search_items("secret-alias", lambda: None)
        assert [x["id"] for x in browser.results] == [EXAMPLE]
        print("PASS: Search by shortName even when API ignores it")

        browser.search_items("testprefix", lambda: None)
        assert browser.meta["total"] == 61
        assert len(browser.results) == 30
        browser.search_items("testprefix", lambda: None, offset=30)
        assert len(browser.results) == 30
        browser.search_items("testprefix", lambda: None, offset=60)
        assert len(browser.results) == 1
        print("PASS: Pagination after combined name/shortName search")

        assert path.is_file(), "Index should be cached on disk"
        assert any(
            "limit=500" in url and "search=" not in url
            for url in api.urls
        ), "The API must be paged for compact index creation"
        requests_before = len(api.urls)
        new_browser = ItemBrowser(api, cache_path=path)
        new_browser.search_items("secret-alias", lambda: None)
        assert new_browser.results[0]["id"] == EXAMPLE
        assert len(api.urls) == requests_before, "Cached search made an HTTP request"
        print("PASS: Local compact cache avoids repeat downloads")

        # Verify index pagination across more than one API request.
        bulk_api = FakeApi()
        for n in range(501):
            bulk_api.rows.append({
                "id": f"{n+1000:024x}",
                "name": f"Large catalog {n}",
                "shortName": f"BIGALIAS{n:03d}",
                "category": {"name": "Test"},
            })
        bulk_browser = ItemBrowser(
            bulk_api, cache_path=Path(temp) / "large_index.json"
        )
        bulk_browser.search_items("BIGALIAS500", lambda: None)
        assert [x["shortName"] for x in bulk_browser.results] == [
            "BIGALIAS500"
        ]
        bulk_calls = [
            url for url in bulk_api.urls
            if "limit=500" in url and "search=" not in url
        ]
        assert len(bulk_calls) >= 2, "Index must fetch all API pages"
        print("PASS: Multi-page index creation and short-name search")

        # Exercise the integrated Items GUI, including selected-item details.
        page = ItemsPage(api, FakeCache())
        page.browser = new_browser
        page.ensure_loaded()
        page.search_input.setText("secret-alias")
        page.search_timer.stop()
        page._start_search()
        assert page.items_list.count() == 1
        assert page.items_list.currentItem().text().startswith(
            "An unrelated example item"
        )
        assert "SECRET-ALIAS" in page.items_list.currentItem().text()
        print("PASS: Items UI displays shortName and filters correctly")
        page.deleteLater()
        app.processEvents()
    print("All name/shortName search tests passed!")


if __name__ == "__main__":
    main()
