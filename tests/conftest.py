from __future__ import annotations

import json
import sqlite3

import pytest


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Keep every test's caches out of the real ~/.cache/aism."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))


@pytest.fixture
def claude_root(tmp_path):
    """A fake ~/.claude with one project holding one session."""
    proj = tmp_path / "claude" / "projects" / "-Users-me-Github-demo"
    proj.mkdir(parents=True)
    sid = "11111111-2222-3333-4444-555555555555"
    events = [
        {"type": "user", "cwd": "/Users/me/Github/demo", "gitBranch": "main",
         "timestamp": "2026-06-29T16:11:35.000Z", "sessionId": sid,
         "message": {"role": "user", "content": "please fix the rate limiter bug"}},
        {"type": "assistant", "cwd": "/Users/me/Github/demo",
         "timestamp": "2026-06-29T16:12:00.000Z", "sessionId": sid,
         "message": {"role": "assistant", "model": "claude-opus-4-8",
                     "content": [{"type": "thinking", "thinking": "secret reasoning"},
                                 {"type": "text", "text": "Fixed the rate limiter."}]}},
        {"type": "user", "cwd": "/Users/me/Github/demo",
         "timestamp": "2026-06-29T16:12:30.000Z", "sessionId": sid,
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "t1", "content": "TOOLNOISE"}]}},
        {"type": "ai-title", "aiTitle": "Fix the rate limiter", "sessionId": sid},
    ]
    (proj / f"{sid}.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return tmp_path / "claude", sid


@pytest.fixture
def opencode_db(tmp_path):
    """A minimal opencode.db with the columns the adapter reads."""
    db = tmp_path / "opencode.db"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE session (id TEXT PRIMARY KEY, project_id TEXT, parent_id TEXT,
            directory TEXT, title TEXT, agent TEXT, model TEXT,
            time_created INTEGER, time_updated INTEGER);
        CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER,
            time_updated INTEGER, data TEXT);
        CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT,
            time_created INTEGER, time_updated INTEGER, data TEXT);
        """
    )
    sid = "ses_demo0001"
    con.execute(
        "INSERT INTO session VALUES (?,?,?,?,?,?,?,?,?)",
        (sid, "proj", None, "/Users/me/Github/demo", "Investigate flaky test", "build",
         json.dumps({"id": "gpt-5.5", "providerID": "openai"}),
         1782755344793, 1782913223968),
    )
    con.execute("INSERT INTO message VALUES (?,?,?,?,?)",
                ("msg1", sid, 1, 1, json.dumps({"role": "user"})))
    con.execute("INSERT INTO message VALUES (?,?,?,?,?)",
                ("msg2", sid, 2, 2, json.dumps({"role": "assistant"})))
    con.execute("INSERT INTO part VALUES (?,?,?,?,?,?)",
                ("p1", "msg1", sid, 1, 1, json.dumps({"type": "text", "text": "why is the test flaky"})))
    con.execute("INSERT INTO part VALUES (?,?,?,?,?,?)",
                ("p2", "msg2", sid, 2, 2, json.dumps({"type": "reasoning", "text": "hidden"})))
    con.execute("INSERT INTO part VALUES (?,?,?,?,?,?)",
                ("p3", "msg2", sid, 3, 3, json.dumps({"type": "text", "text": "It was a race condition"})))
    con.commit()
    con.close()
    return db, sid
