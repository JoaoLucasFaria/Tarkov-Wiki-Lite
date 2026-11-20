"""Curated visual guides for Tarkov quests."""

WIKI_SOURCE = (
    "https://escapefromtarkov.fandom.com/"
    "wiki/Delivery_From_the_Past"
)

GUIDES = {
    "59674eb386f774539f14813a": [
        {
            "title": "Customs - Warehouse location",
            "description": (
                "Find the red warehouse containing "
                "Tarcone Director's office."
            ),
            "url": (
                "https://static.wikia.nocookie.net/"
                "escapefromtarkov_gamepedia/images/4/4a/"
                "Delivery_from_the_past_Customs.png/revision/latest"
            ),
            "source": WIKI_SOURCE,
        },
        {
            "title": "Customs - Secure Folder 0022",
            "description": (
                "Inside the office, look underneath the desk, "
                "on top of the drawers."
            ),
            "url": (
                "https://static.wikia.nocookie.net/"
                "escapefromtarkov_gamepedia/images/e/e2/"
                "Docs_0022-Delivery_From_the_Past.png/revision/latest"
            ),
            "source": WIKI_SOURCE,
        },
        {
            "title": "Factory - Drop-off map",
            "description": (
                "Find the break room on the second floor "
                "near Gate 3."
            ),
            "url": (
                "https://static.wikia.nocookie.net/"
                "escapefromtarkov_gamepedia/images/c/cf/"
                "Delivery_from_the_past_Factory.png/revision/latest"
            ),
            "source": WIKI_SOURCE,
        },
        {
            "title": "Factory - Stash location",
            "description": (
                "Place the documents inside the sheet-metal "
                "break room near Gate 3."
            ),
            "url": (
                "https://static.wikia.nocookie.net/"
                "escapefromtarkov_gamepedia/images/5/5c/"
                "Delivery_from_the_past_dropoff.png/revision/latest"
            ),
            "source": WIKI_SOURCE,
        },
    ],
}


def get_quest_guide(task: dict) -> list[dict]:
    """Return available curated images for a quest."""
    quest_id = str(task.get("id") or "")
    return GUIDES.get(quest_id, [])
