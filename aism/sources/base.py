from __future__ import annotations

from typing import Iterable, Iterator, Protocol

from ..model import Session


class Adapter(Protocol):
    """Contract every session source must implement.

    Adding a new AI tool means writing one class that satisfies this protocol
    and registering it in ``sources/__init__.py`` — nothing else changes.
    """

    tool: str

    def available(self) -> bool:
        """True if this source's store exists on disk."""
        ...

    def list_sessions(self) -> Iterable[Session]:
        """Yield metadata for every session (no message bodies)."""
        ...

    def get(self, session_id: str) -> Session | None:
        """Metadata for a single session, or None if not found."""
        ...

    def iter_content(
        self,
        session_id: str,
        *,
        include_tools: bool = False,
        include_reasoning: bool = False,
    ) -> Iterator[tuple[str, str]]:
        """Yield ``(role, text)`` in conversation order."""
        ...

    def resume_argv(self, session: Session, *, fork: bool = False) -> list[str]:
        """The argv that resumes this session in its native CLI."""
        ...
