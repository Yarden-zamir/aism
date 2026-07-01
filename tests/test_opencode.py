from aism.sources.opencode import OpencodeAdapter


def test_list_metadata(opencode_db):
    db, sid = opencode_db
    a = OpencodeAdapter(db_path=db)
    sessions = list(a.list_sessions())
    assert len(sessions) == 1
    s = sessions[0]
    assert s.tool == "opencode"
    assert s.id == sid
    assert s.title == "Investigate flaky test"
    assert s.cwd == "/Users/me/Github/demo"
    assert s.agent == "build"
    assert s.model == "gpt-5.5"  # parsed out of the JSON model column
    assert s.message_count == 2


def test_timestamps_are_utc(opencode_db):
    db, sid = opencode_db
    s = OpencodeAdapter(db_path=db).get(sid)
    assert s.created.year == 2026
    assert s.updated >= s.created


def test_content_text_only_by_default(opencode_db):
    db, sid = opencode_db
    a = OpencodeAdapter(db_path=db)
    content = list(a.iter_content(sid))
    assert content == [("user", "why is the test flaky"),
                       ("assistant", "It was a race condition")]


def test_content_includes_reasoning_when_asked(opencode_db):
    db, sid = opencode_db
    a = OpencodeAdapter(db_path=db)
    texts = [t for _, t in a.iter_content(sid, include_reasoning=True)]
    assert "hidden" in texts


def test_resume_argv(opencode_db):
    db, sid = opencode_db
    a = OpencodeAdapter(db_path=db)
    s = a.get(sid)
    assert a.resume_argv(s) == ["opencode", "/Users/me/Github/demo", "--session", sid]
    assert a.resume_argv(s, fork=True)[-1] == "--fork"
