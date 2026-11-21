"""Tarkov Wiki Lite — primeira versão.

Interface em PySide6, sem navegador embutido.
Consulta dados de missões pela API JSON do tarkov.dev e usa cache no HD.
"""

from __future__ import annotations

from asyncio import tasks
import html
import json
import sys
from pathlib import Path
from app.services.traders import get_trader_name
from urllib.parse import urlparse
from app.services.tarkov_api import TarkovApi
from app.services.cache_manager import CacheManager
from app.services.progress_manager import ProgressManager
from app.ui.companion_window import CompanionWindow
from app.services.item_catalog import ItemCatalog
from app.models.guide_catalog import get_quest_guide
from app.services.guide_images import GuideImageCache
from app.ui.guide_viewer import GuideDialog
from app.ui.items_page import ItemsPage

from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QStackedWidget,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QAbstractSpinBox,
    QCheckBox,
    QScrollArea,
    QSpinBox,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.models.quest import (
    extract_tasks,
    extract_translations,
    localize,
    name_of,
)

from app.models.rewards import (
    get_reward_item_ids,
    render_reward_html,
)

from app.models.quest_dependencies import (
    build_reverse_requirements,
    get_quest_id,
    get_task_requirements,
)



# Project root directory
APP_DIR = Path(__file__).resolve().parents[2]

# Local cache directory
CACHE_DIR = APP_DIR / "cache"

# Base URL for the Tarkov API for quests and translations
BASE_URL = "https://api.tarkov-stammtisch.de/api/v2"

def esc(value: object) -> str:
    return html.escape(str(value), quote=True)

class TarkovWikiLite(QMainWindow):

    """Main window for Tarkov Wiki Lite."""
    
    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("Tarkov Wiki Lite - v0.2")
        self.resize(1120, 720)
        self.setMinimumSize(850, 550)

        # Services
        self.api = TarkovApi(self)
        self.cache = CacheManager(CACHE_DIR)
        self.guide_images = GuideImageCache(
            CACHE_DIR / "guide_images",
            self,
        )
        self.item_catalog = ItemCatalog(
            self.api,
            CACHE_DIR / "item_names_en.json",
        )
        self.progress = ProgressManager(APP_DIR / "data" / "progress.db")
        # Application state
        self.tasks = []
        self.filtered_tasks = []
        self.quests_loaded = False
        self.nav_buttons = {}
        # Quest waiting to be selected after loading
        self.pending_quest_id: str | None = None

        # Main layout
        central = QWidget()
        self.setCentralWidget(central)

        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Sidebar
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(205)

        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(15, 22, 15, 16)
        sidebar_layout.setSpacing(8)

        logo = QLabel("TARKOV\nWIKI LITE")
        logo.setStyleSheet("""
            color: #bdd393;
            font-size: 21px;
            font-weight: bold;
            padding-bottom: 25px;
        """)
        sidebar_layout.addWidget(logo)

        navigation = [
            ("home", "⌂  Home"),
            ("quests", "☷  Quests"),
            ("items", "▣  Items"),
            ("flea", "$  Flea Market"),
        ]

        for page_id, text in navigation:
            button = QPushButton(text)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setMinimumHeight(44)

            button.clicked.connect(
                lambda checked=False, target=page_id:
                    self.open_page(target)
            )

            sidebar_layout.addWidget(button)
            self.nav_buttons[page_id] = button

        sidebar_layout.addStretch()

        version = QLabel("v0.2  |  TARKOV COMPANION")
        version.setStyleSheet(
            "color: #788b91; font-size: 10px;"
        )
        sidebar_layout.addWidget(version)

        root_layout.addWidget(sidebar)

        # Page container
        self.stack = QStackedWidget()
        root_layout.addWidget(self.stack, 1)

        self.page_ids = {
            "home": 0,
            "quests": 1,
            "items": 2,
            "flea": 3,
        }

        self.stack.addWidget(self._create_home_page())
        self.stack.addWidget(self._create_quests_page())

        self.items_page = ItemsPage(
            api=self.api,
            cache=self.cache,
            initial_mode=self.mode.currentData(),
            open_quest=self.open_quest_from_items,
        )
        self.stack.addWidget(self.items_page)

        self.stack.addWidget(
            self._create_placeholder_page(
                "Flea Market",
                "Market prices and item value comparisons."
            )
        )

        # Global dark theme
        self.setStyleSheet("""
            QWidget {
                background-color: #12191d;
                color: #e6ecef;
                font-family: 'Segoe UI';
                font-size: 13px;
            }

            QWidget#Sidebar {
                background-color: #192328;
                border-right: 1px solid #344148;
            }

            QPushButton#NavButton {
                background-color: transparent;
                border: none;
                border-radius: 7px;
                padding: 12px;
                text-align: left;
                color: #aab9bd;
                font-weight: 500;
            }

            QPushButton#NavButton:hover {
                background-color: #2b393a;
                color: #ffffff;
            }

            QPushButton#NavButton:checked {
                background-color: #405b47;
                color: #ffffff;
                font-weight: bold;
            }

            QPushButton#HomeCard {
                background-color: #25342f;
                border: 1px solid #3d5045;
                border-radius: 10px;
                padding: 24px;
                text-align: left;
                color: #dce9d1;
                font-size: 15px;
                font-weight: bold;
            }

            QPushButton#HomeCard:hover {
                background-color: #344d3b;
                border: 1px solid #91ad82;
            }

            QLineEdit, QComboBox, QPushButton {
                background-color: #263238;
                border: 1px solid #41545b;
                border-radius: 6px;
                padding: 9px;
            }

            QListWidget, QTextBrowser {
                background-color: #1b252b;
                border: 1px solid #41545b;
                border-radius: 6px;
                padding: 8px;
            }

            QListWidget::item {
                padding: 6px;
            }

            QListWidget::item:selected {
                background-color: #426146;
            }

            QPushButton#PinnedQuest {
                background-color: #25342f;
                border: 1px solid #3d5045;
                border-radius: 7px;
                padding: 11px;
                text-align: left;
                color: #dce9d1;
            }

            QPushButton#PinnedQuest:hover {
                background-color: #344d3b;
                border: 1px solid #91ad82;
            }
        """)

        # Start on Home without loading quests yet
        self.open_page("home")



    def open_companion_mode(self) -> None:
        """Open the independent companion window."""

        mode = self.mode.currentData()

        if not hasattr(self, "companion_window"):
            self.companion_window = CompanionWindow(
                self.progress,
                self.cache,
                mode,
            )

            self.companion_window.show()

            # Place the window on another monitor when available
            screens = QApplication.screens()

            if len(screens) > 1 and not self.companion_window.geometry_restored:
                main_screen = self.screen()

                second_screen = next(
                    (
                        screen for screen in screens
                        if screen != main_screen
                    ),
                    screens[1],
                )

                area = second_screen.availableGeometry()

                x = max(
                    area.left() + 12,
                    area.right()
                    - self.companion_window.width()
                    - 12,
                )

                y = area.top() + 30

                self.companion_window.move(x, y)

        else:
            self.companion_window.set_mode(mode)
            self.companion_window.show()

    def get_quest_progress_summary(
        self,
        task: dict,
        mode: str
    ) -> str:
        """Summarize saved progress for a quest."""

        quest_id = str(task.get("id") or "")

        if not quest_id:
            return "Progress unavailable"

        progress = self.progress.get_quest_objective_progress(
            mode, quest_id
        )

        objectives = task.get("objectives") or []

        if isinstance(objectives, dict):
            objectives = list(objectives.values())

        if not isinstance(objectives, list):
            return "Progress unavailable"

        total = 0
        completed = 0
        partial = 0

        for objective in objectives:
            if not isinstance(objective, dict):
                continue

            if not objective.get("description"):
                continue

            objective_id = str(objective.get("id") or "")

            if not objective_id:
                continue

            count = objective.get("count")

            if (
                isinstance(count, (int, float))
                and not isinstance(count, bool)
                and count > 1
            ):
                required = int(count)
            else:
                required = 1

            saved = progress.get(objective_id, 0)

            total += 1

            if saved >= required:
                completed += 1
            elif saved > 0:
                partial += 1

        if total == 0:
            return "No trackable objectives"

        summary = f"{completed}/{total} objectives completed"

        if partial:
            summary += f" | {partial} in progress"

        return summary


    def refresh_home_pins(self) -> None:
        """Display saved pinned quests on the home page."""

        mode = self.mode.currentData()
        mode_label = "PvP" if mode == "regular" else "PvE"

        pinned_ids = self.progress.get_pinned_quests(mode)

        self.home_pins_info.setText(
            f"{len(pinned_ids)} pinned quests - {mode_label}"
        )

        # Remove previously displayed quest buttons
        while self.home_pins_layout.count():
            item = self.home_pins_layout.takeAt(0)
            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

        if not pinned_ids:
            empty = QLabel(
                "No pinned quests yet. Open Quests and pin one!"
            )
            empty.setStyleSheet("color: #82989d;")

            self.home_pins_layout.addWidget(empty)
            return

        # Use loaded data or read local cache
        tasks = self.tasks or self.cache.load_tasks(mode) or []

        tasks_by_id = {
            str(task["id"]): task
            for task in tasks
            if task.get("id")
        }

        # Display up to 6 pinned quests
        for quest_id in pinned_ids[:6]:
            task = tasks_by_id.get(quest_id)

            if task:
                quest_name = name_of(task.get("name"))
            else:
                quest_name = f"Quest {quest_id[:8]} - data unavailable"

            state = self.progress.get_state(mode, quest_id)

            prefix = "[DONE]" if state["completed"] else "[PIN]"

            if task:
                summary = self.get_quest_progress_summary(
                    task, mode
                )
            else:
                summary = "Quest data unavailable"

            button = QPushButton(
                f"{prefix}  {quest_name}\n{summary}"
            )

            button.setMinimumHeight(58)
            button.setObjectName("PinnedQuest")
            button.setMinimumHeight(43)

            button.clicked.connect(
                lambda checked=False, qid=quest_id:
                    self.open_pinned_quest(qid)
            )

            self.home_pins_layout.addWidget(button)

        if len(pinned_ids) > 6:
            remaining = len(pinned_ids) - 6

            info = QLabel(
                f"+ {remaining} more pinned quests"
            )
            info.setStyleSheet("color: #9babad;")

            self.home_pins_layout.addWidget(info)


    def open_pinned_quest(self, quest_id: str) -> None:
        """Open the Quests page and select a pinned quest."""

        self.pending_quest_id = str(quest_id)

        # Remove any previous search filter
        self.search.clear()

        # Navigate to the quest browser
        self.open_page("quests")

        # Select immediately if data is already available
        self._select_pending_quest()


    def _select_pending_quest(self) -> None:
        """Select a quest when its data is available."""

        if not self.pending_quest_id or not self.tasks:
            return

        for index, task in enumerate(self.filtered_tasks):
            if str(task.get("id")) == self.pending_quest_id:
                self.quest_list.setCurrentRow(index)
                self.pending_quest_id = None
                return

        self.status.setText(
            "Pinned quest not found in the loaded quest list."
        )
        self.pending_quest_id = None


    def _create_home_page(self) -> QWidget:
        """Create the application home page."""

        page = QWidget()
        layout = QVBoxLayout(page)

        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        title = QLabel("WELCOME BACK, PMC.")
        title.setStyleSheet("""
            font-size: 30px;
            font-weight: bold;
            color: #e1e9d5;
        """)
        layout.addWidget(title)

        subtitle = QLabel(
            "Your lightweight companion for Escape from Tarkov."
        )
        subtitle.setStyleSheet(
            "font-size: 14px; color: #9babad;"
        )
        layout.addWidget(subtitle)

        section = QLabel("QUICK ACCESS")
        section.setStyleSheet("""
            color: #bdd393;
            font-size: 13px;
            font-weight: bold;
            margin-top: 25px;
        """)
        layout.addWidget(section)

        cards = QHBoxLayout()
        cards.setSpacing(14)

        for text, page_id in [
            ("QUESTS\nObjectives & Rewards", "quests"),
            ("ITEMS\nCrafts & Loot", "items"),
            ("FLEA MARKET\nItem Prices", "flea"),
        ]:
            button = QPushButton(text)
            button.setObjectName("HomeCard")
            button.setMinimumHeight(145)

            button.clicked.connect(
                lambda checked=False, target=page_id:
                    self.open_page(target)
            )

            cards.addWidget(button)

        layout.addLayout(cards)

        # Companion Mode shortcut
        companion_button = QPushButton(
            "OPEN COMPANION MODE"
        )

        companion_button.setMinimumHeight(48)

        companion_button.clicked.connect(
            self.open_companion_mode
        )

        layout.addWidget(companion_button)

        # Pinned quests section
        pinned_title = QLabel("PINNED QUESTS")
        pinned_title.setStyleSheet("""
            color: #bdd393;
            font-size: 14px;
            font-weight: bold;
            margin-top: 20px;
        """)

        layout.addWidget(pinned_title)

        self.home_pins_info = QLabel("Loading pinned quests...")
        self.home_pins_info.setStyleSheet(
            "color: #9babad; font-size: 12px;"
        )

        layout.addWidget(self.home_pins_info)

        # Container for dynamically created quest buttons
        self.home_pins_container = QWidget()

        self.home_pins_layout = QVBoxLayout(
            self.home_pins_container
        )

        self.home_pins_layout.setContentsMargins(0, 0, 0, 0)
        self.home_pins_layout.setSpacing(8)

        layout.addWidget(self.home_pins_container)


        description = QLabel(
            "All quest tracking is manual. "
            "This app does not access the game."
        )
        description.setStyleSheet(
            "color: #82989d; font-size: 12px;"
        )
        layout.addWidget(description)

        layout.addStretch()

        return page


    def _create_quests_page(self) -> QWidget:
        """Create the quest browser page."""

        page = QWidget()
        layout = QVBoxLayout(page)

        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(12)

        title = QLabel("QUESTS")
        title.setStyleSheet("""
            font-size: 24px;
            font-weight: bold;
            color: #bdd393;
        """)
        layout.addWidget(title)

        # Toolbar
        toolbar = QHBoxLayout()

        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "Search quests..."
        )
        self.search.textChanged.connect(self.filter_tasks)
        toolbar.addWidget(self.search)

        self.mode = QComboBox()
        self.mode.addItem("PvP", "regular")
        self.mode.addItem("PvE", "pve")

        self.mode.currentIndexChanged.connect(
            lambda _: self.load_tasks()
        )
        toolbar.addWidget(self.mode)

        refresh = QPushButton("Refresh")
        refresh.clicked.connect(
            lambda: self.load_tasks(force=True)
        )
        toolbar.addWidget(refresh)

        layout.addLayout(toolbar)

        # Quest list and details
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.quest_list = QListWidget()
        self.quest_list.currentRowChanged.connect(
            self.show_task
        )
        splitter.addWidget(self.quest_list)


        # Right-side quest panel
        details_panel = QWidget()
        details_layout = QVBoxLayout(details_panel)

        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(10)

        # Quest progress actions
        actions = QHBoxLayout()

        self.pin_button = QPushButton("Pin Quest")
        self.pin_button.setCheckable(True)
        self.pin_button.setEnabled(False)

        self.completed_button = QPushButton("Mark Completed")
        self.completed_button.setCheckable(True)
        self.completed_button.setEnabled(False)

        actions.addWidget(self.pin_button)
        actions.addWidget(self.completed_button)

        details_layout.addLayout(actions)

        self.guide_button = QPushButton("View Location Guide")
        self.guide_button.setEnabled(False)
        self.guide_button.clicked.connect(
            self.open_location_guide
        )

        details_layout.addWidget(self.guide_button)

        # Objective tracker
        # Vertical splitter for objectives and quest details
        self.details_splitter = QSplitter(Qt.Orientation.Vertical)
        self.details_splitter.setChildrenCollapsible(False)

        # Objective tracker
        self.objectives_scroll = QScrollArea()
        self.objectives_scroll.setWidgetResizable(True)
        self.objectives_scroll.setVisible(False)

        self.details_splitter.addWidget(self.objectives_scroll)

        # Quest details and rewards
        self.details = QTextBrowser()

        self.details.setOpenLinks(False)
        self.details.setOpenExternalLinks(False)

        self.details.anchorClicked.connect(
            self.on_details_link_clicked
        )
        self.details.setHtml(
            "<h2>Select a quest from the list.</h2>"
        )

        self.details_splitter.addWidget(self.details)

        # Give more space to objectives
        self.details_splitter.setStretchFactor(0, 3)
        self.details_splitter.setStretchFactor(1, 1)

        # Add the vertical splitter to the right panel
        details_layout.addWidget(self.details_splitter, 1)


        splitter.addWidget(details_panel)

        # Connect buttons to progress handlers
        self.pin_button.toggled.connect(self.on_pin_toggled)
        self.completed_button.toggled.connect(
            self.on_completed_toggled
        )


        splitter.setSizes([350, 650])
        layout.addWidget(splitter, 1)

        self.status = QLabel("Quest data not loaded")
        self.status.setFixedHeight(22)
        layout.addWidget(self.status)

        return page


    def _create_placeholder_page(
        self,
        title: str,
        description: str
    ) -> QWidget:
        """Create a placeholder for future features."""

        page = QWidget()
        layout = QVBoxLayout(page)

        layout.setContentsMargins(40, 40, 40, 40)

        heading = QLabel(title.upper())
        heading.setStyleSheet("""
            font-size: 28px;
            font-weight: bold;
            color: #bdd393;
        """)
        layout.addWidget(heading)

        text = QLabel(description)
        text.setStyleSheet(
            "font-size: 14px; color: #aab9bd;"
        )
        layout.addWidget(text)

        label = QLabel("COMING SOON")
        label.setStyleSheet(
            "color: #82988a; font-weight: bold;"
        )
        layout.addWidget(label)

        layout.addStretch()

        return page
    

    def open_page(self, page_id: str) -> None:
        """Switch to the selected application page."""

        index = self.page_ids.get(page_id)

        if index is None:
            return

        self.stack.setCurrentIndex(index)

        for key, button in self.nav_buttons.items():
            button.setChecked(key == page_id)

        # Load quests only when the user first opens Quests
        if page_id == "quests" and not self.quests_loaded:
            self.quests_loaded = True
            self.load_tasks()

        if page_id == "home":
            self.refresh_home_pins()

        # Start item browsing only when Items is opened.
        if page_id == "items":
            self.items_page.ensure_loaded()

    def open_quest_from_items(self, quest_id: str, mode: str) -> None:
        """Navigate from an item requirement to its quest."""

        if mode not in ("regular", "pve") or not quest_id:
            return

        self.pending_quest_id = str(quest_id)
        self.search.clear()

        if self.mode.currentData() != mode:
            target_index = self.mode.findData(mode)
            if target_index < 0:
                return

            # Changing the combo box starts loading the requested mode.
            self.quests_loaded = True
            self.mode.setCurrentIndex(target_index)

        self.open_page("quests")
        self._select_pending_quest()

    # ---------- CACHE AND API ----------

    def load_tasks(self, force: bool = False) -> None:
        """Load quests from cache or download fresh data."""

        mode = self.mode.currentData()

        self.tasks = []
        self.filtered_tasks = []

        self.quest_list.clear()
        self.guide_button.setEnabled(False)
        self.objectives_scroll.setVisible(False)
        self.update_quest_actions()
        self.details.setHtml("<h2>Loading quests...</h2>")

        # Try the local cache first
        if not force:
            cached_tasks = self.cache.load_tasks(mode)

            if cached_tasks is not None:
                self.set_tasks(cached_tasks)

                self.status.setText(
                    f"Loaded from local cache: "
                    f"{len(cached_tasks)} quests"
                )
                return

        # Request fresh data if the cache is unavailable
        self.status.setText("Downloading quest data...")

        self.api.get_json(
            f"{BASE_URL}/{mode}/tasks",
            lambda data, error: self.on_tasks_loaded(
                mode, data, error
            ),
        )


    def on_tasks_loaded(self, mode: str, data, error) -> None:
        if mode != self.mode.currentData():
            return

        if error:
            self.show_error(error)
            return

        try:
            base_tasks = extract_tasks(data)
        except ValueError as problem:
            self.show_error(str(problem))
            return

        self.status.setText(
            "Loading English quest names and objectives..."
        )

        self.api.get_json(
            f"{BASE_URL}/{mode}/tasks_en",
            lambda translation, failure: self.on_english_loaded(
                mode, base_tasks, translation, failure
            ),
        )

    def on_english_loaded(
        self, mode: str, base_tasks: list, data, error
    ) -> None:
        if mode != self.mode.currentData():
            return

        if error:
            self.show_error(error)
            return

        translations = extract_translations(data)

        if not translations:
            self.show_error(
                "English translations are unavailable."
            )
            return

        tasks = localize(base_tasks, translations)
        tasks.sort(
            key=lambda task: name_of(task.get("name")).casefold()
        )


        try:
            self.cache.save_tasks(mode, tasks)

        except OSError as problem:
            self.status.setText(
                f"Loaded, but cache failed: {problem}"
            )

        else:
            self.status.setText(
                f"Downloaded {len(tasks)} quests"
            )

        self.set_tasks(tasks)


    def show_error(self, message: str) -> None:
        self.status.setText("Could not download quests")
        self.details.setHtml(
            f"<h2>Connection error</h2><p>{esc(message)}</p>"
            "<p>Check your connection and click Refresh.</p>"
        )

    # ---------- QUEST SEARCH ----------

    def set_tasks(self, tasks: list[dict]) -> None:

        self.tasks = tasks

        self.quest_by_id = {
            get_quest_id(task.get("id")): task
            for task in tasks
            if get_quest_id(task.get("id"))
        }

        self.dependents_by_id = build_reverse_requirements(tasks)


        self.filter_tasks()
        self._select_pending_quest()
        self.refresh_home_pins()

    def filter_tasks(self) -> None:
        query = self.search.text().strip().casefold()

        self.filtered_tasks = [
            task for task in self.tasks
            if query in name_of(task.get("name")).casefold()
        ]

        self.quest_list.blockSignals(True)
        self.quest_list.clear()

        for task in self.filtered_tasks:
            self.quest_list.addItem(
                name_of(task.get("name"))
            )

        self.quest_list.blockSignals(False)

        if self.filtered_tasks:
            self.quest_list.setCurrentRow(0)
        elif self.tasks:
            self.details.setHtml("<p>No quests found.</p>")
            self.update_quest_actions()
            self.objectives_scroll.setVisible(False)
    
    # ---------- QUEST DETAILS ----------
    
    
    def get_selected_quest(self) -> dict | None:
        """Return the currently selected quest."""
    
        row = self.quest_list.currentRow()
    
        if 0 <= row < len(self.filtered_tasks):
            return self.filtered_tasks[row]
    
        return None
    
    
    def update_quest_actions(self) -> None:
        """Load saved progress for the selected quest."""
    
        quest = self.get_selected_quest()
        quest_id = str(quest.get("id") or "") if quest else ""
    
        valid = bool(quest_id)
    
        self.pin_button.setEnabled(valid)
        self.completed_button.setEnabled(valid)
    
        if valid:
            mode = self.mode.currentData()
            state = self.progress.get_state(mode, quest_id)
        else:
            state = {"pinned": False, "completed": False}
    
        # Block signals while updating the interface
        for button, checked in (
            (self.pin_button, state["pinned"]),
            (self.completed_button, state["completed"]),
        ):
            previous = button.blockSignals(True)
            button.setChecked(checked)
            button.blockSignals(previous)
    
        self.pin_button.setText(
            "Unpin Quest" if state["pinned"] else "Pin Quest"
        )
    
        self.completed_button.setText(
            "Mark Incomplete"
            if state["completed"]
            else "Mark Completed"
        )
    
    
    def on_pin_toggled(self, checked: bool) -> None:
        """Save the pinned state of a quest."""
    
        quest = self.get_selected_quest()
    
        if not quest or not quest.get("id"):
            return
    
        mode = self.mode.currentData()
        quest_id = str(quest["id"])
    
        self.progress.set_pinned(
            mode, quest_id, checked
        )
    
        self.pin_button.setText(
            "Unpin Quest" if checked else "Pin Quest"
        )
    
        self.status.setText(
            "Quest pinned" if checked else "Quest unpinned"
        )

        self.refresh_home_pins()
    
    
    def on_completed_toggled(self, checked: bool) -> None:
        """Save the completion state of a quest."""
    
        quest = self.get_selected_quest()
    
        if not quest or not quest.get("id"):
            return
    
        mode = self.mode.currentData()
        quest_id = str(quest["id"])
    
        self.progress.set_completed(
            mode, quest_id, checked
        )
    
        self.completed_button.setText(
            "Mark Incomplete" if checked else "Mark Completed"
        )
    
        self.status.setText(
            "Quest completed" if checked else "Quest marked incomplete"
        )

        self.refresh_home_pins()
    

    def render_dependencies_html(self, task: dict) -> str:
        """Render quest prerequisites and related future quests."""

        parts = ["<hr><h3>Quest Dependencies</h3>"]

        # Minimum player level
        level = task.get("minPlayerLevel")

        if isinstance(level, (int, float)) and level > 1:
            parts.append(
                f"<p><b>Minimum PMC Level:</b> {int(level)}</p>"
            )

        # Prerequisite quests
        requirements = get_task_requirements(task)

        parts.append("<h4>Required Quests</h4>")

        if requirements:
            parts.append("<ul>")

            for quest_id, statuses in requirements:
                required_task = self.quest_by_id.get(quest_id)

                if required_task:
                    name = esc(name_of(required_task.get("name")))
                    label = (
                        f'<a href="quest://{esc(quest_id)}">'
                        f"{name}</a>"
                    )
                else:
                    label = "Quest unavailable in this mode"

                condition = (
                    " or ".join(statuses)
                    if statuses else "unspecified"
                )

                parts.append(
                    f"<li>{label} — Required state: "
                    f"{esc(condition)}</li>"
                )

            parts.append("</ul>")
        else:
            parts.append("<p>No direct quest prerequisites listed.</p>")

        # Other requirements may include trader loyalty,
        # faction, special conditions or delays.
        if task.get("traderRequirements") or task.get("otherRequirements"):
            parts.append(
                "<p><i>Additional unlock conditions exist. "
                "Detailed conditions will be added in a "
                "future update.</i></p>"
            )

        # Quests that depend on this one
        current_id = get_quest_id(task.get("id"))
        dependents = self.dependents_by_id.get(current_id, [])

        parts.append("<h4>Dependent Quests</h4>")

        if dependents:
            parts.append("<ul>")

            dependents = sorted(
                dependents,
                key=lambda entry: name_of(
                    entry[0].get("name")
                ).casefold()
            )

            for next_task, statuses in dependents:
                next_id = get_quest_id(next_task.get("id"))
                name = esc(name_of(next_task.get("name")))

                condition = (
                    " or ".join(statuses)
                    if statuses else "unspecified"
                )

                parts.append(
                    f'<li><a href="quest://{esc(next_id)}">'
                    f"{name}</a> — Requires: "
                    f"{esc(condition)}</li>"
                )

            parts.append("</ul>")
        else:
            parts.append("<p>No dependent quests listed.</p>")

        parts.append(
            "<p><i>These are direct relationships from the API, "
            "not a guarantee that a quest is currently unlocked."
            "</i></p>"
        )

        return "".join(parts)


    
    def render_objectives(self, task: dict) -> None:
        """Render interactive controls for quest objectives."""
    
        mode = self.mode.currentData()
        quest_id = str(task.get("id") or "")
    
        objectives = task.get("objectives") or []
    
        if isinstance(objectives, dict):
            objectives = list(objectives.values())
    
        if not isinstance(objectives, list):
            objectives = []
    
        # Create a new container for the selected quest
        container = QWidget()
        layout = QVBoxLayout(container)
    
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)
    
        title = QLabel("OBJECTIVE TRACKER")
        title.setStyleSheet(
            "color: #bdd393; font-weight: bold;"
        )
        layout.addWidget(title)
    
        visible_count = 0
    
        for objective in objectives:
            if not isinstance(objective, dict):
                continue
            
            description = objective.get("description")
    
            if not description:
                continue
            
            visible_count += 1
    
            objective_id = str(objective.get("id") or "")
            can_track = bool(quest_id and objective_id)
    
            # Determine the required quantity
            raw_count = objective.get("count")
    
            if (
                isinstance(raw_count, (int, float))
                and not isinstance(raw_count, bool)
                and raw_count > 1
            ):
                required = int(raw_count)
            else:
                required = 1
    
            # Read previously saved progress
            saved = 0
    
            if can_track:
                saved = self.progress.get_objective_progress(
                    mode, quest_id, objective_id
                )
    
            if required > 1:
                # Numeric objectives
                label = QLabel(str(description))
                label.setWordWrap(True)
    
                layout.addWidget(label)
    
                counter = QSpinBox()
                counter.setRange(0, required)
                counter.setValue(min(saved, required))
                counter.setSuffix(f" / {required}")
    
                counter.setButtonSymbols(
                    QAbstractSpinBox.ButtonSymbols.PlusMinus
                )
    
                counter.setFixedWidth(125)
                counter.setEnabled(can_track)
    
                if can_track:
                    counter.valueChanged.connect(
                        lambda value, m=mode, q=quest_id,
                        o=objective_id:
                        self.progress.set_objective_progress(
                            m, q, o, value
                        )
                    )
    
                layout.addWidget(counter)
    
            else:
                # Objectives without a numeric quantity
                row = QHBoxLayout()
    
                checkbox = QCheckBox()
                checkbox.setChecked(saved >= 1)
                checkbox.setEnabled(can_track)
    
                label = QLabel(str(description))
                label.setWordWrap(True)
    
                if can_track:
                    checkbox.toggled.connect(
                        lambda checked, m=mode, q=quest_id,
                        o=objective_id:
                        self.progress.set_objective_progress(
                            m, q, o, int(checked)
                        )
                    )
    
                row.addWidget(checkbox)
                row.addWidget(label, 1)
    
                layout.addLayout(row)
    
            if not can_track:
                warning = QLabel(
                    "Tracking unavailable: missing objective ID."
                )
                warning.setStyleSheet(
                    "color: #c9a36d; font-size: 11px;"
                )
                layout.addWidget(warning)
    
        if visible_count == 0:
            layout.addWidget(
                QLabel("No objectives available.")
            )
    
        layout.addStretch()
    
        # Replaces the previous quest's tracker widget
        self.objectives_scroll.setWidget(container)
        self.objectives_scroll.setVisible(True)
        # Set the initial panel proportions only once
        if not getattr(self, "_tracker_size_initialized", False):
            self.details_splitter.setSizes([500, 180])
            self._tracker_size_initialized = True
    

    def on_details_link_clicked(self, url) -> None:
        """Handle internal quest links and external wiki links."""

        if url.scheme() == "quest":
            quest_id = url.host()

            if quest_id in self.quest_by_id:
                self.open_pinned_quest(quest_id)

        elif url.scheme() in ("https", "http"):
            QDesktopServices.openUrl(url)

    
    def show_task(self, row: int) -> None:
        """Display a quest and its interactive objectives."""

        if not 0 <= row < len(self.filtered_tasks):
            return

        task = self.filtered_tasks[row]
        self.guide_button.setEnabled(
            bool(get_quest_guide(task))
        )

        # Update text, objectives and saved quest state
        self.refresh_selected_reward_details()
        self.render_objectives(task)
        self.update_quest_actions()

        # Resolve only the reward item names needed by this quest
        item_ids = get_reward_item_ids(task)

        self.item_catalog.ensure_names(
            item_ids,
            self.refresh_selected_reward_details,
        )

    def refresh_selected_reward_details(self) -> None:
        """Refresh text without recreating objective controls."""

        task = self.get_selected_quest()

        if task is None:
            return

        name = esc(name_of(task.get("name")))
        trader = esc(get_trader_name(task.get("trader")))

        parts = [
            f"<h2>{name}</h2>",
            f"<p><b>Trader:</b> {trader}</p>",
        ]

        parts.append(
            render_reward_html(
                task,
                self.item_catalog.names,
            )
        )

        parts.append(
            self.render_dependencies_html(task)
        )

        link = task.get("wikiLink")

        if (
            isinstance(link, str)
            and urlparse(link).scheme in ("https", "http")
        ):
            parts.append(
                f'<p><a href="{esc(link)}">'
                "Open original wiki guide</a></p>"
            )

        self.details.setHtml("".join(parts))

    def open_location_guide(self) -> None:
        """Open the visual guide for the selected quest."""

        task = self.get_selected_quest()

        if task is None:
            return

        images = get_quest_guide(task)

        if not images:
            return

        dialog = GuideDialog(
            name_of(task.get("name")),
            images,
            self.guide_images,
            self,
        )

        dialog.exec()
