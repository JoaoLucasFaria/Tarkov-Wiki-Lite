
"""Discover wiki image candidates for a small batch of quests."""

import argparse
import csv
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError

from wiki_image_probe import (
    ROOT_DIR,
    fetch_image_details,
    fetch_images,
    get_page_title,
    save_preview,
)


REPORT_PATH = ROOT_DIR / "cache" / "guide_coverage.csv"
CANDIDATES_DIR = ROOT_DIR / "cache" / "guide_candidates"
GUIDES_DIR = ROOT_DIR / "guides"

REQUEST_DELAY = 5.0


def load_pending_quests(priority: str) -> list[dict]:
    """Find quests without an approved guide or candidate report."""

    with REPORT_PATH.open(
        newline="",
        encoding="utf-8-sig",
    ) as file:
        rows = list(csv.DictReader(file))

    pending = []

    for quest in rows:
        if quest.get("priority") != priority:
            continue

        quest_id = quest.get("quest_id", "")

        if not re.fullmatch(r"[0-9a-f]{24}", quest_id):
            continue

        if not quest.get("wiki_link"):
            continue

        approved_path = GUIDES_DIR / f"{quest_id}.json"
        candidate_path = CANDIDATES_DIR / f"{quest_id}.json"

        if approved_path.exists() or candidate_path.exists():
            continue

        pending.append(quest)

    return pending


def main() -> None:
    """Discover candidate images without approving them automatically."""

    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Number of quests to inspect (1-10)",
    )

    parser.add_argument(
        "--priority",
        choices=("High", "Medium", "Low"),
        default="High",
    )

    args = parser.parse_args()

    if not 1 <= args.limit <= 100:
        parser.error("--limit must be between 1 and 10")

    pending = load_pending_quests(args.priority)

    batch = pending[:args.limit]

    print(f"\nPriority: {args.priority}")
    print(f"Pending quests: {len(pending)}")
    print(f"Selected for this batch: {len(batch)}")

    succeeded = 0
    failed = 0

    for index, quest in enumerate(batch, start=1):
        quest_id = quest["quest_id"]
        quest_name = quest["name"]

        if index > 1:
            time.sleep(REQUEST_DELAY)

        print(f"\n[{index}/{len(batch)}] {quest_name}")
        print(f"Quest ID: {quest_id}")

        try:
            page_title = get_page_title(quest["wiki_link"])

            file_titles = fetch_images(page_title)

            print(f"Files discovered: {len(file_titles)}")

            if not file_titles:
                print("No image references found.")
                failed += 1
                continue

            images = fetch_image_details(file_titles)

            print(f"Images resolved: {len(images)}")

            if not images:
                print("No usable image URLs returned.")
                failed += 1
                continue

            save_preview(quest, images)

            print(
                "Review command: "
                f"python tools/guide_review_manager.py open {quest_id}"
            )

            succeeded += 1

        except (
            HTTPError,
            URLError,
            TimeoutError,
            ValueError,
            OSError,
        ) as error:
            print(f"Lookup failed: {error}")
            failed += 1

            if isinstance(error, HTTPError) and error.code == 429:
                print("Rate limit reached. Stopping this batch.")
                break

    print("\n=== BATCH RESULTS ===")
    print(f"Successful: {succeeded}")
    print(f"Failed or empty: {failed}")
    print("Approved guides were not modified.")


if __name__ == "__main__":
    main()
