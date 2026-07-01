from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from ..model import Session

_SESSION_COLS = """
    s.id, s.parent_id, s.directory, s.title, s.agent, s.model,
    s.time_created, s.time_updated,
    (SELECT count(*) FROM message m WHERE m.session_id = s.id) AS mcount
"""


def opencode_db() -> Path:
    env = os.environ.get("OPENCODE_DB")
    if env:
        return Path(env)
    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "opencode" / "opencode.db"


def _ms_to_dt(v) -> datetime:
    if not v:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    return datetime.fromtimestamp(v / 1000, tz=timezone.utc)


def _model_name(raw) -> str | None:
    if not raw:
        return None
    try:
        d = json.loads(raw)
        if isinstance(d, dict):
            return d.get("id") or d.get("modelID")
    except (json.JSONDecodeError, TypeError):
        pass
    return raw if isinstance(raw, str) else None


class OpencodeAdapter:
    """Reads opencode sessions from its SQLite database (read-only)."""

    tool = "opencode"

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or opencode_db()

    def available(self) -> bool:
        return self.db_path.is_file()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=3.0)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout = 3000")
        return con

    def _row_to_session(self, r: sqlite3.Row) -> Session:
        return Session(
            tool="opencode",
            id=r["id"],
            title=r["title"] or "(no title)",
            cwd=r["directory"] or "",
            created=_ms_to_dt(r["time_created"]),
            updated=_ms_to_dt(r["time_updated"]),
            message_count=r["mcount"] or 0,
            git_branch=None,
            model=_model_name(r["model"]),
            agent=r["agent"],
            parent_id=r["parent_id"],
            size_bytes=0,
            source_ref=str(self.db_path),
        )

    def list_sessions(self) -> Iterator[Session]:
        if not self.available():
            return
        con = self._connect()
        try:
            rows = con.execute(
                f"SELECT {_SESSION_COLS} FROM session s ORDER BY s.time_updated DESC"
            ).fetchall()
        finally:
            con.close()
        for r in rows:
            yield self._row_to_session(r)

    def get(self, session_id: str) -> Session | None:
        if not self.available():
            return None
        con = self._connect()
        try:
            r = con.execute(
                f"SELECT {_SESSION_COLS} FROM session s WHERE s.id = ?", [session_id]
            ).fetchone()
        finally:
            con.close()
        return self._row_to_session(r) if r else None

    def iter_content(
        self,
        session_id: str,
        *,
        include_tools: bool = False,
        include_reasoning: bool = False,
    ) -> Iterator[tuple[str, str]]:
        # Text parsing is done in Python (not json_extract) for portability
        # across sqlite builds without the json1 extension.
        if not self.available():
            return
        wanted = {"text"}
        if include_reasoning:
            wanted.add("reasoning")
        con = self._connect()
        try:
            rows = con.execute(
                """
                SELECT m.data AS mdata, p.data AS pdata
                FROM part p JOIN message m ON p.message_id = m.id
                WHERE p.session_id = ?
                ORDER BY p.time_created, p.id
                """,
                [session_id],
            ).fetchall()
        finally:
            con.close()
        for r in rows:
            try:
                part = json.loads(r["pdata"])
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(part, dict) or part.get("type") not in wanted:
                continue
            text = part.get("text")
            if not text:
                continue
            try:
                msg = json.loads(r["mdata"])
                role = msg.get("role", "?") if isinstance(msg, dict) else "?"
            except (json.JSONDecodeError, TypeError):
                role = "?"
            yield (role, text)

    def resume_argv(self, session: Session, *, fork: bool = False) -> list[str]:
        argv = ["opencode", session.cwd or str(Path.home()), "--session", session.id]
        if fork:
            argv.append("--fork")
        return argv
