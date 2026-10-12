from dataclasses import dataclass, field


@dataclass
class Person:
    """Someone who wrote or interacted with a post."""

    name: str
    location: str = ""
    position: str = ""
    company: str = ""
    profile_url: str = ""


@dataclass
class Post:
    """A post found on a portal, normalized across portals."""

    portal: str
    url: str
    author: Person | None  # None when filtered out
    content: str = ""
    reactors: list[Person] = field(default_factory=list)
    commenters: list[Person] = field(default_factory=list)

    def people(self) -> list[Person]:
        author = [self.author] if self.author else []
        return [*author, *self.reactors, *self.commenters]
