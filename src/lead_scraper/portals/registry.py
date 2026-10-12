from lead_scraper.portals.base import LocationFilter, Portal

_REGISTRY: dict[str, type[Portal]] = {}


def register(cls: type[Portal]) -> type[Portal]:
    _REGISTRY[cls.name] = cls
    return cls


def available_portals() -> list[str]:
    return list(_REGISTRY)


def get_portal(name: str, location_filter: LocationFilter | None = None) -> Portal:
    return _REGISTRY[name](location_filter=location_filter)
