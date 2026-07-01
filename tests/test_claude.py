from aism.sources.claude import ClaudeAdapter


def test_list_metadata(claude_root):
    root, sid = claude_root
    a = ClaudeAdapter(root=root)
    sessions = list(a.list_sessions())
    assert len(sessions) == 1
    s = sessions[0]
    assert s.tool == "claude"
    assert s.id == sid
    assert s.title == "Fix the rate limiter"  # from ai-title, not first prompt
    assert s.cwd == "/Users/me/Github/demo"
    assert s.git_branch == "main"
    assert s.model == "claude-opus-4-8"
    assert s.message_count == 3  # 2 user + 1 assistant


def test_metadata_cache_roundtrip(claude_root):
    root, sid = claude_root
    a = ClaudeAdapter(root=root)
    first = list(a.list_sessions())[0]
    # second run should hit the cache and produce an equal record
    again = list(ClaudeAdapter(root=root).list_sessions())[0]
    assert again.to_dict() == first.to_dict()


def test_content_excludes_tool_and_reasoning_by_default(claude_root):
    root, sid = claude_root
    a = ClaudeAdapter(root=root)
    content = list(a.iter_content(sid))
    texts = [t for _, t in content]
    assert "please fix the rate limiter bug" in texts
    assert "Fixed the rate limiter." in texts
    assert "secret reasoning" not in texts  # thinking excluded
    assert "TOOLNOISE" not in " ".join(texts)  # tool_result excluded


def test_content_includes_reasoning_when_asked(claude_root):
    root, sid = claude_root
    a = ClaudeAdapter(root=root)
    texts = [t for _, t in a.iter_content(sid, include_reasoning=True)]
    assert "secret reasoning" in texts


def test_resume_argv(claude_root):
    root, sid = claude_root
    a = ClaudeAdapter(root=root)
    s = a.get(sid)
    assert a.resume_argv(s) == ["claude", "--resume", sid]
