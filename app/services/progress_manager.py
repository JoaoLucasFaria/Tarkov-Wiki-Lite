"""Local quest progress storage using SQLite."""

import sqlite3
from contextlib import closing
from pathlib import Path


class ProgressManager:
    """Manage manually recorded quest progress."""

    VALID_MODES = ("regular", "pve")
    VALID_FLAGS = ("completed", "pinned")

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)

        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        self._initialize_database()

    def _connect(self):
        """Create a connection to the local database."""
        return sqlite3.connect(self.database_path)

    
    def _initialize_database(self) -> None:
        """Initialize all required progress database tables."""
    
        with closing(self._connect()) as connection:
            with connection:
                # Quest completion and pinned states
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS quest_progress (
                        mode TEXT NOT NULL,
                        quest_id TEXT NOT NULL,
                        completed INTEGER NOT NULL DEFAULT 0,
                        pinned INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    
                        PRIMARY KEY (mode, quest_id)
                    )
                """)
    
                # Individual objective progress
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS objective_progress (
                        mode TEXT NOT NULL,
                        quest_id TEXT NOT NULL,
                        objective_id TEXT NOT NULL,
                        progress INTEGER NOT NULL DEFAULT 0
                            CHECK(progress >= 0),
                        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    
                        PRIMARY KEY (
                            mode,
                            quest_id,
                            objective_id
                        )
                    )
                """)
    

    def _validate(self, mode: str, quest_id: str) -> None:
        if mode not in self.VALID_MODES:
            raise ValueError("Invalid game mode.")

        if not isinstance(quest_id, str) or not quest_id:
            raise ValueError("Invalid quest ID.")

    def get_state(self, mode: str, quest_id: str) -> dict:
        """Return saved completion and pin states."""

        self._validate(mode, quest_id)

        with closing(self._connect()) as connection:
            row = connection.execute("""
                SELECT completed, pinned
                FROM quest_progress
                WHERE mode = ? AND quest_id = ?
            """, (mode, quest_id)).fetchone()

        if row is None:
            return {"completed": False, "pinned": False}

        return {
            "completed": bool(row[0]),
            "pinned": bool(row[1])
        }

    def _set_flag(
        self,
        mode: str,
        quest_id: str,
        flag: str,
        value: bool
    ) -> None:
        """Update a validated quest progress flag."""

        self._validate(mode, quest_id)

        if flag not in self.VALID_FLAGS:
            raise ValueError("Invalid progress flag.")

        with closing(self._connect()) as connection:
            with connection:
                connection.execute(f"""
                    INSERT INTO quest_progress
                        (mode, quest_id, {flag})
                    VALUES (?, ?, ?)
                    ON CONFLICT(mode, quest_id)
                    DO UPDATE SET
                        {flag} = excluded.{flag},
                        updated_at = CURRENT_TIMESTAMP
                """, (mode, quest_id, int(value)))

    def set_completed(
        self, mode: str, quest_id: str, completed: bool
    ) -> None:
        """Save whether a quest has been completed."""

        self._set_flag(mode, quest_id, "completed", completed)

    def set_pinned(
        self, mode: str, quest_id: str, pinned: bool
    ) -> None:
        """Save whether a quest is pinned."""

        self._set_flag(mode, quest_id, "pinned", pinned)

    def get_pinned_quests(self, mode: str) -> list[str]:
        """Return IDs of pinned quests."""

        if mode not in self.VALID_MODES:
            raise ValueError("Invalid game mode.")

        with closing(self._connect()) as connection:
            rows = connection.execute("""
                SELECT quest_id
                FROM quest_progress
                WHERE mode = ? AND pinned = 1
                ORDER BY updated_at DESC
            """, (mode,)).fetchall()

        return [row[0] for row in rows]

    
    def get_objective_progress(
        self,
        mode: str,
        quest_id: str,
        objective_id: str
    ) -> int:
        """Return the manually saved objective progress."""

        self._validate(mode, quest_id)

        if not objective_id:
            raise ValueError("Invalid objective ID.")

        with closing(self._connect()) as connection:
            row = connection.execute("""
                SELECT progress
                FROM objective_progress
                WHERE mode = ?
                  AND quest_id = ?
                  AND objective_id = ?
            """, (mode, quest_id, objective_id)).fetchone()

        return int(row[0]) if row else 0


    def set_objective_progress(
        self,
        mode: str,
        quest_id: str,
        objective_id: str,
        progress: int
    ) -> None:
        """Save the progress of a single quest objective."""

        self._validate(mode, quest_id)

        if not isinstance(objective_id, str) or not objective_id:
            raise ValueError("Invalid objective ID.")

        if type(progress) is not int or progress < 0:
            raise ValueError("Progress must be a non-negative integer.")

        with closing(self._connect()) as connection:
            with connection:
                connection.execute("""
                    INSERT INTO objective_progress
                        (mode, quest_id, objective_id, progress)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(mode, quest_id, objective_id)
                    DO UPDATE SET
                        progress = excluded.progress,
                        updated_at = CURRENT_TIMESTAMP
                """, (mode, quest_id, objective_id, progress))

    
    def get_quest_objective_progress(
        self,
        mode: str,
        quest_id: str
    ) -> dict[str, int]:
        """Return all saved objective progress for a quest."""
    
        self._validate(mode, quest_id)
    
        with closing(self._connect()) as connection:
            rows = connection.execute("""
                SELECT objective_id, progress
                FROM objective_progress
                WHERE mode = ? AND quest_id = ?
            """, (mode, quest_id)).fetchall()
    
        return {
            objective_id: int(progress)
            for objective_id, progress in rows
        }

