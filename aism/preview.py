from __future__ import annotations

from .sources import get_adapter


class _Ansi:
    def __init__(self, enabled: bool):
        self.reset = "\x1b[0m" if enabled else ""
        self.bold = "\x1b[1m" if enabled else ""
        self.dim = "\x1b[2m" if enabled else ""
        self.cyan = "\x1b[36m" if enabled else ""
        self.green = "\x1b[32m" if enabled else ""
        self.yellow = "\x1b[33m" if enabled else ""
        self.invert = "\x1b[7m" if enabled else ""


def _highlight(text: str, query: str, c: _Ansi) -> str:
    """Literal, case-insensitive highlight of ``query`` occurrences."""
    if not query or not c.invert:
        return text
    low_text = text.lower()
    low_q = query.lower()
    out = []
    i = 0
    while True:
        j = low_text.find(low_q, i)
        if j < 0:
            out.append(text[i:])
            break
        out.append(text[i:j])
        out.append(c.invert + text[j : j + len(query)] + c.reset)
        i = j + len(query)
    return "".join(out)


def render(tool: str, session_id: str, *, query: str | None = None, color: bool = True) -> str:
    adapter = get_adapter(tool)
    c = _Ansi(color)
    out: list[str] = []

    s = adapter.get(session_id)
    if s is not None:
        out.append(f"{c.bold}{c.cyan}{s.title}{c.reset}")
        out.append(f"{c.dim}{tool} · {s.cwd or '(unknown cwd)'}{c.reset}")
        meta = []
        if s.model:
            meta.append(s.model)
        if s.agent:
            meta.append(f"agent={s.agent}")
        meta.append(f"{s.message_count} msgs")
        meta.append(s.updated.astimezone().strftime("%Y-%m-%d %H:%M"))
        out.append(f"{c.dim}{' · '.join(meta)}{c.reset}")
        if s.git_branch:
            out.append(f"{c.dim}branch: {s.git_branch}{c.reset}")
        out.append("")

    empty = True
    for role, text in adapter.iter_content(session_id):
        empty = False
        role_color = c.green if role == "user" else c.yellow
        out.append(f"{role_color}{c.bold}▎ {role}{c.reset}")
        body = text.strip()
        if query:
            body = _highlight(body, query, c)
        out.append(body)
        out.append("")
    if empty and s is None:
        out.append(f"{c.dim}(session not found){c.reset}")
    return "\n".join(out)
