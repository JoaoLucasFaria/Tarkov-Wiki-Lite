
"""Local JSON cache management for Tarkov Wiki Lite."""

import json
from pathlib import Path


class CacheManager:
    """Read and write cached quest data."""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir

    def get_cache_path(self, mode: str) -> Path:
        """Return the cache file for a game mode."""

        if mode not in ("regular", "pve"):
            raise ValueError(f"Invalid game mode: {mode}")

        return self.cache_dir / f"tasks_{mode}.json"

    def load_tasks(self, mode: str) -> list[dict] | None:
        """Load cached quests, if valid data exists."""

        path = self.get_cache_path(mode)

        try:
            tasks = json.loads(
                path.read_text(encoding="utf-8")
            )

        except (OSError, ValueError, UnicodeError):
            return None

        if (
            not isinstance(tasks, list)
            or not tasks
            or not all(isinstance(task, dict) for task in tasks)
        ):
            return None

        return tasks

    def save_tasks(
        self, mode: str, tasks: list[dict]
    ) -> None:
        """Save quest data to the local cache."""

        path = self.get_cache_path(mode)

        self.cache_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        path.write_text(
            json.dumps(tasks, ensure_ascii=False),
            encoding="utf-8"
        )
