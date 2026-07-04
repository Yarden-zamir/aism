"""fzf orchestration: one window, live search, sort toggle, resume on enter.

Lines fed to fzf are ``tool\\tid\\t<visible>``. Fields 1-2 are hidden
(``--with-nth 3..``); field 3 is shown *and* searched. In fzf 0.73 ``--nth``
selects *within* the ``--with-nth`` view, so there is no way to search a field
you don't display — instead the full (untruncated) path + title live in the
visible field and fzf matches the whole item even when the display is cut at the
screen edge. Reloads/sorting are driven by the structured ``sessions.json`` via
the ``_view`` subcommand so we can re-sort without re-parsing the sources.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

from .model import Session
from .util import cache_dir, rel_time, shorten_home, truncate, which

DIM = "\x1b[2m"
RESET = "\x1b[0m"

# sort cycle for the ctrl-t toggle
SORTS = ["updated", "created", "messages", "path"]
SORT_LABEL = {"updated": "↓updated", "created": "↓created",
              "messages": "↓msgs", "path": "↑path"}

HEADER = "↵ resume · ^f search mode · ^t sort · ^o path · ^y copy · ⇧↑↓ scroll"
DEFAULT_MODE = "content"
MODE_LABEL = {"content": "search:all", "sessions": "sessions"}


def sessions_file() -> Path:
    return cache_dir() / "sessions.json"


def state_file() -> Path:
    return cache_dir() / "state.json"


# ---------------------------------------------------------------- format ----
def _clean(s: str) -> str:
    return s.replace("\t", " ").replace("\n", " ").strip()


def format_line(s: Session) -> str:
    glyph = "◆" if s.tool == "claude" else "◇"
    when = rel_time(s.updated)
    cwd = shorten_home(s.cwd)
    cwd_disp = cwd if len(cwd) >= 30 else f"{cwd:<30}"  # pad short paths, never truncate
    title = truncate(_clean(s.title), 120)
    tail = f"{s.message_count}m" + (f" {s.model}" if s.model else "")
    visible = f"{glyph} {when:>4}  {cwd_disp}  {title}  {DIM}{tail}{RESET}"
    return f"{s.tool}\t{s.id}\t{visible}"


def searchable(s: Session) -> str:
    """Lowercased blob used for name/path matching in content ("all") mode."""
    return f"{s.cwd} {shorten_home(s.cwd)} {s.title} {s.model or ''}".lower()


# ------------------------------------------------------------- state/data ----
def load_state() -> dict:
    try:
        st = json.loads(state_file().read_text())
    except Exception:
        st = {}
    return {"mode": st.get("mode", DEFAULT_MODE), "sort": st.get("sort", "updated")}


def save_state(*, mode: str | None = None, sort: str | None = None) -> dict:
    st = load_state()
    if mode:
        st["mode"] = mode
    if sort:
        st["sort"] = sort
    state_file().write_text(json.dumps(st))
    return st


def rotate_sort() -> dict:
    st = load_state()
    i = SORTS.index(st["sort"]) if st["sort"] in SORTS else 0
    return save_state(sort=SORTS[(i + 1) % len(SORTS)])


def prompt_text() -> str:
    st = load_state()
    mode = MODE_LABEL.get(st["mode"], st["mode"])
    return f"{mode} {SORT_LABEL.get(st['sort'], st['sort'])}> "


def toggle_search_action(query: str) -> str:
    st = load_state()
    c = _self_cmd()
    view = f"{c} _view {shlex.quote(query)}" if query else f"{c} _view"
    prompt = f"transform-prompt({c} _prompt)"
    if st["mode"] == "content":
        save_state(mode="sessions")
        return f"enable-search+unbind(change)+reload({view})+{prompt}"
    save_state(mode="content")
    return f"disable-search+rebind(change)+reload({view})+{prompt}"


def sort_sessions(sessions: list[Session], sort: str) -> list[Session]:
    if sort == "created":
        return sorted(sessions, key=lambda s: s.created, reverse=True)
    if sort == "messages":
        return sorted(sessions, key=lambda s: s.message_count, reverse=True)
    if sort == "path":
        return sorted(sessions, key=lambda s: (s.cwd.lower(), s.updated))
    return sorted(sessions, key=lambda s: s.updated, reverse=True)


def load_sessions_data() -> list[Session]:
    try:
        data = json.loads(sessions_file().read_text())
    except Exception:
        return []
    return [Session.from_dict(d) for d in data]


def write_data(sessions: list[Session]) -> None:
    sessions_file().write_text(json.dumps([s.to_dict() for s in sessions]))
    save_state(mode=DEFAULT_MODE, sort="updated")  # predictable recency-first default


# ------------------------------------------------------------------ fzf ----
def _self_cmd() -> str:
    return f"{shlex.quote(sys.executable)} -m aism"


def build_argv() -> list[str]:
    c = _self_cmd()
    view = f"{c} _view {{q}}"
    prompt = f"transform-prompt({c} _prompt)"
    return [
        "fzf",
        "--ansi",
        "--delimiter", "\t",
        "--with-nth", "3..",          # show + search field 3 (full path/title)
        "--layout", "reverse",
        "--info", "inline",
        "--header", HEADER,
        "--preview", f"{c} preview {{1}} {{2}} --query {{q}} --color",
        "--preview-window", "right,33%,wrap",
        "--bind", f"change:reload({view})",
        "--bind", f"start:disable-search+{prompt}",
        "--bind", f"ctrl-f:transform({c} _toggle_search {{q}})",
        "--bind", f"ctrl-t:execute-silent({c} _state --sort next)+reload({view})+{prompt}",
        "--bind", "ctrl-y:execute-silent(printf %s {2} | pbcopy)",
        "--bind", "shift-up:preview-up",
        "--bind", "shift-down:preview-down",
        "--bind", "alt-up:preview-page-up",
        "--bind", "alt-down:preview-page-down",
        "--expect", "ctrl-o",
    ]


def browse(sessions: list[Session]) -> tuple[str, str] | None:
    """Launch the picker. Returns ("resume"|"print", line) or None if cancelled."""
    if not which("fzf"):
        raise RuntimeError("fzf not found on PATH — install fzf to use the picker")
    write_data(sessions)
    initial = "\n".join(format_line(s) for s in sort_sessions(sessions, load_state()["sort"]))
    proc = subprocess.run(build_argv(), input=initial, capture_output=True, text=True)
    if proc.returncode not in (0,):  # 130 = cancelled
        return None
    out = proc.stdout.split("\n")
    key = out[0] if out else ""
    selection = next((ln for ln in out[1:] if ln.strip()), "")
    if not selection:
        return None
    return ("print" if key == "ctrl-o" else "resume", selection)
