
"""Approve wiki images and create a curated quest guide."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit


ROOT_DIR = Path(__file__).resolve().parents[1]
CANDIDATES_DIR = ROOT_DIR / "cache" / "guide_candidates"
GUIDES_DIR = ROOT_DIR / "guides"


def load_objectives(quest_id: str) -> list[dict]:
    """Find quest objectives in the local API cache."""

    for mode in ("regular", "pve"):
        path = ROOT_DIR / "cache" / f"tasks_{mode}.json"

        if not path.is_file():
            continue

        tasks = json.loads(path.read_text(encoding="utf-8"))

        for task in tasks:
            if task.get("id") == quest_id:
                return [
                    objective
                    for objective in task.get("objectives", [])
                    if isinstance(objective, dict)
                ]

    return []


def parse_selection(value: str, total: int) -> list[int]:
    """Parse ordered image numbers, rejecting invalid selections."""

    parts = [
        part.strip()
        for part in value.replace(" ", ",").split(",")
        if part.strip()
    ]

    try:
        numbers = [int(part) for part in parts]
    except ValueError as error:
        raise ValueError("Use numbers separated by commas.") from error

    if not numbers:
        raise ValueError("Select at least one image.")

    if len(numbers) != len(set(numbers)):
        raise ValueError("Image numbers cannot be repeated.")

    if any(number < 1 or number > total for number in numbers):
        raise ValueError("An image number is out of range.")

    return numbers


def main() -> None:
    """Interactively review candidates and save a quest guide."""

    parser = argparse.ArgumentParser()
    parser.add_argument("quest_id")
    arguments = parser.parse_args()

    quest_id = arguments.quest_id

    if (
        len(quest_id) != 24
        or any(char not in "0123456789abcdef" for char in quest_id)
    ):
        parser.error("Expected a 24-character lowercase quest ID.")

    candidate_path = CANDIDATES_DIR / f"{quest_id}.json"
    output_path = GUIDES_DIR / f"{quest_id}.json"

    if not candidate_path.is_file():
        parser.error("Candidate JSON not found. Run wiki_image_probe.py first.")

    if output_path.exists():
        parser.error(
            "An approved guide already exists. "
            "This tool will not overwrite it."
        )

    data = json.loads(candidate_path.read_text(encoding="utf-8"))

    if data.get("quest_id") != quest_id:
        parser.error("Candidate quest ID does not match.")

    candidates = data.get("images", [])

    if not candidates:
        parser.error("No candidate images found.")

    print(f"\nQuest: {data['quest_name']}")
    print("\nAvailable images:\n")

    for number, image in enumerate(candidates, start=1):
        print(f"  {number}. {image['title']}")

    print("\nEnter images in the order they should appear.")

    try:
        selection = parse_selection(
            input("Image numbers: "),
            len(candidates),
        )
    except ValueError as error:
        parser.error(str(error))

    objectives = load_objectives(quest_id)

    print("\nQuest objectives:")

    for index, objective in enumerate(objectives, start=1):
        print(f"  {index}. {objective.get('description', '')}")

    print("  0. General quest image (no objective association)")

    approved = []

    for number in selection:
        candidate = candidates[number - 1]

        print(f"\n--- Image {number} ---")
        print(candidate["title"])

        default_title = candidate["title"].removeprefix("File:")
        default_title = Path(default_title).stem

        title = input(
            f"Display title [{default_title}]: "
        ).strip() or default_title

        description = input(
            "Description in English: "
        ).strip()

        if not description:
            parser.error("Each approved image needs a description.")

        default_objective = 1 if objectives else 0

        raw_objective = input(
            f"Objective number [{default_objective}]: "
        ).strip()

        try:
            objective_number = (
                int(raw_objective)
                if raw_objective
                else default_objective
            )
        except ValueError:
            parser.error("Invalid objective number.")

        if not 0 <= objective_number <= len(objectives):
            parser.error("Objective number out of range.")

        url = candidate.get("url", "")

        if urlsplit(url).scheme != "https":
            parser.error("Image URL must use HTTPS.")

        image_data = {
            "title": title,
            "description": description,
            "url": url,
            "source": (
                candidate.get("source")
                or data["wiki_url"]
            ),
        }

        if objective_number:
            image_data["objective_id"] = objectives[
                objective_number - 1
            ].get("id")

        approved.append(image_data)

    guide = {
        "quest_id": quest_id,
        "name": data["quest_name"],
        "images": approved,
    }

    print(f"\nApproved images: {len(approved)}")
    print(f"Destination: {output_path}")

    confirmation = input("Save this guide? [y/N]: ").strip().lower()

    if confirmation != "y":
        print("Cancelled. No files changed.")
        return

    GUIDES_DIR.mkdir(parents=True, exist_ok=True)

    output_path.write_text(
        json.dumps(guide, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print("\nGuide saved successfully!")


if __name__ == "__main__":
    main()
