from datetime import datetime
from pathlib import Path

import questionary

from lead_scraper.export import write_csv
from lead_scraper.geo import is_us_location
from lead_scraper.portals import available_portals, get_portal

OUTPUT_DIR = Path("output")


def prompt_keywords() -> list[str]:
    raw = questionary.text(
        "Enter keywords (comma-separated):",
        validate=lambda s: bool(s.strip()) or "Enter at least one keyword",
    ).ask()
    if raw is None:
        return []
    return [k.strip() for k in raw.split(",") if k.strip()]


def prompt_limit() -> int | None:
    raw = questionary.text(
        "How many posts to scrape?",
        default="10",
        validate=lambda s: s.strip().isdigit() and int(s) > 0 or "Enter a positive number",
    ).ask()
    return int(raw) if raw else None


def main() -> None:
    portal_name = questionary.select(
        "Select a portal to scrape:", choices=available_portals()
    ).ask()
    if portal_name is None:  # Ctrl+C
        return

    keywords = prompt_keywords()
    if not keywords:
        return

    limit = prompt_limit()
    if limit is None:
        return

    portal = get_portal(portal_name, location_filter=is_us_location)
    posts = portal.search(keywords, limit=limit)
    if not posts:
        print("No posts found.")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = OUTPUT_DIR / f"{portal_name.lower()}_{timestamp}.csv"
    rows = write_csv(posts, path)
    print(f"Saved {rows} people from {len(posts)} posts to {path}")
