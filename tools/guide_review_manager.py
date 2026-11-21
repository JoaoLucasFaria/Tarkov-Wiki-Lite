
"""Review wiki image candidates visually and import approved quest guides."""

import argparse
import json
import os
import re
import shutil
import webbrowser
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import urlsplit


ROOT_DIR = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT_DIR / "cache"
CANDIDATE_DIR = CACHE_DIR / "guide_candidates"
GUIDES_DIR = ROOT_DIR / "guides"


def read_json(path: Path):
    """Read a UTF-8 JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))


def validate_quest_id(quest_id: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{24}", quest_id):
        raise ValueError("Invalid quest ID (expected 24 lowercase hex characters).")


def load_objectives(quest_id: str) -> list[dict]:
    """Return unique objectives from the available PvP/PvE caches."""

    objectives = {}

    for mode in ("regular", "pve"):
        path = CACHE_DIR / f"tasks_{mode}.json"

        if not path.is_file():
            continue

        for task in read_json(path):
            if task.get("id") != quest_id:
                continue

            for objective in task.get("objectives") or []:
                if not isinstance(objective, dict):
                    continue

                objective_id = objective.get("id")

                if isinstance(objective_id, str) and objective_id:
                    objectives.setdefault(objective_id, {
                        "id": objective_id,
                        "description": str(
                            objective.get("description") or objective_id
                        ),
                    })

    return list(objectives.values())


def build_review(quest_id: str) -> None:
    """Build an editable HTML review page without downloading image files."""

    validate_quest_id(quest_id)

    candidate_path = CANDIDATE_DIR / f"{quest_id}.json"
    guide_path = GUIDES_DIR / f"{quest_id}.json"

    if not candidate_path.is_file():
        raise FileNotFoundError(f"Candidates missing: {candidate_path}")

    data = read_json(candidate_path)

    if data.get("quest_id") != quest_id:
        raise ValueError("Candidate quest ID mismatch.")

    existing = (
        read_json(guide_path)
        if guide_path.exists()
        else {"images": []}
    )

    candidates = data.get("images") or []
    original = existing.get("images") or []

    by_url = {
        item["url"]: item
        for item in candidates
        if isinstance(item, dict) and isinstance(item.get("url"), str)
    }

    ordered = []
    used = set()

    # Show previously approved images first, preserving their order.
    for image in original:
        url = image.get("url", "")
        candidate = by_url.get(url, {})

        ordered.append({
            "filename": candidate.get("title", image.get("title", "")),
            "title": image.get("title", ""),
            "description": image.get("description", ""),
            "url": url,
            "thumbnail_url": candidate.get("thumbnail_url", url),
            "source": (
                image.get("source")
                or candidate.get("source")
                or data.get("wiki_url", "")
            ),
            "objective_id": image.get("objective_id", ""),
            "selected": True,
        })

        used.add(url)

    # Add new candidates without automatically approving them.
    for item in candidates:
        url = item.get("url", "")

        if not url or url in used:
            continue

        filename = item.get("title", "")
        friendly_name = Path(
            filename.removeprefix("File:")
        ).stem

        ordered.append({
            "filename": filename,
            "title": friendly_name,
            "description": "",
            "url": url,
            "thumbnail_url": item.get("thumbnail_url") or url,
            "source": item.get("source") or data.get("wiki_url", ""),
            "objective_id": "",
            "selected": False,
        })

        used.add(url)

    payload = {
        "quest_id": quest_id,
        "name": (
            data.get("quest_name")
            or existing.get("name")
            or quest_id
        ),
        "objectives": load_objectives(quest_id),
        "images": ordered,
    }

    # Prevent embedded JSON from terminating the HTML script element.
    embedded = (
        json.dumps(payload, ensure_ascii=True)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )

    html_text = HTML_TEMPLATE.replace(
        "__QUEST_NAME__", escape(payload["name"])
    )
    html_text = html_text.replace("__DATA__", embedded)

    output = CANDIDATE_DIR / f"{quest_id}_review.html"
    output.write_text(html_text, encoding="utf-8")

    print(f"Review page: {output}")
    print(f"Previously approved images: {len(original)}")

    webbrowser.open(output.resolve().as_uri())


def apply_review(review_path: Path, replace: bool) -> None:
    """Validate an exported review and write its guide safely."""

    data = read_json(review_path)

    quest_id = data.get("quest_id", "")
    validate_quest_id(quest_id)

    name = data.get("name")
    images = data.get("images")

    if not isinstance(name, str) or not name.strip():
        raise ValueError("Guide name is required.")

    if not isinstance(images, list) or not images:
        raise ValueError("Select at least one image.")

    candidate_path = CANDIDATE_DIR / f"{quest_id}.json"

    if not candidate_path.is_file():
        raise ValueError("Candidate data not found for this quest.")

    candidates = read_json(candidate_path).get("images", [])

    permitted_urls = {
        item.get("url")
        for item in candidates
    }

    existing_path = GUIDES_DIR / f"{quest_id}.json"

    if existing_path.exists():
        for item in read_json(existing_path).get("images", []):
            permitted_urls.add(item.get("url"))

        if not replace:
            raise FileExistsError(
                "Guide already exists. Add --replace to edit it."
            )

    objective_ids = {
        item["id"]
        for item in load_objectives(quest_id)
    }

    cleaned = []
    used_urls = set()

    for item in images:
        if not isinstance(item, dict):
            raise ValueError("Invalid image entry.")

        for key in ("title", "description", "url", "source"):
            if (
                not isinstance(item.get(key), str)
                or not item[key].strip()
            ):
                raise ValueError(
                    f"Image missing required field: {key}"
                )

        url = item["url"]

        if url in used_urls or url not in permitted_urls:
            raise ValueError(
                "Duplicate or unknown image URL in review."
            )

        if any(
            urlsplit(item[key]).scheme != "https"
            for key in ("url", "source")
        ):
            raise ValueError(
                "Image and source URLs must use HTTPS."
            )

        used_urls.add(url)

        entry = {
            key: item[key].strip()
            for key in ("title", "description", "url", "source")
        }

        objective_id = item.get("objective_id")

        if objective_id:
            if objective_id not in objective_ids:
                raise ValueError(
                    f"Unknown objective ID: {objective_id}"
                )

            entry["objective_id"] = objective_id

        cleaned.append(entry)

    GUIDES_DIR.mkdir(parents=True, exist_ok=True)

    if existing_path.exists():
        backup_dir = CACHE_DIR / "guide_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S_%f"
        )

        backup = backup_dir / f"{quest_id}_{timestamp}.json"

        shutil.copy2(existing_path, backup)
        print(f"Backup: {backup}")

    content = {
        "quest_id": quest_id,
        "name": name.strip(),
        "images": cleaned,
    }

    temporary = existing_path.with_suffix(".json.tmp")

    try:
        temporary.write_text(
            json.dumps(
                content,
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )

        os.replace(temporary, existing_path)

    finally:
        temporary.unlink(missing_ok=True)

    print(
        f"Guide saved: {existing_path} "
        f"({len(cleaned)} images)"
    )


HTML_TEMPLATE = r'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">

    <title>Guide Review - __QUEST_NAME__</title>

    <style>
        body {
            background: #16191c;
            color: #eeeeee;
            font: 14px Arial, sans-serif;
            margin: 25px;
        }

        h1 { font-size: 23px; }
        p { color: #b3b9bf; }

        header {
            display: flex;
            align-items: center;
            gap: 15px;
            flex-wrap: wrap;
            position: sticky;
            top: 0;
            background: #16191c;
            padding: 10px 0;
            z-index: 2;
        }

        button {
            cursor: pointer;
            background: #405c49;
            color: white;
            border: 1px solid #7a9e80;
            padding: 8px 12px;
            border-radius: 5px;
        }

        button:disabled {
            opacity: 0.35;
            cursor: default;
        }

        .grid {
            display: grid;
            grid-template-columns:
                repeat(auto-fill, minmax(310px, 1fr));
            gap: 16px;
        }

        article {
            background: #242a2e;
            border: 1px solid #444;
            border-radius: 8px;
            overflow: hidden;
        }

        article.selected {
            border-color: #9ccd9a;
        }

        .preview {
            height: 220px;
            background: #101214;
            display: flex;
            justify-content: center;
            align-items: center;
        }

        .preview img {
            max-height: 100%;
            max-width: 100%;
            object-fit: contain;
        }

        .details {
            padding: 14px;
            display: grid;
            gap: 8px;
        }

        label {
            display: grid;
            gap: 4px;
        }

        input[type=text],
        textarea,
        select {
            box-sizing: border-box;
            width: 100%;
            padding: 8px;
            background: #141719;
            color: #eeeeee;
            border: 1px solid #63686b;
            border-radius: 4px;
        }

        textarea {
            height: 66px;
            resize: vertical;
        }

        a { color: #a9cfa4; }

        .actions {
            display: flex;
            gap: 8px;
            align-items: center;
            justify-content: space-between;
        }
    </style>
</head>

<body>
    <header>
        <h1>Guide Review — __QUEST_NAME__</h1>
        <span id="count"></span>
        <button id="export">Export approved JSON</button>
    </header>

    <p>
        Choose images, change their order with ↑/↓,
        write descriptions in English and associate the correct objective.
        Export downloads a .review.json file;
        it does not change the app directly.
    </p>

    <div class="grid" id="cards"></div>

    <script type="application/json" id="review-data">__DATA__</script>

    <script>
        const data = JSON.parse(
            document.getElementById('review-data').textContent
        );

        const cards = document.getElementById('cards');

        function field(label, node) {
            const wrap = document.createElement('label');
            const name = document.createElement('span');

            name.textContent = label;

            wrap.append(name, node);

            return wrap;
        }

        function render() {
            cards.replaceChildren();

            data.images.forEach((item, index) => {
                const card = document.createElement('article');

                if (item.selected) {
                    card.classList.add('selected');
                }

                const preview = document.createElement('div');
                preview.className = 'preview';

                const img = document.createElement('img');
                img.src = item.thumbnail_url;
                img.loading = 'lazy';
                img.alt = item.filename;

                preview.append(img);
                card.append(preview);

                const details = document.createElement('div');
                details.className = 'details';

                const actions = document.createElement('div');
                actions.className = 'actions';

                const check = document.createElement('input');
                check.type = 'checkbox';
                check.checked = item.selected;

                check.addEventListener('change', () => {
                    item.selected = check.checked;

                    card.classList.toggle(
                        'selected', item.selected
                    );

                    updateCount();
                });

                actions.append(field('Use this image', check));

                const up = document.createElement('button');
                up.textContent = '↑';
                up.title = 'Move up';
                up.disabled = index === 0;
                up.onclick = () => move(index, -1);

                const down = document.createElement('button');
                down.textContent = '↓';
                down.title = 'Move down';
                down.disabled = index === data.images.length - 1;
                down.onclick = () => move(index, 1);

                actions.append(up, down);
                details.append(actions);

                const filename = document.createElement('strong');
                filename.textContent = item.filename;
                details.append(filename);

                const title = document.createElement('input');
                title.type = 'text';
                title.value = item.title;

                title.addEventListener('input', () => {
                    item.title = title.value;
                });

                details.append(field('Display title', title));

                const description = document.createElement('textarea');
                description.value = item.description;

                description.addEventListener('input', () => {
                    item.description = description.value;
                });

                details.append(
                    field('Description (English)', description)
                );

                const select = document.createElement('select');

                const general = document.createElement('option');
                general.value = '';
                general.textContent = 'General / no objective';
                select.append(general);

                data.objectives.forEach((objective, i) => {
                    const option = document.createElement('option');

                    option.value = objective.id;
                    option.textContent =
                        `${i + 1}. ${objective.description}`;

                    select.append(option);
                });

                select.value = item.objective_id || '';

                select.addEventListener('change', () => {
                    item.objective_id = select.value;
                });

                details.append(field('Quest objective', select));

                const link = document.createElement('a');
                link.href = item.url;
                link.target = '_blank';
                link.rel = 'noopener noreferrer';
                link.textContent = 'Open original';

                details.append(link);

                card.append(details);
                cards.append(card);
            });

            updateCount();
        }

        function move(index, delta) {
            const next = index + delta;

            [data.images[index], data.images[next]] = [
                data.images[next], data.images[index]
            ];

            render();
        }

        function updateCount() {
            document.getElementById('count').textContent =
                `${data.images.filter(x => x.selected).length} selected`;
        }

        document.getElementById('export').addEventListener(
            'click', () => {
                const selected = data.images.filter(x => x.selected);

                if (!selected.length) {
                    alert('Select at least one image.');
                    return;
                }

                for (const img of selected) {
                    if (
                        !img.title.trim() ||
                        !img.description.trim()
                    ) {
                        alert(
                            `Fill title and description for: ${img.filename}`
                        );
                        return;
                    }
                }

                const result = {
                    quest_id: data.quest_id,
                    name: data.name,
                    images: selected.map(x => ({
                        title: x.title.trim(),
                        description: x.description.trim(),
                        url: x.url,
                        source: x.source,
                        ...(x.objective_id
                            ? {objective_id: x.objective_id}
                            : {})
                    }))
                };

                const blob = new Blob(
                    [JSON.stringify(result, null, 2)],
                    {type: 'application/json'}
                );

                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');

                a.href = url;
                a.download = `${data.quest_id}.review.json`;

                document.body.append(a);
                a.click();
                a.remove();

                setTimeout(
                    () => URL.revokeObjectURL(url), 1000
                );
            }
        );

        render();
    </script>
</body>
</html>
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(
        dest="action",
        required=True,
    )

    open_cmd = commands.add_parser(
        "open",
        help="Open visual review in your browser",
    )
    open_cmd.add_argument("quest_id")

    apply_cmd = commands.add_parser(
        "apply",
        help="Import an exported review JSON",
    )
    apply_cmd.add_argument("review_file", type=Path)
    apply_cmd.add_argument(
        "--replace",
        action="store_true",
        help="Edit an existing guide (with backup)",
    )

    args = parser.parse_args()

    if args.action == "open":
        build_review(args.quest_id)
    else:
        apply_review(args.review_file, args.replace)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Error: {exc}") from exc
