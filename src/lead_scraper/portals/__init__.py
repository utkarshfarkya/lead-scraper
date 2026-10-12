from lead_scraper.portals.registry import available_portals, get_portal, register

# Import portal modules so their @register decorators run.
# Add new portals here.x
from lead_scraper.portals import linkedin

__all__ = ["available_portals", "get_portal", "register"]
