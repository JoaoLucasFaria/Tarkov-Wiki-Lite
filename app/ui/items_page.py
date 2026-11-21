"""Lightweight item encyclopedia page for Tarkov Wiki Lite.

This page never interacts with the game. Item data comes from the public API;
quest requirements are read from the existing local PvP/PvE quest caches.
"""

from __future__ import annotations

import html
from datetime import datetime
from collections import OrderedDict
from pathlib import Path
from collections.abc import Callable
from urllib.parse import urlparse

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.services.item_browser import ItemBrowser
from app.services.trader_price_catalog import TraderPriceCatalog
from app.services.trader_purchase_offers import TraderPurchaseOffers
from app.services.item_recipe_catalog import ItemRecipeCatalog, resolve_recipe_source_name
from app.services.item_hideout_requirements import ItemHideoutRequirements
from app.services.item_image_decoder import decode_item_pixmap
from app.services.item_requirements import extract_item_requirements
from app.services.item_requirement_summary import (
    get_item_requirements,
    summarize_quest_requirements,
)


IMAGE_LIMIT_BYTES = 3 * 1024 * 1024
IMAGE_CACHE_SIZE = 12
IMAGE_TARGET_SIZE = 144


def esc(value: object) -> str:
    """Escape dynamic values for insertion into QTextBrowser HTML."""
    return html.escape(str(value), quote=True)


class ItemsPage(QWidget):
    """Item search, item details and general quest requirements."""

    def __init__(
        self,
        api,
        cache,
        initial_mode: str = "regular",
        open_quest: Callable[[str, str], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.api = api
        self.cache = cache
        self.browser = ItemBrowser(
            api,
            cache_path=Path(__file__).resolve().parents[2]
            / "cache" / "items_search_index_en.json",
        )
        self.open_quest = open_quest
        self.trader_prices = TraderPriceCatalog(
            Path(__file__).resolve().parents[2] / "cache", self
        )
        self.trader_prices.updated.connect(self._on_trader_prices_updated)
        self.purchase_offers = TraderPurchaseOffers(
            api, Path(__file__).resolve().parents[2] / "cache"
        )
        self.recipes = ItemRecipeCatalog(
            api, Path(__file__).resolve().parents[2] / "cache"
        )
        self.hideout_requirements = ItemHideoutRequirements(
            api, Path(__file__).resolve().parents[2] / "cache"
        )
        self._recipe_show_all = False
        self._recipe_names: dict[str, str] = {}
        self._recipe_names_length = -1
        self._started = False
        self._quest_summaries: dict[str, list[dict] | None] = {}

        # Small decoded-image cache, separate from JSON detail caching.
        self._image_cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._image_reply = None
        self._image_generation = 0
        self._image_item_id: str | None = None
        self._image_candidates: list[str] = []
        self._image_errors: list[str] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 20)
        root.setSpacing(12)

        title = QLabel("ITEMS")
        title.setStyleSheet(
            "font-size: 24px; font-weight: bold; color: #bdd393;"
        )
        root.addWidget(title)

        subtitle = QLabel(
            "Browse item data and quest requirements. "
            "Personal stash planning belongs in My PMC."
        )
        subtitle.setStyleSheet("color: #9babad; font-size: 12px;")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        toolbar = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search by item name or short name...")
        toolbar.addWidget(self.search_input, 1)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("PvP requirements", "regular")
        self.mode_combo.addItem("PvE requirements", "pve")
        chosen_mode = self.mode_combo.findData(initial_mode)
        if chosen_mode >= 0:
            self.mode_combo.setCurrentIndex(chosen_mode)
        toolbar.addWidget(self.mode_combo)

        self.refresh_button = QPushButton("Refresh")
        toolbar.addWidget(self.refresh_button)
        root.addLayout(toolbar)

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(350)
        self.search_timer.timeout.connect(self._start_search)
        self.search_input.textChanged.connect(self._schedule_search)
        self.refresh_button.clicked.connect(self._start_search)
        self.mode_combo.currentIndexChanged.connect(self._render_details)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self.results_status = QLabel("Open Items to search the item catalog.")
        self.results_status.setStyleSheet("color: #9babad;")
        left_layout.addWidget(self.results_status)

        self.items_list = QListWidget()
        self.items_list.currentItemChanged.connect(self._select_item)
        left_layout.addWidget(self.items_list, 1)

        pagination = QHBoxLayout()
        self.previous_button = QPushButton("Previous")
        self.previous_button.clicked.connect(self._previous_page)
        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self._next_page)
        self.page_label = QLabel("Page 1")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pagination.addWidget(self.previous_button)
        pagination.addWidget(self.page_label, 1)
        pagination.addWidget(self.next_button)
        left_layout.addLayout(pagination)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        header = QHBoxLayout()
        self.image_label = QLabel("No image")
        self.image_label.setFixedSize(152, 152)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet(
            "background: #1b252b; border: 1px solid #41545b; "
            "border-radius: 7px; color: #82989d;"
        )
        header.addWidget(self.image_label)

        self.item_title = QLabel("Select an item")
        self.item_title.setWordWrap(True)
        self.item_title.setTextFormat(Qt.TextFormat.PlainText)
        self.item_title.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.item_title.setStyleSheet(
            "font-size: 19px; font-weight: bold; color: #dce9d1;"
        )
        header.addWidget(self.item_title, 1)
        right_layout.addLayout(header)

        self.details = QTextBrowser()
        self.details.setOpenLinks(False)
        self.details.setOpenExternalLinks(False)
        self.details.anchorClicked.connect(self._open_link)
        self.details.setHtml(
            "<p>Search for an item, then select it to view its details.</p>"
        )
        right_layout.addWidget(self.details, 1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([330, 560])
        root.addWidget(splitter, 1)

        self.status = QLabel("Data is loaded on demand from the public API.")
        self.status.setStyleSheet("color: #82989d; font-size: 11px;")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self._update_pagination()

    def ensure_loaded(self) -> None:
        """Lazy-load the first page only when the tab is opened."""
        if not self._started:
            self._started = True
            self._start_search()

    def set_mode(self, mode: str) -> None:
        """Optionally synchronize with an external PvP/PvE mode."""
        index = self.mode_combo.findData(mode)
        if index >= 0:
            self.mode_combo.setCurrentIndex(index)

    def _schedule_search(self, _text: str) -> None:
        if self._started:
            self.search_timer.start()

    def _start_search(self, offset: int = 0) -> None:
        # Qt clicked(bool) passes a boolean; it must not become the offset.
        if type(offset) is not int:
            offset = 0
        self.search_timer.stop()
        self._clear_image()
        self._recipe_show_all = False
        self.item_title.setText("Select an item")
        self.details.setHtml("<p>Searching...</p>")
        self.browser.search_items(
            self.search_input.text(), self._on_search_updated, offset=offset
        )

    def _on_search_updated(self) -> None:
        if self.browser.searching:
            self.results_status.setText("Searching items...")
            self.items_list.clear()
            self._update_pagination()
            return

        self.items_list.blockSignals(True)
        self.items_list.clear()
        for item in self.browser.results:
            item_id = str(item.get("id") or "")
            if not item_id:
                continue
            name = str(item.get("name") or "Unknown item")
            category = item.get("category")
            group = category.get("name") if isinstance(category, dict) else ""
            short_name = str(item.get("shortName") or "")
            caption = " • ".join(part for part in (short_name, str(group or "")) if part)
            label = f"{name}\n{caption}" if caption else name
            row = QListWidgetItem(label)
            row.setData(Qt.ItemDataRole.UserRole, item_id)
            row.setToolTip(name)
            self.items_list.addItem(row)
        self.items_list.blockSignals(False)

        if self.browser.search_error:
            self.results_status.setText("Item search failed")
            self.details.setHtml(
                f"<h3>Connection error</h3><p>{esc(self.browser.search_error)}</p>"
                "<p>Try Refresh when the connection is available.</p>"
            )
            self.status.setText("Could not retrieve item search results.")
        else:
            count = self.items_list.count()
            self.results_status.setText(f"{count} items on this page")
            index = self.browser.index
            if index is not None and index.loading:
                self.status.setText(
                    "Building local name/short-name index in the background "
                    f"(page {index.pages_loaded + 1}). Search results may update."
                )
            elif index is not None and index.error and not index.ready:
                self.status.setText(
                    "Name search is available; short-name index could not be "
                    "updated. See terminal for details."
                )
            else:
                self.status.setText(
                    "Search by full name or short name. Images load on selection."
                )
            if count:
                self.items_list.setCurrentRow(0)
            else:
                self.item_title.setText("No items found")
                self.details.setHtml("<p>No items match this search.</p>")
        self._update_pagination()

    def _update_pagination(self) -> None:
        offset = self.browser.offset
        limit = self.browser.limit
        page = offset // limit + 1
        meta_total = self.browser.meta.get("total")
        known_total = (
            int(meta_total)
            if type(meta_total) is int and meta_total >= 0
            else None
        )
        total_pages = (
            max(1, (known_total + limit - 1) // limit)
            if known_total is not None
            else None
        )
        self.page_label.setText(
            f"Page {page}" + (f" / {total_pages}" if total_pages else "")
        )
        ready = not self.browser.searching and not self.browser.search_error
        self.previous_button.setEnabled(ready and offset > 0)
        if known_total is not None:
            has_next = offset + len(self.browser.results) < known_total
        else:
            has_next = len(self.browser.results) == limit
        self.next_button.setEnabled(bool(ready and has_next))

    def _previous_page(self) -> None:
        self._start_search(max(0, self.browser.offset - self.browser.limit))

    def _next_page(self) -> None:
        self._start_search(self.browser.offset + self.browser.limit)

    def _select_item(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None:
            return
        item_id = current.data(Qt.ItemDataRole.UserRole)
        if not isinstance(item_id, str):
            return
        self._clear_image()
        self._recipe_show_all = False
        self.item_title.setText(current.text().split("\n", 1)[0])
        self.details.setHtml("<p>Loading item details...</p>")
        self.browser.load_item_details(item_id, self._on_details_updated)

    def _on_details_updated(self) -> None:
        self._render_details()

    def _render_details(self, _index: int | None = None) -> None:
        selected = self.items_list.currentItem()
        if selected is None:
            return
        selected_id = selected.data(Qt.ItemDataRole.UserRole)
        if selected_id != self.browser.selected_item_id:
            return
        if self.browser.details_loading:
            self.details.setHtml("<p>Loading item details...</p>")
            return
        if self.browser.details_error:
            self.details.setHtml(
                f"<h3>Could not load item</h3>"
                f"<p>{esc(self.browser.details_error)}</p>"
            )
            return
        item = self.browser.selected_item
        if not isinstance(item, dict):
            return

        self.item_title.setText(str(item.get("name") or "Unknown item"))
        self._load_image(item)

        parts: list[str] = []
        description = item.get("description")
        if description:
            parts.append(f"<p>{esc(description)}</p>")

        category = item.get("category")
        if isinstance(category, dict) and category.get("name"):
            parts.append(f"<p><b>Category:</b> {esc(category['name'])}</p>")
        if item.get("shortName"):
            parts.append(f"<p><b>Short name:</b> {esc(item['shortName'])}</p>")
        types = item.get("types")
        if isinstance(types, list) and types:
            parts.append(f"<p><b>Types:</b> {esc(', '.join(map(str, types)))}</p>")

        width, height = item.get("width"), item.get("height")
        if type(width) is int and type(height) is int:
            parts.append(
                f"<p><b>Stash size:</b> {width} × {height} "
                f"({width * height} slots)</p>"
            )
        if isinstance(item.get("weight"), (int, float)):
            parts.append(f"<p><b>Weight:</b> {esc(item['weight'])} kg</p>")

        wiki = item.get("wikiLink")
        if isinstance(wiki, str):
            parsed = urlparse(wiki)
            if parsed.scheme == "https" and parsed.netloc:
                parts.append(
                    f'<p><a href="{esc(wiki)}">Open original wiki page</a></p>'
                )

        # Trader data is requested only after an item is selected.
        mode = str(self.mode_combo.currentData() or "regular")
        self.trader_prices.ensure(mode)
        parts.extend(self._trader_prices_html(item, mode))
        self.purchase_offers.ensure(
            mode, str(item.get("id") or ""), self._render_details
        )
        parts.extend(self._purchase_offers_html(str(item.get("id") or ""), mode))
        price = item.get("basePrice")
        if isinstance(price, (int, float)) and not isinstance(price, bool):
            parts.append(
                f"<p><small>Base value (reference only): {int(price):,} ₽ — "
                "not a trader or Flea Market selling price.</small></p>"
            )

        parts.append("<hr><h3>Quest requirements</h3>")
        parts.extend(self._quest_requirements_html(str(item.get("id") or "")))
        # Craft and barter relationships belong to the public encyclopedia.
        self.recipes.ensure(mode, self._on_recipes_updated)
        parts.extend(self._recipe_html(str(item.get("id") or ""), mode))
        self.hideout_requirements.ensure(mode, self._render_details)
        parts.extend(self._hideout_html(str(item.get("id") or ""), mode))
        parts.append(
            "<hr><p><small>Personal Hideout station levels, stash inventory and "
            "item priorities will be tracked in My PMC. "
            "Flea Market data is intentionally excluded.</small></p>"
        )
        self.details.setHtml("".join(parts))

    def _on_recipes_updated(self) -> None:
        """Refresh only the visible item when async recipe data changes."""
        self._render_details()

    def _item_names(self) -> dict[str, str]:
        """Reuse the existing compact search index; never download names twice."""
        idx = self.browser.index
        if idx is None or not idx.ready:
            return self._recipe_names
        entries = idx.items
        if len(entries) != self._recipe_names_length:
            self._recipe_names = {
                str(entry["id"]).lower(): str(entry["name"])
                for entry in entries
                if isinstance(entry, dict)
                and isinstance(entry.get("id"), str)
                and isinstance(entry.get("name"), str)
            }
            self._recipe_names_length = len(entries)
        return self._recipe_names

    def _ingredient_html(self, entry: dict) -> str:
        item_id = str(entry.get("id") or "")
        selected = self.browser.selected_item
        selected_name = (
            str(selected.get("name") or "")
            if isinstance(selected, dict) and selected.get("id") == item_id
            else ""
        )
        name = (
            self._item_names().get(item_id)
            or str(entry.get("name") or "")
            or selected_name
            or item_id
        )
        amount = entry.get("count", 1)
        amount_text = f"{amount:g}" if isinstance(amount, (int, float)) else "?"
        label = f"{esc(name)} ×{esc(amount_text)}"
        if len(item_id) == 24 and all(c in "0123456789abcdef" for c in item_id):
            label = f'<a href="item://{esc(item_id)}">{label}</a>'
        if entry.get("reusable"):
            label += " <small>(reusable tool)</small>"
        return label

    def _single_recipe_html(self, recipe: dict, kind: str) -> str:
        mode = self.mode_combo.currentData() or "regular"
        source = esc(resolve_recipe_source_name(
            mode, recipe, self.recipes, self.hideout_requirements
        ))
        level = recipe.get("level")
        if type(level) is int and level > 0:
            source += f" — {'Level' if kind == 'crafts' else 'LL'} {level}"
        extras = []
        duration = recipe.get("duration")
        if kind == "crafts" and type(duration) is int and duration > 0:
            hours, remainder = divmod(duration, 3600)
            minutes = (remainder + 59) // 60
            extras.append(f"{hours}h {minutes}m" if hours else f"{minutes}m")
        if recipe.get("unlock"):
            extras.append("Quest unlock required")
        head = f"<b>{source}</b>"
        if extras:
            head += f" <small>({esc(' • '.join(extras))})</small>"
        required = ", ".join(self._ingredient_html(x) for x in recipe["required"])
        rewards = ", ".join(self._ingredient_html(x) for x in recipe["rewards"])
        return (
            f"<li>{head}<br>"
            f"<small>Requires:</small> {required}<br>"
            f"<small>Gives:</small> {rewards}</li>"
        )

    def _recipe_html(self, item_id: str, mode: str) -> list[str]:
        parts = ["<hr><h3>Crafts &amp; barters</h3>"]
        sections = (
            ("crafts", "for", "Craft this item"),
            ("crafts", "using", "Used in crafts"),
            ("barters", "for", "Get this item via barter"),
            ("barters", "using", "Used as barter payment"),
        )
        pending_shown: set[str] = set()
        for kind, side, title in sections:
            state = self.recipes.status(mode, kind)
            if state == "loading":
                if kind not in pending_shown:
                    parts.append(f"<p>Loading {esc(kind)} in the background...</p>")
                    pending_shown.add(kind)
                continue
            if state == "error":
                if kind not in pending_shown:
                    parts.append(
                        f"<p>Could not load {esc(kind)}: "
                        f"{esc(self.recipes.error(mode, kind))}. "
                        '<a href="recipes://refresh">Retry recipes</a></p>'
                    )
                    pending_shown.add(kind)
                continue
            if state == "empty":
                continue
            recipes = self.recipes.recipes_for(mode, kind, item_id, side)
            parts.append(f"<h4>{esc(title)} ({len(recipes)})</h4>")
            if not recipes:
                parts.append("<p><small>None found in this mode.</small></p>")
                continue
            limit = len(recipes) if self._recipe_show_all else 12
            parts.append("<ul>")
            for recipe in recipes[:limit]:
                parts.append(self._single_recipe_html(recipe, kind))
            parts.append("</ul>")
            if len(recipes) > limit:
                parts.append(
                    f'<p><a href="recipes://show-all">Show all {len(recipes)} recipes</a></p>'
                )
        if self._recipe_show_all:
            parts.append('<p><a href="recipes://collapse">Show fewer recipes</a></p>')
        parts.append(
            '<p><small><a href="recipes://refresh">Refresh crafts &amp; barters</a>. '
            "Data is cached by PvP/PvE. Recipe costs and profitability "
            "are not calculated.</small></p>"
        )
        return parts


    def _hideout_html(self, item_id: str, mode: str) -> list[str]:
        """Public item-to-Hideout relationships, not personal upgrade tracking."""
        parts = ["<hr><h3>Used in Hideout</h3>"]
        source = self.hideout_requirements
        state = source.status(mode)
        if state == "loading":
            parts.append("<p>Loading Hideout construction requirements...</p>")
            return parts
        if state == "error":
            parts.append(
                f"<p>Hideout requirements unavailable: {esc(source.error(mode))}</p>"
                '<p><a href="hideout://refresh">Retry Hideout data</a></p>'
            )
            return parts
        if state == "empty":
            parts.append("<p>Hideout data not loaded yet.</p>")
            return parts
        rows = source.for_item(mode, item_id)
        if not rows:
            parts.append("<p>This item is not listed as a Hideout construction material.</p>")
        else:
            total = sum(row["count"] for row in rows)
            parts.append(
                f"<p><b>Total across Hideout construction levels: "
                f"{esc(self._purchase_number(total))}×</b></p>"
            )
            parts.append("<ul>")
            for row in rows:
                label = row.get("station_name") or self.recipes.source_name(mode, {
                    "source": row["station_id"], "kind": "crafts"
                })
                parts.append(
                    f"<li>{esc(label)} — Level {row['level']}: "
                    f"{esc(self._purchase_number(row['count']))}×</li>"
                )
            parts.append("</ul>")
            parts.append(
                "<p><small>Full upgrade path, independent of your personal "
                "Hideout progress. My PMC will calculate what remains based "
                "on your completed station levels.</small></p>"
            )
        if state == "stale":
            parts.append(
                f"<p><small>Showing cached data; refresh failed: "
                f"{esc(source.error(mode))}</small></p>"
            )
        elif state == "refreshing":
            parts.append("<p><small>Updating Hideout requirements...</small></p>")
        parts.append('<p><small><a href="hideout://refresh">Refresh Hideout requirements</a></small></p>')
        return parts

    def _on_trader_prices_updated(self, mode: str) -> None:
        if mode == self.mode_combo.currentData():
            self._render_details()

    @staticmethod
    def _rubles(value: int | float) -> str:
        return f"{value:,.0f} ₽"

    def _trader_prices_html(self, item: dict, mode: str) -> list[str]:
        """Only player-to-trader sales are included; Flea Market is excluded."""
        source = self.trader_prices
        item_id = str(item.get("id") or "")
        parts = ["<hr><h3>Trader sell prices</h3>"]
        loading = source.is_loading(mode)
        if not source.has_prices(mode):
            if loading:
                parts.append(
                    "<p>Loading trader prices in the background (first sync)...</p>"
                    "<p><small>Only a compact price index is saved locally. "
                    "No Flea Market data is used.</small></p>"
                )
            else:
                error = source.error(mode)
                if error:
                    parts.append(
                        f"<p>Trader prices unavailable: {esc(error)}</p>"
                        '<p><a href="price://refresh">Retry price download</a></p>'
                    )
                else:
                    parts.append("<p>No trader price data loaded.</p>")
            return parts

        offers = source.offers_for(mode, item_id)
        if not offers:
            parts.append("<p>No trader resale price is available for this item.</p>")
        else:
            best = offers[0]
            best_value = best["price_rub"]
            best_trader = best["trader"]
            parts.append(
                f"<p><b>Best trader sell price:</b> {self._rubles(best_value)} "
                f"— {esc(best_trader)}</p>"
            )
            width, height = item.get("width"), item.get("height")
            if (
                type(width) is int and type(height) is int
                and width > 0 and height > 0
            ):
                slots = width * height
                parts.append(
                    f"<p><b>Trader value per slot:</b> "
                    f"{self._rubles(best_value / slots)} "
                    f"({slots} stash slot{'s' if slots != 1 else ''})</p>"
                )
            else:
                parts.append(
                    "<p><b>Trader value per slot:</b> Unknown "
                    "(missing item dimensions)</p>"
                )
            parts.append("<p><b>Trader comparison:</b></p><ul>")
            for offer in offers:
                parts.append(
                    f"<li>{esc(offer['trader'])}: "
                    f"{self._rubles(offer['price_rub'])}</li>"
                )
            parts.append("</ul>")

        fetched = source.fetched_at(mode)
        if fetched:
            when = datetime.fromtimestamp(fetched).strftime("%d %b %Y %H:%M")
            parts.append(
                f"<p><small>Trader-price snapshot: {esc(when)} (local time)"
                f"{' — refreshing' if loading else ''}. "
                'Prices may vary with trader conditions and item durability. '
                '<a href="price://refresh">Refresh prices</a>. '
                "Flea Market excluded.</small></p>"
            )
        if source.error(mode):
            parts.append(
                "<p><small>Last refresh failed; showing the cached "
                f"snapshot. {esc(source.error(mode))}</small></p>"
            )
        return parts


    @staticmethod
    def _purchase_number(value: object) -> str:
        if type(value) in (int, float):
            return f"{value:,.0f}" if float(value).is_integer() else f"{value:g}"
        return "?"

    def _purchase_requirement_html(self, part: dict) -> str:
        """Show actual required currency/items; never infer a price from summaryCost."""
        currency = str(part.get("currency") or "")
        count = self._purchase_number(part.get("count"))
        if currency:
            return f"{esc(count)} {esc(currency)}"
        req_type = str(part.get("type") or "")
        if req_type == "DogtagRequirement":
            side = str(part.get("side") or "Any faction")
            level = part.get("level")
            label = f"Dogtags ({side}"
            if type(level) is int:
                label += f", level {level}+"
            return f"{esc(label + ')')} ×{esc(count)}"
        item_id = str(part.get("item_id") or "").lower()
        if len(item_id) == 24 and all(c in "0123456789abcdef" for c in item_id):
            name = self._item_names().get(item_id) or f"Item …{item_id[-6:]}"
            return f'<a href="item://{esc(item_id)}">{esc(name)}</a> ×{esc(count)}'
        label = req_type.replace("Requirement", "") or "Unknown requirement"
        return f"{esc(label)} ×{esc(count)}"

    def _purchase_offers_html(self, item_id: str, mode: str) -> list[str]:
        """Traders selling TO the player, separate from player selling TO traders."""
        parts = ["<hr><h3>Buy from traders</h3>"]
        state = self.purchase_offers.status(mode, item_id)
        if state == "loading":
            parts.append("<p>Checking current trader purchase offers...</p>")
            return parts
        if state == "error":
            parts.append(
                f"<p>Trader purchase offers unavailable: "
                f"{esc(self.purchase_offers.error(mode, item_id))}</p>"
                '<p><a href="purchase://refresh">Retry offers</a></p>'
            )
            return parts
        offers = self.purchase_offers.offers_for(mode, item_id)
        if not offers:
            parts.append("<p>No trader purchase offers found for this item.</p>")
        else:
            cash = [row for row in offers if row.get("cash_only")]
            barter = [row for row in offers if not row.get("cash_only")]
            for title, rows in (("Currency purchases", cash), ("Item / special trades", barter)):
                if not rows:
                    continue
                parts.append(f"<h4>{esc(title)} ({len(rows)})</h4><ul>")
                for offer in rows[:16]:
                    trader = esc(offer.get("trader") or "Unknown trader")
                    conditions = []
                    if type(offer.get("loyalty")) is int:
                        conditions.append(f"LL {offer['loyalty']}")
                    if type(offer.get("pmc_level")) is int:
                        conditions.append(f"PMC level {offer['pmc_level']}+")
                    if type(offer.get("buy_limit")) is int:
                        conditions.append(f"Purchase limit {offer['buy_limit']}")
                    stack = offer.get("stack_count")
                    stack_text = f" ×{stack}" if type(stack) is int and stack > 1 else ""
                    price = " + ".join(
                        self._purchase_requirement_html(req)
                        for req in offer.get("requirements", [])
                    )
                    extras = f" <small>({esc(' • '.join(conditions))})</small>" if conditions else ""
                    parts.append(f"<li><b>{trader}</b>{esc(stack_text)}{extras}<br>"
                                 f"<small>Cost:</small> {price}</li>")
                parts.append("</ul>")
                if len(rows) > 16:
                    parts.append(f"<p><small>Showing first 16 of {len(rows)} offers.</small></p>")
        stamp = self.purchase_offers.fetched_at(mode, item_id)
        detail = (
            f"Snapshot: {datetime.fromtimestamp(stamp).strftime('%d %b %Y %H:%M')} (local)"
            if stamp else "Trader offer availability can change"
        )
        parts.append(
            f"<p><small>{esc(detail)}. "
            "Loyalty and level requirements are informational, not checks "
            "against your character. "
            '<a href="purchase://refresh">Refresh offers</a>. '
            "No Flea Market prices used.</small></p>"
        )
        if state == "stale":
            parts.append(
                "<p><small>Refresh failed; showing previously cached offers. "
                f"{esc(self.purchase_offers.error(mode, item_id))}</small></p>"
            )
        elif state == "refreshing":
            parts.append("<p><small>Updating trader offers...</small></p>")
        return parts

    def _summaries_for_mode(self, mode: str) -> list[dict] | None:
        if mode in self._quest_summaries:
            return self._quest_summaries[mode]
        tasks = self.cache.load_tasks(mode)
        if not isinstance(tasks, list):
            # Do not cache a miss; the user may load Quests later.
            return None
        summaries = summarize_quest_requirements(
            extract_item_requirements(tasks)
        )
        self._quest_summaries[mode] = summaries
        return summaries

    def _quest_requirements_html(self, item_id: str) -> list[str]:
        mode = str(self.mode_combo.currentData() or "regular")
        summaries = self._summaries_for_mode(mode)
        if summaries is None:
            return [
                "<p>Quest cache unavailable for this mode. "
                "Open Quests and load its data, then return to Items.</p>"
            ]
        matches = get_item_requirements(item_id, summaries)
        direct = matches["direct_requirements"]
        alternatives = matches["alternative_requirements"]
        if not direct and not alternatives:
            return ["<p>No quest requirements found in this mode.</p>"]

        direct_total = matches["required_total"]
        parts = [
            f"<p><b>Direct mandatory total (preliminary): "
            f"{direct_total}</b></p>",
            "<p><small>This is a sum across quest requirements, not a "
            "recommendation to keep these items now. Alternative choices "
            "and special quest conditions are excluded from the total. "
            "Final totals require a full quest-by-quest audit.</small></p>",
        ]
        if direct:
            parts.append("<h4>Direct requirements</h4><ul>")
            for entry in direct:
                parts.append(self._requirement_row(entry, mode, alternative=False))
            parts.append("</ul>")
        if alternatives:
            parts.append("<h4>Accepted as an alternative</h4><ul>")
            for entry in alternatives:
                parts.append(self._requirement_row(entry, mode, alternative=True))
            parts.append("</ul>")
        return parts

    @staticmethod
    def _requirement_row(entry: dict, mode: str, alternative: bool) -> str:
        quest_id = str(entry.get("quest_id") or "")
        quest_name = esc(entry.get("quest_name") or quest_id)
        name = (
            f'<a href="quest://{esc(quest_id)}">{quest_name}</a>'
            if len(quest_id) == 24 and all(c in "0123456789abcdefABCDEF" for c in quest_id)
            else quest_name
        )
        required = int(entry.get("required_count") or 0)
        optional = int(entry.get("optional_count") or 0)
        amount = f"{required} required" if required else "No mandatory quantity"
        if optional:
            amount += f", {optional} optional"
        info = [amount]
        if alternative:
            info.append(f"one of {len(entry.get('item_ids') or [])} item choices")
        if entry.get("found_in_raid"):
            info.append("Found in Raid")
        return f"<li>{name} — {esc('; '.join(info))}</li>"

    def _open_link(self, url: QUrl) -> None:
        if url.scheme() == "hideout" and url.host() == "refresh":
            mode = str(self.mode_combo.currentData() or "regular")
            self.hideout_requirements.ensure(mode, self._render_details, force=True)
            self._render_details()
            return
        if url.scheme() == "purchase" and url.host() == "refresh":
            mode = str(self.mode_combo.currentData() or "regular")
            item = self.browser.selected_item
            if isinstance(item, dict):
                self.purchase_offers.ensure(
                    mode, str(item.get("id") or ""), self._render_details, force=True
                )
                self._render_details()
            return
        if url.scheme() == "recipes":
            action = url.host()
            if action == "refresh":
                mode = str(self.mode_combo.currentData() or "regular")
                self.recipes.ensure(mode, self._on_recipes_updated, force=True)
            elif action == "show-all":
                self._recipe_show_all = True
            elif action == "collapse":
                self._recipe_show_all = False
            self._render_details()
            return
        if url.scheme() == "item":
            item_id = url.host().lower()
            if len(item_id) != 24 or any(c not in "0123456789abcdef" for c in item_id):
                return
            for idx in range(self.items_list.count()):
                row = self.items_list.item(idx)
                if row.data(Qt.ItemDataRole.UserRole) == item_id:
                    self.items_list.setCurrentRow(idx)
                    return
            # Ingredient navigation works without a second search/index scan.
            row = QListWidgetItem(self._item_names().get(item_id, item_id))
            row.setData(Qt.ItemDataRole.UserRole, item_id)
            self.items_list.addItem(row)
            self.items_list.setCurrentItem(row)
            return
        if url.scheme() == "price" and url.host() == "refresh":
            mode = str(self.mode_combo.currentData() or "regular")
            self.trader_prices.ensure(mode, force=True)
            self._render_details()
            return
        if url.scheme() == "quest":
            quest_id = url.host()
            if (
                self.open_quest is not None
                and len(quest_id) == 24
                and all(c in "0123456789abcdefABCDEF" for c in quest_id)
            ):
                self.open_quest(quest_id, str(self.mode_combo.currentData()))
            return
        if url.scheme() == "https" and url.host():
            QDesktopServices.openUrl(url)

    def _clear_image(self) -> None:
        """Cancel pending image work when the selected item changes."""
        self._image_generation += 1
        reply = self._image_reply
        self._image_reply = None
        self._image_item_id = None
        self._image_candidates = []
        self._image_errors = []
        if reply is not None and reply.isRunning():
            reply.abort()
        self.image_label.clear()
        self.image_label.setText("No image")

    def _load_image(self, item: dict) -> None:
        """Fetch the base image, falling back to the smaller item icon."""
        item_id = str(item.get("id") or "")
        if self._image_item_id == item_id:
            # An ongoing request, cached result or completed failure should
            # not restart when the player switches PvP/PvE requirements.
            return

        urls = []
        for key in ("imageLink", "iconLink"):
            url = item.get(key)
            if not isinstance(url, str):
                continue
            parsed = urlparse(url)
            if parsed.scheme == "https" and parsed.netloc and url not in urls:
                urls.append(url)

        self._image_item_id = item_id
        self._image_candidates = urls
        self._image_errors = []
        if not urls:
            self.image_label.setText("No image")
            return
        self._request_next_image()

    def _request_next_image(self) -> None:
        """Try the next available image URL, retaining request generation."""
        if not self._image_candidates:
            self.image_label.setText("Image unavailable")
            if self._image_errors:
                error = "; ".join(self._image_errors)
                print(f"Item image warning ({self._image_item_id}): {error}")
                self.status.setText(
                    "Item image unavailable. See terminal for details. "
                    "If Qt lacks WebP support: python -m pip install Pillow"
                )
            return

        url = self._image_candidates.pop(0)
        if url in self._image_cache:
            self._image_cache.move_to_end(url)
            self.image_label.setPixmap(self._image_cache[url])
            return

        image_generation = self._image_generation
        item_id = self._image_item_id
        self.image_label.setText("Loading image...")
        request = QNetworkRequest(QUrl(url))
        request.setTransferTimeout(15000)
        request.setRawHeader(b"User-Agent", b"TarkovWikiLite/0.2")
        reply = self.api.network.get(request)
        self._image_reply = reply

        def limit_download(received: int, _total: int) -> None:
            if received > IMAGE_LIMIT_BYTES and reply.isRunning():
                reply.abort()

        reply.downloadProgress.connect(limit_download)

        def finished() -> None:
            if self._image_reply is reply:
                self._image_reply = None
            try:
                selected = self.items_list.currentItem()
                if (
                    image_generation != self._image_generation
                    or selected is None
                    or selected.data(Qt.ItemDataRole.UserRole) != item_id
                ):
                    return

                if reply.error() != QNetworkReply.NetworkError.NoError:
                    self._image_errors.append(
                        f"{url.rsplit('/', 1)[-1]}: {reply.errorString()}"
                    )
                    self._request_next_image()
                    return

                data = bytes(reply.readAll())
                if not data or len(data) > IMAGE_LIMIT_BYTES:
                    self._image_errors.append("Image empty or exceeds 3 MB")
                    self._request_next_image()
                    return

                pixmap, error = decode_item_pixmap(
                    data, target_size=IMAGE_TARGET_SIZE
                )
                if pixmap is None:
                    self._image_errors.append(
                        f"{url.rsplit('/', 1)[-1]}: {error}"
                    )
                    self._request_next_image()
                    return

                self._image_cache[url] = pixmap
                self._image_cache.move_to_end(url)
                while len(self._image_cache) > IMAGE_CACHE_SIZE:
                    self._image_cache.popitem(last=False)
                self.image_label.setPixmap(pixmap)
            finally:
                reply.deleteLater()

        reply.finished.connect(finished)
