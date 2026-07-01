from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import content, fzf, preview
from .model import Session
from .sources import get_adapter, get_adapters
from .util import rel_time, shorten_home, which


# ---------------------------------------------------------------- loading ----
def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _match_path(cwd: str, pattern: str) -> bool:
    pattern = os.path.expanduser(pattern)
    return pattern in cwd or fnmatch.fnmatch(cwd, pattern) or fnmatch.fnmatch(cwd, f"*{pattern}*")


def _predicate(args):
    since = _parse_date(args.since) if getattr(args, "since", None) else None
    until = _parse_date(args.until) if getattr(args, "until", None) else None

    def keep(s: Session) -> bool:
        if getattr(args, "path", None) and not _match_path(s.cwd, args.path):
            return False
        if getattr(args, "branch", None) and (s.git_branch or "") != args.branch:
            return False
        if getattr(args, "agent", None) and (s.agent or "") != args.agent:
            return False
        if getattr(args, "model", None) and args.model.lower() not in (s.model or "").lower():
            return False
        if since and s.updated < since:
            return False
        if until and s.updated > until:
            return False
        return True

    return keep


def load_sessions(args) -> list[Session]:
    tool = getattr(args, "tool", None)
    sessions: list[Session] = []
    for adapter in get_adapters(tool):
        sessions.extend(adapter.list_sessions())
    keep = _predicate(args)
    sessions = [s for s in sessions if keep(s)]
    sessions.sort(key=lambda s: s.updated, reverse=True)

    grep = getattr(args, "grep", None)
    if grep:
        content.ensure_content(sessions)
        ids = content.search_ids(grep, tool)
        if ids is not None:
            sessions = [s for s in sessions if (s.tool, s.id) in ids]
    return sessions


# ------------------------------------------------------------- subcommands ----
def _human_line(s: Session) -> str:
    tail = f"{s.message_count}m" + (f" {s.model}" if s.model else "")
    return (
        f"{s.tool:<8} {rel_time(s.updated):>4}  "
        f"{shorten_home(s.cwd):<40}  {s.title}  ({tail})"
    )


def cmd_list(args) -> int:
    sessions = load_sessions(args)
    if args.json:
        json.dump([s.to_dict() for s in sessions], sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        for s in sessions:
            print(_human_line(s))
    return 0


def cmd_search(args) -> int:
    args.grep = args.query
    return cmd_list(args)


def cmd_preview(args) -> int:
    # tolerate empty/invalid selection (fzf runs preview with no row on an
    # empty list) instead of erroring into the preview pane
    try:
        out = preview.render(args.tool, args.id, query=args.query, color=args.color)
    except KeyError:
        out = ""
    sys.stdout.write(out + "\n")
    return 0


def _resume(session: Session, *, fork: bool, print_only: bool) -> int:
    adapter = get_adapter(session.tool)
    argv = adapter.resume_argv(session, fork=fork)
    if print_only:
        print(" ".join(shlex.quote(a) for a in argv))
        return 0
    if not which(argv[0]):
        print(f"{argv[0]} not found on PATH. Run manually:\n  {' '.join(argv)}", file=sys.stderr)
        return 127
    cwd = session.cwd
    if cwd and Path(cwd).is_dir():
        os.chdir(cwd)
    elif cwd:
        print(f"warning: cwd {cwd} no longer exists; resuming from $HOME", file=sys.stderr)
        os.chdir(Path.home())
    os.execvp(argv[0], argv)  # replaces this process


def cmd_resume(args) -> int:
    session = get_adapter(args.tool).get(args.id)
    if session is None:
        print(f"session not found: {args.tool}/{args.id}", file=sys.stderr)
        return 1
    return _resume(session, fork=args.fork, print_only=args.print)


def cmd_path(args) -> int:
    session = get_adapter(args.tool).get(args.id)
    if session is None:
        print(f"session not found: {args.tool}/{args.id}", file=sys.stderr)
        return 1
    print(session.source_ref)
    return 0


def cmd_reindex(args) -> int:
    sessions = load_sessions(args)
    built = content.ensure_content(sessions, force=True, progress=True)
    print(f"reindexed {built} session(s) into {content.content_dir()}")
    return 0


def cmd_doctor(args) -> int:
    print("tools:")
    for name in ("fzf", "rg", "bat", "claude", "opencode"):
        loc = which(name)
        print(f"  {'✓' if loc else '✗'} {name:<9} {loc or '(missing)'}")
    print("sources:")
    for adapter in (get_adapter("claude"), get_adapter("opencode")):
        if adapter.available():
            n = sum(1 for _ in adapter.list_sessions())
            print(f"  ✓ {adapter.tool:<9} {n} sessions")
        else:
            print(f"  ✗ {adapter.tool:<9} (not found)")
    print(f"cache: {content.content_dir().parent}")
    if not which("fzf"):
        print("\ninstall fzf for the interactive picker: brew install fzf", file=sys.stderr)
    return 0


def cmd_browse(args) -> int:
    sessions = load_sessions(args)
    if not sessions:
        print("no sessions found", file=sys.stderr)
        return 0
    content.ensure_content(sessions, progress=True)
    try:
        result = fzf.browse(sessions)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1
    if result is None:
        return 0
    action, line = result
    parts = line.split("\t", 2)
    if len(parts) < 2:
        return 0
    tool, sid = parts[0], parts[1]
    if action == "print":
        session = get_adapter(tool).get(sid)
        print(session.source_ref if session else f"{tool}/{sid}")
        return 0
    session = get_adapter(tool).get(sid)
    if session is None:
        print(f"session not found: {tool}/{sid}", file=sys.stderr)
        return 1
    return _resume(session, fork=getattr(args, "fork", False), print_only=False)


def cmd_view(args) -> int:
    """Internal: render fzf lines from sessions.json, honoring mode + sort state.

    Sessions mode returns everything (fzf does the fuzzy filtering itself).
    Content ("all") mode keeps a session if its message content matches
    (ripgrep) OR its name/path/model matches — so title/directory hits are
    never dropped just because the conversation body differs.
    """
    st = fzf.load_state()
    sessions = fzf.sort_sessions(fzf.load_sessions_data(), st["sort"])
    query = args.query or ""
    if st["mode"] == "content" and query:
        hits = content.search_ids(query)  # set (maybe empty); None only if empty query
        needle = query.lower()
        sessions = [
            s for s in sessions
            if (hits and (s.tool, s.id) in hits) or needle in fzf.searchable(s)
        ]
    out = "\n".join(fzf.format_line(s) for s in sessions)
    sys.stdout.write(out + ("\n" if out else ""))
    return 0


def cmd_state(args) -> int:
    if args.sort == "next":
        fzf.rotate_sort()
    elif args.sort:
        fzf.save_state(sort=args.sort)
    if args.mode:
        fzf.save_state(mode=args.mode)
    return 0


def cmd_prompt(args) -> int:
    sys.stdout.write(fzf.prompt_text())
    return 0


# --------------------------------------------------------------- argparse ----
def _add_filters(p: argparse.ArgumentParser) -> None:
    p.add_argument("--tool", choices=["claude", "opencode"], help="limit to one tool")
    p.add_argument("--path", help="filter by working directory (substring or glob)")
    p.add_argument("--branch", help="filter by git branch (claude only)")
    p.add_argument("--agent", help="filter by agent (opencode only)")
    p.add_argument("--model", help="filter by model substring")
    p.add_argument("--since", metavar="YYYY-MM-DD", help="updated on/after date")
    p.add_argument("--until", metavar="YYYY-MM-DD", help="updated on/before date")
    p.add_argument("--grep", help="only sessions whose content matches this regex")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aism", description="Browse, search, and resume Claude Code and opencode sessions."
    )
    _add_filters(parser)  # top-level filters apply to the default interactive picker
    parser.add_argument("--fork", action="store_true", help="fork on resume (opencode)")
    sub = parser.add_subparsers(dest="cmd")

    p_list = sub.add_parser("list", help="list sessions")
    _add_filters(p_list)
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_search = sub.add_parser("search", help="find sessions mentioning a query")
    _add_filters(p_search)
    p_search.add_argument("query")
    p_search.add_argument("--json", action="store_true")
    p_search.set_defaults(func=cmd_search)

    p_prev = sub.add_parser("preview", help="render a session transcript")
    p_prev.add_argument("tool")  # no choices: tolerate empty selection from fzf
    p_prev.add_argument("id", nargs="?", default="")
    p_prev.add_argument("--query", default=None)
    p_prev.add_argument("--color", action="store_true")
    p_prev.set_defaults(func=cmd_preview)

    p_res = sub.add_parser("resume", help="resume a session")
    p_res.add_argument("tool", choices=["claude", "opencode"])
    p_res.add_argument("id")
    p_res.add_argument("--fork", action="store_true")
    p_res.add_argument("--print", action="store_true", help="print the resume command only")
    p_res.set_defaults(func=cmd_resume)

    p_path = sub.add_parser("path", help="print a session's source path")
    p_path.add_argument("tool", choices=["claude", "opencode"])
    p_path.add_argument("id")
    p_path.set_defaults(func=cmd_path)

    p_reindex = sub.add_parser("reindex", help="rebuild the content search cache")
    _add_filters(p_reindex)
    p_reindex.set_defaults(func=cmd_reindex)

    sub.add_parser("doctor", help="check dependencies and sources").set_defaults(func=cmd_doctor)

    # internal subcommands used by fzf binds
    p_view = sub.add_parser("_view")
    p_view.add_argument("query", nargs="?", default="")
    p_view.set_defaults(func=cmd_view)

    p_state = sub.add_parser("_state")
    p_state.add_argument("--mode", choices=["sessions", "content"])
    p_state.add_argument("--sort", default=None)
    p_state.set_defaults(func=cmd_state)

    sub.add_parser("_prompt").set_defaults(func=cmd_prompt)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        return cmd_browse(args)
    return func(args)
