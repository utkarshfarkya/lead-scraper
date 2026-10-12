from abc import ABC, abstractmethod
from collections.abc import Callable

from lead_scraper.models import Post

LocationFilter = Callable[[str], bool]


class Portal(ABC):
    """Base class every portal scraper implements.

    To add a portal: subclass this, set `name`, implement `search`,
    and decorate the class with `@register` (see `portals/__init__.py`).
    """

    name: str

    def __init__(self, location_filter: LocationFilter | None = None) -> None:
        # Only people whose location passes this are returned.
        self.location_filter = location_filter

    @abstractmethod
    def search(self, keywords: list[str], limit: int = 20) -> list[Post]:
        """Return up to `limit` posts matching the given keywords."""
