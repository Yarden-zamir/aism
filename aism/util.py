from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME")
    d = (Path(base) if base else Path.home() / ".cache") / "aism"
    d.mkdir(parents=True, exist_ok=True)
    return d


def which(name: str) -> str | None:
    return shutil.which(name)


def shorten_home(p: str) -> str:
    if not p:
        return ""
    home = str(Path.home())
    if p == home:
        return "~"
    if p.startswith(home + "/"):
        return "~" + p[len(home):]
    return p


def truncate(s: str, width: int) -> str:
    if len(s) <= width:
        return s
    if width <= 1:
        return s[:width]
    return s[: width - 1] + "…"


def to_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def rel_time(dt: datetime, *, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    seconds = max(0.0, (to_utc(now) - to_utc(dt)).total_seconds())
    minutes = seconds / 60
    if seconds < 60:
        return "now"
    if minutes < 60:
        return f"{int(minutes)}m"
    hours = minutes / 60
    if hours < 24:
        return f"{int(hours)}h"
    days = hours / 24
    if days < 7:
        return f"{int(days)}d"
    if days < 30:
        return f"{int(days / 7)}w"
    if days < 365:
        return f"{int(days / 30)}mo"
    return f"{int(days / 365)}y"
