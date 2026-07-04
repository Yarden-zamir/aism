from datetime import datetime, timezone

from aism import fzf
from aism.model import Session


def _s(tool="claude", sid="a", title="t", cwd="/Users/me/x", updated=1, created=1, msgs=0):
    dt = lambda n: datetime.fromtimestamp(n, tz=timezone.utc)
    return Session(tool=tool, id=sid, title=title, cwd=cwd,
                   created=dt(created), updated=dt(updated), message_count=msgs)


def test_format_line_keeps_full_untruncated_path():
    # Regression: session search only works if the FULL path is in the visible
    # field (fzf matches the whole item even when the display is cut). A long
    # path must survive verbatim so `--with-nth 3..` can match it.
    long = "/Users/me/Github/data-app-design/qcdi-header-columns-first"
    line = fzf.format_line(_s(cwd=long, title="Header columns"))
    visible = line.split("\t", 2)[2]
    assert "qcdi-header-columns-first" in visible  # not truncated away
    assert line.split("\t")[0] == "claude"  # hidden tool field preserved


def test_format_line_has_three_fields():
    parts = fzf.format_line(_s()).split("\t")
    assert len(parts) == 3  # tool, id, visible


def test_searchable_covers_path_and_title():
    blob = fzf.searchable(_s(cwd="/Users/me/dotfiles", title="Docker cleanup"))
    assert "dotfiles" in blob and "docker cleanup" in blob


def test_sort_sessions_orders():
    a = _s(sid="a", updated=10, created=1, msgs=5, cwd="/z")
    b = _s(sid="b", updated=1, created=10, msgs=50, cwd="/a")
    assert [s.id for s in fzf.sort_sessions([b, a], "updated")] == ["a", "b"]
    assert [s.id for s in fzf.sort_sessions([a, b], "created")] == ["b", "a"]
    assert [s.id for s in fzf.sort_sessions([a, b], "messages")] == ["b", "a"]
    assert [s.id for s in fzf.sort_sessions([a, b], "path")] == ["b", "a"]  # /a before /z


def test_rotate_sort_cycles(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    fzf.save_state(mode="sessions", sort="updated")
    seen = [fzf.rotate_sort()["sort"] for _ in range(4)]
    assert seen == ["created", "messages", "path", "updated"]


def test_prompt_reflects_mode_and_sort(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    fzf.save_state(mode="content", sort="messages")
    assert fzf.prompt_text() == "search:all ↓msgs> "


def test_default_mode_is_search_all(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert fzf.load_state()["mode"] == "content"
    assert fzf.prompt_text() == "search:all ↓updated> "


def test_fzf_starts_in_search_all_mode():
    argv = fzf.build_argv()
    assert any("start:disable-search+transform-prompt" in arg for arg in argv)
    assert any("change:reload" in arg for arg in argv)
    assert any("ctrl-f:transform" in arg for arg in argv)
    assert not any("ctrl-s:" in arg for arg in argv)


def test_ctrl_f_toggles_search_modes(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    fzf.save_state(mode="content", sort="updated")

    action = fzf.toggle_search_action("rate limit")
    assert fzf.load_state()["mode"] == "sessions"
    assert "enable-search" in action
    assert "unbind(change)" in action
    assert "_view 'rate limit'" in action

    action = fzf.toggle_search_action("rate limit")
    assert fzf.load_state()["mode"] == "content"
    assert "disable-search" in action
    assert "rebind(change)" in action
