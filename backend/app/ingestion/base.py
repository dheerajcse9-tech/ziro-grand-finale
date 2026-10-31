from dataclasses import dataclass
from typing import Protocol


class IngestError(RuntimeError):
    """Raised with a user-presentable message when a source cannot be processed."""


@dataclass
class Segment:
    text: str
    page: int | None = None
    start: float | None = None
    end: float | None = None
    heading: str | None = None


class Connector(Protocol):
    """A knowledge connector turns a resource into positioned text segments (page or time span)."""
    def extract(self, resource: dict) -> list[Segment]: ...
