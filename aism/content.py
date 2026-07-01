"""Content extraction cache + full-text search over both tools.

Each session's searchable text is materialized to
``$XDG_CACHE_HOME/aism/content/<tool>/<id>.txt`` and re-extracted only when the
session is newer than its cache file. Search is ripgrep over that directory
(with a pure-Python fallback), so "find sessions that mention X" is one grep.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Iterable

from .model import Session
from .sources import get_adapter
from .sources.base import Adapter
from .util import cache_dir, which


def content_dir() -> Path:
    d = cache_dir() / "content"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path_for(tool: str, session_id: str) -> Path:
    d = content_dir() / tool
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{session_id}.txt"


def ensure_content(
    sessions: Iterable[Session], *, force: bool = False, progress: bool = False
) -> int:
    """Build/refresh the text cache for the given sessions. Returns count built."""
    adapters: dict[str, Adapter] = {}
    built = 0
    for s in sessions:
        p = _path_for(s.tool, s.id)
        if not force and p.exists() and p.stat().st_mtime >= s.updated.timestamp() - 1:
            continue
        adapter = adapters.get(s.tool)
        if adapter is None:
            adapter = get_adapter(s.tool)
            adapters[s.tool] = adapter
        lines = [f"{role}: {text}" for role, text in adapter.iter_content(s.id)]
        try:
            p.write_text("\n".join(lines), encoding="utf-8")
        except OSError:
            continue
        built += 1
        if progress and built % 25 == 0:
            print(f"\rindexing content… {built} sessions", end="", file=sys.stderr, flush=True)
    if progress and built:
        print(f"\rindexed {built} session(s){' ' * 20}", file=sys.stderr)
    return built


def search_ids(query: str, tool: str | None = None) -> set[tuple[str, str]] | None:
    """Return {(tool, id)} whose cached content matches ``query``.

    An empty query returns ``None`` meaning "no content filter — match all".
    """
    if not query:
        return None
    base = content_dir()
    roots = [base / tool] if tool else [base]
    roots = [r for r in roots if r.exists()]
    if not roots:
        return set()

    files: list[str] = []
    rg = which("rg")
    if rg:
        cmd = [rg, "-l", "-i", "--no-messages", "-e", query, *[str(r) for r in roots]]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            files = out.stdout.splitlines()
        except (OSError, subprocess.SubprocessError):
            files = []
    else:
        needle = query.lower()
        for r in roots:
            for f in r.rglob("*.txt"):
                try:
                    if needle in f.read_text(encoding="utf-8", errors="replace").lower():
                        files.append(str(f))
                except OSError:
                    pass

    hits: set[tuple[str, str]] = set()
    for fp in files:
        p = Path(fp)
        hits.add((p.parent.name, p.stem))
    return hits
