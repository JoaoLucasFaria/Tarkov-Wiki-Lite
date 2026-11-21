"""Offline GUI smoke test for the Items page (no HTTP requests)."""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl
from unittest.mock import patch

from app.services.trader_price_catalog import TraderPriceCatalog
from PySide6.QtWidgets import QApplication

from app.ui.items_page import ItemsPage

ITEM_ID = "590a3efd86f77437d351a25b"
QUEST_ID = "5ae4493486f7744efa289417"


class FakeApi:
    def get_json(self, url, callback):
        if f"/items/{ITEM_ID}?" in url:
            callback({
                "id": ITEM_ID,
                "name": "Gas analyzer",
                "description": "A measuring device.",
                "basePrice": 21697,
                "width": 1,
                "height": 2,
            }, None)
        else:
            callback({
                "data": [{"id": ITEM_ID, "name": "Gas analyzer"}],
                "meta": {"total": 1},
            }, None)


class FakeCache:
    def load_tasks(self, mode):
        if mode == "pve":
            return []
        return [{
            "id": QUEST_ID,
            "name": "Offline Test Quest",
            "objectives": [
                {
                    "id": "Find two",
                    "type": "findItem",
                    "items": [ITEM_ID],
                    "count": 2,
                    "optional": True,
                    "foundInRaid": False,
                },
                {
                    "id": "Hand over two",
                    "type": "giveItem",
                    "items": [ITEM_ID],
                    "count": 2,
                    "optional": False,
                    "foundInRaid": False,
                },
            ],
        }]


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    opened = []
    page = ItemsPage(
        FakeApi(), FakeCache(), open_quest=lambda q, m: opened.append((q, m))
    )
    # Keep this GUI smoke test strictly offline: no full JSON price download.
    with patch.object(TraderPriceCatalog, "ensure", return_value=None):
        page.ensure_loaded()

        assert page.items_list.count() == 1, "Item search failed"
        assert page.browser.selected_item["name"] == "Gas analyzer", "Details failed"
        assert "Direct mandatory total (preliminary): 2" in page.details.toPlainText(), (
            "Quest requirements failed"
        )
        page._open_link(QUrl(f"quest://{QUEST_ID}"))
        assert opened == [(QUEST_ID, "regular")], "Quest navigation failed"

        page.set_mode("pve")
        assert "No quest requirements" in page.details.toPlainText(), "PvE mode failed"

    page.deleteLater()
    app.processEvents()
    print("PASS: Item search")
    print("PASS: Item details")
    print("PASS: Quest requirements without double counting")
    print("PASS: Clickable quest link")
    print("PASS: PvP / PvE requirement switch")
    print("All Items page smoke tests passed!")


if __name__ == "__main__":
    main()
