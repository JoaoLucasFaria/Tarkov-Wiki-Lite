
"""Discover and preview quest images from the Tarkov wiki."""

import csv
import json
from html import escape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode, urlsplit
from urllib.request import Request, urlopen


ROOT_DIR = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT_DIR / "cache" / "guide_coverage.csv"

WIKI_DOMAIN = "escapefromtarkov.fandom.com"
API_URL = f"https://{WIKI_DOMAIN}/api.php"

QUEST_NAME = "A Big Loss"


def find_quest() -> dict:
    """Find the selected quest in the coverage report."""

    with REPORT_PATH.open(
        newline="",
        encoding="utf-8-sig",
    ) as file:
        for row in csv.DictReader(file):
            if row["name"] == QUEST_NAME:
                return row

    raise ValueError(f"Quest not found: {QUEST_NAME}")


def get_page_title(wiki_url: str) -> str:
    """Extract the MediaWiki page title from its URL."""

    parsed = urlsplit(wiki_url)

    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != WIKI_DOMAIN
        or not parsed.path.startswith("/wiki/")
    ):
        raise ValueError(f"Unsupported wiki URL: {wiki_url}")

    return unquote(parsed.path[6:]).replace("_", " ")


def wiki_request(params: dict) -> dict:
    """Make a read-only request to the wiki API."""

    request_url = API_URL + "?" + urlencode(params)

    request = Request(
        request_url,
        headers={
            "User-Agent": "TarkovWikiLite-GuideResearch/0.1",
            "Accept": "application/json",
        },
    )

    with urlopen(request, timeout=20) as response:
        data = json.load(response)

    if "error" in data:
        raise ValueError(str(data["error"]))

    return data


def fetch_images(page_title: str) -> list[str]:
    """Find all files referenced by a wiki page."""

    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "prop": "images",
        "titles": page_title,
        "imlimit": "max",
        "redirects": "1",
    }

    images = set()

    while True:
        data = wiki_request(params)

        for page in data.get("query", {}).get("pages", []):
            if "missing" in page:
                raise ValueError("Wiki page does not exist.")

            for image in page.get("images", []):
                title = image.get("title")

                if title:
                    images.add(title)

        continuation = data.get("continue")

        if not continuation:
            break

        params.update(continuation)

    return sorted(images)


def fetch_image_details(file_titles: list[str]) -> list[dict]:
    """Resolve file references to image URLs and thumbnails."""

    results = []

    for start in range(0, len(file_titles), 20):
        batch = file_titles[start:start + 20]

        params = {
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "prop": "imageinfo",
            "titles": "|".join(batch),
            "iiprop": "url|size|mime",
            "iiurlwidth": "420",
        }

        data = wiki_request(params)

        for page in data.get("query", {}).get("pages", []):
            info_list = page.get("imageinfo") or []

            if not info_list:
                continue

            info = info_list[0]

            if not info.get("url"):
                continue

            results.append({
                "title": page.get("title", ""),
                "url": info["url"],
                "thumbnail_url": info.get("thumburl", ""),
                "source": info.get("descriptionurl", ""),
                "width": info.get("width", 0),
                "height": info.get("height", 0),
                "size_bytes": info.get("size", 0),
                "mime": info.get("mime", ""),
                "review_status": "pending",
                "objective_id": None,
            })

    return sorted(results, key=lambda item: item["title"])


def save_preview(quest: dict, images: list[dict]) -> None:
    """Create a JSON candidate list and an HTML preview gallery."""

    output_dir = ROOT_DIR / "cache" / "guide_candidates"
    output_dir.mkdir(parents=True, exist_ok=True)

    quest_id = quest["quest_id"]

    json_path = output_dir / f"{quest_id}.json"
    html_path = output_dir / f"{quest_id}.html"

    candidate_data = {
        "quest_id": quest_id,
        "quest_name": quest["name"],
        "wiki_url": quest["wiki_link"],
        "images": images,
    }

    json_path.write_text(
        json.dumps(candidate_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    cards = []

    for index, item in enumerate(images, start=1):
        title = escape(item["title"])
        original_url = escape(item["url"], quote=True)
        thumbnail_url = escape(
            item["thumbnail_url"], quote=True
        )
        source_url = escape(
            item["source"] or quest["wiki_link"],
            quote=True,
        )

        if thumbnail_url:
            preview = (
                f'<img src="{thumbnail_url}" '
                f'alt="{title}" loading="lazy">'
            )
        else:
            preview = "<p>Thumbnail unavailable.</p>"

        cards.append(f"""
        <article>
            <div class="preview">
                {preview}
            </div>

            <div class="content">
                <h2>{index}. {title}</h2>

                <p>
                    Dimensions:
                    {item["width"]} × {item["height"]}
                </p>

                <a href="{original_url}" target="_blank">
                    Open original
                </a>

                <a href="{source_url}" target="_blank">
                    Wiki file page
                </a>
            </div>
        </article>
        """)

    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <title>Tarkov Wiki Lite - Image Review</title>

        <style>
            body {
                font-family: Arial, sans-serif;
                background: #171a1d;
                color: #eeeeee;
                margin: 30px;
            }

            .grid {
                display: grid;
                grid-template-columns:
                    repeat(auto-fit, minmax(290px, 1fr));
                gap: 18px;
            }

            article {
                background: #252a2f;
                border: 1px solid #444;
                border-radius: 10px;
                overflow: hidden;
            }

            .preview {
                height: 270px;
                display: flex;
                align-items: center;
                justify-content: center;
                background: #111;
            }

            .preview img {
                max-width: 100%;
                max-height: 100%;
                object-fit: contain;
            }

            .content {
                padding: 15px;
            }

            h2 {
                font-size: 16px;
                overflow-wrap: anywhere;
            }

            p {
                color: #aaaaaa;
            }

            a {
                color: #a9cfa4;
                display: inline-block;
                margin-right: 14px;
            }
        </style>
    </head>
    <body>
    """

    html_content += (
        "<h1>Tarkov Wiki Lite - Image Candidates</h1>"
        f"<h2>{escape(quest['name'])}</h2>"
        f"<p>{len(images)} candidates - not yet approved.</p>"
        '<div class="grid">'
        + "\n".join(cards)
        + "</div></body></html>"
    )

    html_path.write_text(
        html_content,
        encoding="utf-8",
    )

    print(f"Candidate JSON: {json_path}")
    print(f"Preview gallery: {html_path}")


def main() -> None:
    """Discover and preview images for one quest."""

    quest = find_quest()
    title = get_page_title(quest["wiki_link"])

    print(f"Quest: {quest['name']}")
    print(f"Quest ID: {quest['quest_id']}")
    print(f"Wiki page: {quest['wiki_link']}")

    try:
        file_titles = fetch_images(title)

        print(f"\nFiles discovered: {len(file_titles)}")

        images = fetch_image_details(file_titles)

        print(f"Images resolved: {len(images)}")

        save_preview(quest, images)

    except (HTTPError, URLError, ValueError, OSError) as error:
        print(f"Wiki lookup failed: {error}")


if __name__ == "__main__":
    main()
