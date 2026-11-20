"""Independent companion window for pinned Tarkov quests."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.models.quest import name_of
from app.services.cache_manager import CacheManager
from app.services.progress_manager import ProgressManager
from pathlib import Path
from PySide6.QtCore import QSettings, QByteArray


class CompanionWindow(QWidget):
    """Display pinned quests in a separate desktop window."""

    def __init__(
        self,
        progress: ProgressManager,
        cache: CacheManager,
        mode: str = "regular",
    ) -> None:
        super().__init__()

        # Save window preferences on the local HD
        project_dir = Path(__file__).resolve().parents[2]
        settings_dir = project_dir / "config"
        settings_dir.mkdir(parents=True, exist_ok=True)

        self.settings = QSettings(
            str(settings_dir / "preferences.ini"),
            QSettings.Format.IniFormat
        )

        self.geometry_restored = False

        self.progress = progress
        self.cache = cache
        self.mode = mode

        self.setWindowTitle("Tarkov Wiki Lite - Companion")
        self.resize(420, 650)
        self.setMinimumSize(320, 350)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        # Header
        header = QHBoxLayout()

        title = QLabel("RAID COMPANION")
        title.setStyleSheet(
            "color: #bdd393; font-size: 18px; font-weight: bold;"
        )

        self.mode_label = QLabel()

        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)

        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.mode_label)
        header.addWidget(refresh_button)

        root.addLayout(header)

        # Scrollable quest list
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        root.addWidget(self.scroll, 1)

        footer = QLabel(
            "Manual tracking only - no game integration"
        )
        footer.setStyleSheet(
            "color: #82989d; font-size: 11px;"
        )
        root.addWidget(footer)

        self.setStyleSheet("""
            QWidget {
                background-color: #151e23;
                color: #e6ecef;
                font-family: 'Segoe UI';
                font-size: 12px;
            }

            QFrame#QuestCard {
                background-color: #22302d;
                border: 1px solid #405348;
                border-radius: 8px;
            }

            QPushButton, QSpinBox {
                background-color: #2a393d;
                border: 1px solid #4b5d60;
                border-radius: 5px;
                padding: 6px;
            }

            QPushButton:hover {
                background-color: #3b5144;
            }

            QScrollArea {
                border: none;
            }
        """)

        self.refresh()

        # Restore the previous window position and size
        saved_geometry = self.settings.value("companion/geometry")

        if isinstance(saved_geometry, QByteArray):
            self.geometry_restored = self.restoreGeometry(
                saved_geometry
            )

    def set_mode(self, mode: str) -> None:
        """Change the displayed game mode."""
        if mode not in ("regular", "pve"):
            raise ValueError("Invalid game mode.")

        self.mode = mode
        self.refresh()

    def refresh(self) -> None:
        """Reload pinned quests and their saved objectives."""

        self.mode_label.setText(
            "PvP" if self.mode == "regular" else "PvE"
        )

        # Replace the previous content
        old_widget = self.scroll.takeWidget()

        if old_widget is not None:
            old_widget.deleteLater()

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(12)

        pinned_ids = self.progress.get_pinned_quests(
            self.mode
        )

        tasks = self.cache.load_tasks(self.mode) or []

        tasks_by_id = {
            str(task["id"]): task
            for task in tasks
            if task.get("id")
        }

        if not pinned_ids:
            empty = QLabel(
                "No pinned quests.\n\n"
                "Pin a quest in the Quests tab first."
            )
            empty.setWordWrap(True)
            layout.addWidget(empty)

        for quest_id in pinned_ids:
            task = tasks_by_id.get(quest_id)

            if task is None:
                layout.addWidget(
                    QLabel(
                        f"Quest {quest_id[:8]}: "
                        "cached data unavailable."
                    )
                )
                continue

            self.add_quest_card(
                layout, task, quest_id
            )

        layout.addStretch()
        self.scroll.setWidget(container)

    def closeEvent(self, event) -> None:
       """Save window geometry when the companion closes."""
    
       self.settings.setValue(
           "companion/geometry",
           self.saveGeometry()
       )
    
       self.settings.sync()
    
       super().closeEvent(event)

    def add_quest_card(
        self,
        parent_layout: QVBoxLayout,
        task: dict,
        quest_id: str,
    ) -> None:
        """Create a card with interactive quest objectives."""

        card = QFrame()
        card.setObjectName("QuestCard")

        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        name = QLabel(name_of(task.get("name")))
        name.setWordWrap(True)
        name.setTextFormat(Qt.TextFormat.PlainText)
        name.setStyleSheet(
            "color: #bdd393; font-size: 14px;"
            "font-weight: bold;"
        )
        layout.addWidget(name)

        state = self.progress.get_state(
            self.mode, quest_id
        )

        if state["completed"]:
            done = QLabel("QUEST COMPLETED")
            done.setStyleSheet("color: #a8cb8a;")
            layout.addWidget(done)

        objectives = task.get("objectives") or []

        if isinstance(objectives, dict):
            objectives = list(objectives.values())

        if not isinstance(objectives, list):
            objectives = []

        for objective in objectives:
            if not isinstance(objective, dict):
                continue

            description = objective.get("description")
            objective_id = str(objective.get("id") or "")

            if not description:
                continue

            label = QLabel(str(description))
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            layout.addWidget(label)

            raw_count = objective.get("count")

            required = (
                int(raw_count)
                if isinstance(raw_count, (int, float))
                and not isinstance(raw_count, bool)
                and raw_count > 1
                else 1
            )

            saved = 0

            if objective_id:
                saved = self.progress.get_objective_progress(
                    self.mode, quest_id, objective_id
                )

            if required > 1:
                counter = QSpinBox()
                counter.setRange(0, required)
                counter.setValue(min(saved, required))
                counter.setSuffix(f" / {required}")
                counter.setFixedWidth(125)

                counter.setButtonSymbols(
                    QAbstractSpinBox.ButtonSymbols.PlusMinus
                )

                counter.setEnabled(bool(objective_id))

                if objective_id:
                    counter.valueChanged.connect(
                        lambda value,
                        m=self.mode,
                        q=quest_id,
                        o=objective_id:
                            self.progress.set_objective_progress(
                                m, q, o, value
                            )
                    )

                layout.addWidget(counter)

            else:
                checkbox = QCheckBox("Completed")
                checkbox.setChecked(saved >= 1)
                checkbox.setEnabled(bool(objective_id))

                if objective_id:
                    checkbox.toggled.connect(
                        lambda checked,
                        m=self.mode,
                        q=quest_id,
                        o=objective_id:
                            self.progress.set_objective_progress(
                                m, q, o, int(checked)
                            )
                    )

                layout.addWidget(checkbox)

        parent_layout.addWidget(card)
