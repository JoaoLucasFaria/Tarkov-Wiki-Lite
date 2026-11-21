
"""Audit local quest guide metadata without downloading images."""

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
GUIDES_DIR = ROOT / "guides"
CACHE_DIR = ROOT / "cache"

REQUIRED_FIELDS = ("title", "description", "url", "source")
DECORATIVE_WORDS = ("banner", "splash", "wallpaper", "logo")


def load_quests() -> dict:
    """Collect known quest IDs and objective IDs from both modes."""

    quests = defaultdict(set)

    for mode in ("regular", "pve"):
        path = CACHE_DIR / f"tasks_{mode}.json"

        if not path.is_file():
            continue

        tasks = json.loads(path.read_text(encoding="utf-8"))

        for task in tasks:
            quest_id = task.get("id")

            if not quest_id:
                continue

            quests[quest_id]

            for objective in task.get("objectives") or []:
                if isinstance(objective, dict):
                    objective_id = objective.get("id")

                    if objective_id:
                        quests[quest_id].add(objective_id)

    return quests


def audit_guide(path: Path, quests: dict) -> dict:
    """Check a single guide for structural and metadata problems."""

    issues = set()
    image_count = 0
    quest_id = path.stem

    try:
        guide = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {
            "quest_id": quest_id,
            "name": "",
            "images": 0,
            "issues": "invalid_json",
        }

    if not isinstance(guide, dict):
        return {
            "quest_id": quest_id,
            "name": "",
            "images": 0,
            "issues": "invalid_structure",
        }

    if not re.fullmatch(r"[0-9a-f]{24}", quest_id):
        issues.add("invalid_filename")

    if guide.get("quest_id") != quest_id:
        issues.add("quest_id_mismatch")

    if quest_id not in quests:
        issues.add("unknown_quest")

    name = str(guide.get("name") or quest_id)
    images = guide.get("images")

    if not isinstance(images, list) or not images:
        issues.add("missing_images")
        images = []

    image_count = len(images)

    if image_count > 20:
        issues.add("large_guide")

    seen_urls = set()

    for image in images:
        if not isinstance(image, dict):
            issues.add("invalid_image_entry")
            continue

        for field in REQUIRED_FIELDS:
            value = image.get(field)

            if not isinstance(value, str) or not value.strip():
                issues.add(f"missing_{field}")

        url = image.get("url")

        if isinstance(url, str):
            parsed = urlsplit(url)

            if parsed.scheme != "https" or not parsed.netloc:
                issues.add("invalid_image_url")

            if url in seen_urls:
                issues.add("duplicate_image")

            seen_urls.add(url)

        source = image.get("source")

        if isinstance(source, str) and source:
            parsed = urlsplit(source)

            if parsed.scheme != "https" or not parsed.netloc:
                issues.add("invalid_source_url")

        objective_id = image.get("objective_id")

        if objective_id and objective_id not in quests.get(
            quest_id, set()
        ):
            issues.add("unknown_objective_id")

        title = str(image.get("title") or "").lower()

        if any(word in title for word in DECORATIVE_WORDS):
            issues.add("possible_decorative_image")

    return {
        "quest_id": quest_id,
        "name": name,
        "images": image_count,
        "issues": ", ".join(sorted(issues)) or "OK",
    }


def main() -> None:
    """Generate a CSV report for all local guides."""

    quests = load_quests()

    paths = sorted(GUIDES_DIR.glob("*.json"))
    results = [audit_guide(path, quests) for path in paths]

    output = CACHE_DIR / "guide_audit.csv"
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open(
        "w", newline="", encoding="utf-8-sig"
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["quest_id", "name", "images", "issues"],
        )

        writer.writeheader()
        writer.writerows(results)

    issue_counts = Counter()

    for result in results:
        if result["issues"] != "OK":
            issue_counts.update(result["issues"].split(", "))

    print("\n=== GUIDE AUDIT ===")
    print(f"Guide files: {len(paths)}")
    print(f"Image references: {sum(r['images'] for r in results)}")
    print(f"Guides without flags: {sum(r['issues'] == 'OK' for r in results)}")
    print(f"Guides flagged: {sum(r['issues'] != 'OK' for r in results)}")

    print("\n=== ISSUES TO REVIEW ===")

    for issue, count in issue_counts.most_common():
        print(f"{issue}: {count}")

    print(f"\nReport saved: {output}")


if __name__ == "__main__":
    main()
