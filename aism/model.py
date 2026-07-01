from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass
class Session:
    """A normalized session record shared by every source adapter."""

    tool: str  # "claude" | "opencode"
    id: str
    title: str
    cwd: str
    created: datetime
    updated: datetime
    message_count: int = 0
    git_branch: str | None = None
    model: str | None = None
    agent: str | None = None
    parent_id: str | None = None
    size_bytes: int = 0
    source_ref: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["created"] = self.created.isoformat()
        d["updated"] = self.updated.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Session":
        d = dict(d)
        d["created"] = datetime.fromisoformat(d["created"])
        d["updated"] = datetime.fromisoformat(d["updated"])
        return cls(**d)
