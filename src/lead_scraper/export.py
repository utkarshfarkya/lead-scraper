import csv
from pathlib import Path

from lead_scraper.models import Post

CSV_FIELDS = ["post_url", "name", "position", "company", "profile_url"]


def write_csv(posts: list[Post], path: Path) -> int:
    """Write one row per person per post. Returns the number of rows."""
    rows = []
    for post in posts:
        seen: set[str] = set()
        for person in post.people():
            # Profiles with reaction and comment gets only one row
            key = person.profile_url or person.name
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "post_url": post.url,
                    "name": person.name,
                    "position": person.position,
                    "company": person.company,
                    "profile_url": person.profile_url,
                }
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)
