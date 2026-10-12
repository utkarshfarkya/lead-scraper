# lead-scraper

Interactive CLI: pick a portal, enter keywords, get matching posts.

```sh
uv sync
uv run lead-scraper
```

LinkedIn opens your installed Google Chrome (required). Log in the first time; the session is
saved in `~/.lead-scraper/linkedin-profile` for later runs.

## Adding a new portal

1. Create `src/lead_scraper/portals/<portal>.py`:

   ```python
   from lead_scraper.models import Post
   from lead_scraper.portals.base import Portal
   from lead_scraper.portals.registry import register

   @register
   class RedditPortal(Portal):
       name = "Reddit"

       def search(self, keywords: list[str], limit: int = 20) -> list[Post]:
           ...
   ```

2. Import it in `src/lead_scraper/portals/__init__.py`.

It then shows up in the portal menu automatically.
