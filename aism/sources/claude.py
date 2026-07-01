from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from ..model import Session
from ..util import cache_dir


def claude_root() -> Path:
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env) if env else Path.home() / ".claude"


def _parse_ts(ts: str | None) -> datetime | None:
    if not isinstance(ts, str) or not ts:
        return None
    try:
        # timestamps are ISO-8601 with a trailing Z
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _stringify(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for blk in content:
            if isinstance(blk, dict):
                parts.append(blk.get("text") or blk.get("content") or "")
            else:
                parts.append(str(blk))
        return " ".join(p for p in parts if p)
    if content is None:
        return ""
    return json.dumps(content)[:2000]


def _first_user_text(message) -> str | None:
    """Real typed prompt text from a user event (skip tool_result payloads)."""
    if isinstance(message, str):
        return message or None
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content or None
    if isinstance(content, list):
        for blk in content:
            if isinstance(blk, dict) and blk.get("type") == "text" and blk.get("text"):
                return blk["text"]
    return None


def _extract_texts(message, include_tools: bool, include_reasoning: bool) -> Iterator[str]:
    if isinstance(message, str):
        if message:
            yield message
        return
    if not isinstance(message, dict):
        return
    content = message.get("content")
    if isinstance(content, str):
        if content:
            yield content
        return
    if not isinstance(content, list):
        return
    for blk in content:
        if not isinstance(blk, dict):
            continue
        btype = blk.get("type")
        if btype == "text" and blk.get("text"):
            yield blk["text"]
        elif btype == "thinking" and include_reasoning and blk.get("thinking"):
            yield blk["thinking"]
        elif btype == "tool_use" and include_tools:
            yield f"[tool_use {blk.get('name', '')}] {json.dumps(blk.get('input'))[:2000]}"
        elif btype == "tool_result" and include_tools:
            yield f"[tool_result] {_stringify(blk.get('content'))[:2000]}"


class ClaudeAdapter:
    """Reads Claude Code JSONL session logs under ~/.claude/projects/."""

    tool = "claude"

    def __init__(self, root: Path | None = None):
        base = root or claude_root()
        self.projects_dir = base / "projects"
        self._meta_cache_path = cache_dir() / "claude-meta.json"
        self._meta_cache: dict | None = None

    def available(self) -> bool:
        return self.projects_dir.is_dir()

    # -- metadata cache -------------------------------------------------
    def _cache(self) -> dict:
        if self._meta_cache is None:
            try:
                loaded = json.loads(self._meta_cache_path.read_text())
                self._meta_cache = loaded if isinstance(loaded, dict) else {}
            except Exception:
                self._meta_cache = {}
        return self._meta_cache

    def _save_cache(self) -> None:
        if self._meta_cache is not None:
            try:
                self._meta_cache_path.write_text(json.dumps(self._meta_cache))
            except OSError:
                pass

    def _session_files(self):
        for proj in sorted(self.projects_dir.iterdir()):
            if not proj.is_dir():
                continue
            yield from sorted(proj.glob("*.jsonl"))

    # -- listing --------------------------------------------------------
    def list_sessions(self) -> Iterator[Session]:
        if not self.available():
            return
        cache = self._cache()
        dirty = False
        seen: set[str] = set()
        for f in self._session_files():
            key = str(f)
            seen.add(key)
            try:
                st = f.stat()
            except OSError:
                continue
            fp = f"{int(st.st_mtime)}:{st.st_size}"
            entry = cache.get(key)
            if entry and entry.get("fp") == fp:
                yield Session.from_dict(entry["session"])
                continue
            s = self._parse_meta(f, st)
            if s is None:
                continue
            cache[key] = {"fp": fp, "session": s.to_dict()}
            dirty = True
            yield s
        for stale in [k for k in cache if k not in seen]:
            del cache[stale]
            dirty = True
        if dirty:
            self._save_cache()

    def _find_file(self, session_id: str) -> Path | None:
        if not self.available():
            return None
        matches = list(self.projects_dir.glob(f"*/{session_id}.jsonl"))
        return matches[0] if matches else None

    def get(self, session_id: str) -> Session | None:
        f = self._find_file(session_id)
        if not f:
            return None
        try:
            return self._parse_meta(f, f.stat())
        except OSError:
            return None

    def _parse_meta(self, f: Path, st) -> Session | None:
        cwd = branch = ai_title = first_user = model = None
        created = updated = None
        count = 0
        try:
            fh = f.open(encoding="utf-8", errors="replace")
        except OSError:
            return None
        with fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(e, dict):
                    continue
                if cwd is None and e.get("cwd"):
                    cwd = e["cwd"]
                if branch is None and e.get("gitBranch"):
                    branch = e["gitBranch"]
                ts = e.get("timestamp")
                if isinstance(ts, str):
                    if created is None:
                        created = ts
                    updated = ts
                etype = e.get("type")
                if etype == "ai-title":
                    ai_title = e.get("aiTitle") or ai_title
                elif etype == "user":
                    count += 1
                    if first_user is None:
                        first_user = _first_user_text(e.get("message"))
                elif etype == "assistant":
                    count += 1
                    m = e.get("message")
                    if isinstance(m, dict) and m.get("model"):
                        model = m["model"]
        mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
        title = ai_title or (first_user.strip()[:80] if first_user else "(no title)")
        return Session(
            tool="claude",
            id=f.stem,
            title=title,
            cwd=cwd or "",
            created=_parse_ts(created) or mtime,
            updated=_parse_ts(updated) or mtime,
            message_count=count,
            git_branch=branch,
            model=model,
            agent=None,
            parent_id=None,
            size_bytes=st.st_size,
            source_ref=str(f),
        )

    # -- content --------------------------------------------------------
    def iter_content(
        self,
        session_id: str,
        *,
        include_tools: bool = False,
        include_reasoning: bool = False,
    ) -> Iterator[tuple[str, str]]:
        f = self._find_file(session_id)
        if not f:
            return
        with f.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(e, dict) or e.get("type") not in ("user", "assistant"):
                    continue
                role = e["type"]
                for text in _extract_texts(e.get("message"), include_tools, include_reasoning):
                    yield (role, text)

    # -- resume ---------------------------------------------------------
    def resume_argv(self, session: Session, *, fork: bool = False) -> list[str]:
        # Claude has no fork flag; fork is a no-op here.
        return ["claude", "--resume", session.id]
