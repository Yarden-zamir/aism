from aism import content
from aism.sources.claude import ClaudeAdapter
from aism.sources.opencode import OpencodeAdapter


def test_ensure_and_search_across_tools(claude_root, opencode_db, monkeypatch):
    root, csid = claude_root
    db, osid = opencode_db
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(root))
    monkeypatch.setenv("OPENCODE_DB", str(db))

    sessions = list(ClaudeAdapter(root=root).list_sessions()) + list(
        OpencodeAdapter(db_path=db).list_sessions()
    )
    built = content.ensure_content(sessions, force=True)
    assert built == 2

    # empty query means "no filter"
    assert content.search_ids("") is None

    # term only in the claude session
    hits = content.search_ids("rate limiter")
    assert ("claude", csid) in hits
    assert ("opencode", osid) not in hits

    # term only in the opencode session
    hits = content.search_ids("race condition")
    assert ("opencode", osid) in hits
    assert ("claude", csid) not in hits

    # reasoning/tool content is not in the default index
    assert content.search_ids("secret reasoning") == set()
    assert content.search_ids("hidden") == set()


def test_search_is_incremental(claude_root):
    root, csid = claude_root
    sessions = list(ClaudeAdapter(root=root).list_sessions())
    assert content.ensure_content(sessions) == 1
    # unchanged session should not be re-extracted
    assert content.ensure_content(sessions) == 0
