# AI Session Manager — Specification

Status: **implemented (v0.1.0)** — see §14 for the built layout and what differs
from the original design.
Owner: Yarden-zamir

Quick start:

```
uv run aism            # interactive picker (fzf)
uv run aism search X   # sessions mentioning X (both tools)
uv run aism list --path ~/Github/foo --tool claude
uv run aism doctor     # check deps + source availability
```

## 1. Purpose

A fast terminal tool to **browse, search, and resume** every local
[Claude Code](https://docs.claude.com/en/docs/claude-code) and
[opencode](https://opencode.ai) session from one `fzf` interface.

Primary questions it must answer instantly:

- "Find the session where **X** was mentioned." (full-text over message content)
- "Show sessions under **this path / repo**." (filter by working directory)
- "Which session did I do **Y** in, and resume it." (browse → resume)

Non-goals (v1): editing/merging sessions, syncing to the cloud, analytics
dashboards, exporting. See §11.

## 2. Data sources (ground truth)

Both layouts were verified directly on disk, not just from docs. Source of
truth for parsing is always the **content of the files/rows**, never a decoded
directory name (the encoding is lossy — see §2.1).

### 2.1 Claude Code

- **Location:** `~/.claude/projects/<encoded-cwd>/<session-uuid>.jsonl`
  - One `.jsonl` file per session; filename stem is the session UUID.
  - `<encoded-cwd>` replaces every `/` in the absolute cwd with `-`
    (e.g. `/Users/you/Github/project` → `-Users-you-Github-project`).
  - 🔴 **Lossy:** original dir names containing `-` are indistinguishable from
    path separators. **Never reverse-decode the folder name.** Read the real
    `cwd` field from inside the JSONL instead.
  - Config root honors `$CLAUDE_CONFIG_DIR` (defaults to `~/.claude`).
- **Format:** newline-delimited JSON. One event object per line. Observed
  `type` values: `user`, `assistant`, `system`, `summary`, `attachment`,
  `file-history-snapshot`, `ai-title`, `last-prompt`, `mode`,
  `permission-mode`, `queue-operation`.
- **Fields present on `user`/`assistant` events:** `type`, `sessionId`, `uuid`,
  `parentUuid`, `cwd`, `gitBranch`, `timestamp` (ISO-8601 UTC), and `message`
  (either a string, or Anthropic-style `content` array of
  `{type: text|tool_use|tool_result, ...}` blocks).
- **Title:** the `ai-title` event (when present) carries a generated title in
  its **`aiTitle`** field; otherwise fall back to the first `user` **string**
  content (skipping `tool_result` user events), truncated.
- **Model:** read from `assistant.message.model` (e.g. `claude-opus-4-8`).
- **Session identity:** `sessionId` field (equals the filename stem).
- Sibling files under `~/.claude/` (`history.jsonl`, `file-history/`,
  `shell-snapshots/`, etc.) are **not** sessions and must be ignored.

### 2.2 opencode

- **Storage engine:** SQLite at `~/.local/share/opencode/opencode.db`
  (WAL mode). Overridable via `$OPENCODE_DB`. The `$XDG_DATA_HOME` base is
  honored for the default path.
- 🔴 The legacy file tree `~/.local/share/opencode/storage/{session,message,part}/…`
  is **pre-migration and stale** (verified: last write ≈ Feb 2026 vs live DB
  through Jul 2026; 89 stale session files vs 349 rows). v1 reads **only the
  DB**. Reading the file tree is an explicit non-goal unless a DB is absent.
- **Schema (relevant columns), hierarchy `project → session → message → part`:**
  - `project(id, worktree, vcs, name, time_created, time_updated, …)`
  - `session(id, project_id, parent_id, slug, directory, title, version,
    time_created, time_updated, time_archived, path, agent, model, cost,
    tokens_input, tokens_output, tokens_reasoning, tokens_cache_read,
    tokens_cache_write, metadata)`
  - `message(id, session_id, time_created, time_updated, data)` — `data` is a
    JSON blob: `{role, time, modelID, providerID, mode, agent,
    path:{cwd,root}, cost, tokens, finish}`.
  - `part(id, message_id, session_id, time_created, time_updated, data)` —
    `data` JSON with `type` ∈ `{text, reasoning, tool, patch, step-start,
    step-finish, file, compaction}`. **`text` parts hold user prompts and
    assistant replies** (the searchable content); `reasoning` is model
    thinking; `tool`/`patch` are structured tool activity.
- **Working directory:** `session.directory` (and `message.data.path.cwd`).
- **Title:** `session.title` (already human-readable).
- **Sub-sessions:** `session.parent_id` is set for agent/child sessions
  (39/349 observed). v1 shows them but tags them as children (§6).
- **Concurrency:** open the DB **read-only** with a busy timeout; never write.
  WAL means live opencode processes may be writing concurrently — reads are safe.

## 3. Unified model

Every source is normalized by an adapter into one `Session` record:

```
Session:
  tool:        "claude" | "opencode"
  id:          str                     # native session id
  title:       str                     # ai title | session.title | first prompt
  cwd:         str                     # absolute working directory
  git_branch:  str | None
  created:     datetime (UTC)
  updated:     datetime (UTC)
  message_count: int
  model:       str | None              # last/most-common model
  agent:       str | None              # opencode agent; claude → None
  parent_id:   str | None              # sub-session linkage
  size_bytes:  int                     # jsonl size or Σ part lengths (approx)
  source_ref:  str                     # jsonl path | db path
  resume_cmd:  list[str]               # argv to resume (see §7)
```

Content (for search/preview) is streamed lazily per session, not held in the
list model.

## 4. Architecture

Language: **Python ≥3.11, run via `uv`** (per project tooling). Standard
library only for core (`sqlite3`, `json`, `subprocess`, `pathlib`,
`argparse`) — **no third-party deps** for parsing. External runtime tools:
`fzf` (required), `rg`/ripgrep (required for fast content search), optional
`bat` for prettier preview.

As-built layout (a few modules were merged for simplicity — see §14):

```
aism/
  __init__.py
  __main__.py       # enables `python -m aism`
  cli.py            # argparse entrypoint, session loading + filters, all commands
  model.py          # Session dataclass (to_dict/from_dict)
  util.py           # cache dir, home-shortening, relative time, which()
  content.py        # text-cache extraction + ripgrep search (index + search merged)
  preview.py        # `aism preview <tool> <id>` — renders a transcript
  fzf.py            # fzf argv/keybindings, line formatting, browse()
  sources/
    __init__.py     # adapter registry: all_adapters/get_adapters/get_adapter
    base.py         # Adapter protocol
    claude.py       # JSONL adapter (+ per-file metadata cache)
    opencode.py     # SQLite adapter (read-only)
tests/
  conftest.py       # builds a fake ~/.claude and a fixture opencode.db
  test_claude.py test_opencode.py test_content.py
pyproject.toml      # console_script: aism = aism.cli:main
README.md  SPEC.md
```

Adapter protocol (`sources/base.py`):

```
class Adapter(Protocol):
    tool: str
    def available(self) -> bool: ...             # source root/db exists
    def list_sessions(self) -> Iterable[Session]: ...
    def iter_content(self, id: str) -> Iterable[ContentLine]: ...  # role, text
    def resume_argv(self, s: Session) -> list[str]: ...
```

Adding a third tool = one new adapter file; nothing else changes.

## 5. Search & indexing

Two-layer approach; both live in a cache dir (`$XDG_CACHE_HOME/aism/`, default
`~/.cache/aism/`).

1. **Session list** — cheap. Built on every run by scanning JSONL headers and
   one DB query. Fast enough to skip caching at current scale (hundreds of
   sessions); a mtime-keyed JSON cache is added only if startup exceeds ~150 ms.

2. **Content search** — the "where was X mentioned" case. Approach:
   - Materialize each session's searchable text (concatenated `text`-type
     content, role-prefixed) into a per-session file:
     `~/.cache/aism/content/<tool>/<id>.txt`, keyed by session `updated` mtime
     so only changed/new sessions are re-extracted (incremental).
   - Live search = `rg` across that cache dir; each hit maps a file back to a
     `Session`. This powers fzf's live reload (§6) with sub-second latency over
     the whole corpus.
   - 🟠 Simpler alternative considered: SQLite FTS5 index. Rejected for v1 —
     ripgrep-over-text-cache is simpler, needs no schema migration, and gives
     free regex/word-boundary search. Revisit if corpus grows to 10k+ sessions.

Content extraction rules (v1 index = **text parts only**):
- Claude: for each `user`/`assistant` line, pull text from `message` (string)
  or from `content[].text` where `type == "text"`. `thinking` (reasoning),
  `tool_use`, and `tool_result` blocks are **excluded** from the search index.
- opencode: read `part.data` where `type == "text"`, joined to `message.role`.
  JSON is parsed in Python (not `json_extract`) so it works on sqlite builds
  without the json1 extension. `reasoning`/`tool`/`patch` parts are excluded.
- The adapters *can* emit reasoning/tool text (`include_reasoning`/
  `include_tools` kwargs, used by preview), but v1 does **not** wire CLI flags
  to fold them into the search index — keeping the index to visible
  conversation text. Revisit if "search my tool output" is wanted.

## 6. Interactive UI (fzf)

`aism` with no subcommand launches the browser. Design chosen: **live
full-text in one fzf window** (per decision).

- **List line (tab-separated):** `tool \t id \t visible`. `tool`/`id` are hidden
  ({1}/{2} in binds); `visible` is the shown, aligned
  `◆tool  updated(rel)  cwd(~/…)  title  ·msgs ·model`.
- 🔴 **fzf `--nth` gotcha (0.73):** `--nth` selects fields *within* the
  `--with-nth` view, so you **cannot** search a field you don't display. The
  visible field therefore carries the **full, untruncated** cwd + title (fzf
  matches the whole item even when the display is cut at the screen edge), and
  we use `--with-nth 3..` with **no `--nth`**. This is why session search works.
- **Default mode = session list**, fzf fuzzy-matching over the visible line
  (full path + title + model).
- **Content/"search all" mode (`ctrl-f`)** matches a session if its message
  content matches (ripgrep) **OR** its name/path/model matches — so title and
  directory hits are never dropped just because the body differs. Filtering is
  done by the `_view` subcommand (fzf's own search is disabled in this mode).
- **Sort toggle (`ctrl-t`)** cycles `updated → created → messages → path`,
  reflected live in the prompt (via `transform-prompt`). Sort + mode live in
  `~/.cache/aism/state.json`; the picker renders from a structured
  `~/.cache/aism/sessions.json` through `_view`, so re-sorting never re-reads
  the sources.
- **Preview pane width: 33%** (`--preview-window right,33%,wrap`).
- **`ctrl-f` / `ctrl-s` toggle Content vs Sessions mode.** The `change` event
  is bound to `reload(aism _view {q})` but **unbound at start**, so Sessions
  mode is plain fzf fuzzy filtering over the visible line. `ctrl-f` does
  `disable-search + _state --mode content + rebind(change) + reload(_view {q})`
  so typing filters via `_view` (ripgrep + name/path); `ctrl-s` does
  `enable-search + _state --mode sessions + unbind(change) + reload(_view {q})`
  to return to fuzzy. `_view` reads `sessions.json` (fast) each reload.
- **Preview pane:** `aism preview {tool} {id} --query {q}` renders the
  transcript (metadata header + role-labeled turns; in content mode it
  highlights the query with inverse video). Plain ANSI in v1; `bat` is M5.
- **Filters (also available as flags, applied before fzf):**
  `--path <glob/substr>`, `--tool claude|opencode`, `--since <date>`,
  `--until <date>`, `--branch <name>`, `--agent <name>`, `--model <substr>`,
  `--grep <regex>` (non-interactive content filter).
- **Keybindings** (compact header: `↵ resume · ^f all · ^s sessions · ^t sort ·
  ^o path · ^y copy · ⇧↑↓ scroll`):
  - `enter` → **resume** the selected session (§7) — the primary action.
  - `ctrl-f` → "search all" mode (name + path + content); `ctrl-s` → sessions.
  - `ctrl-t` → cycle sort order (updated/created/messages/path).
  - `ctrl-o` → print session path to stdout and exit (scripting).
  - `ctrl-y` → copy session id to clipboard (`pbcopy`).
  - `shift-↑/↓` scroll, `alt-↑/↓` page the preview.
  - The scrollable preview pane replaces a separate pager (no `$PAGER` view).

Sorting: default `updated` desc; `ctrl-t` cycles updated/created/messages/path
in the picker. (A non-interactive `--sort` flag is M5.)

## 7. Resume (primary action)

Verified command shapes:

- **Claude:** `claude --resume <session-id>`, executed **with cwd set to the
  session's `cwd`** (Claude resolves sessions per working directory). If the
  cwd no longer exists → warn and offer to resume from `$HOME` or abort.
- **opencode:** `opencode <directory> --session <session-id>` (positional
  project dir + `-s`). Optional `--fork` passthrough via `aism --fork`.

Resume runs by `exec`-ing the CLI so the user lands directly in the TUI. The
exact `resume_argv` is built by each adapter, and shown (dry-run) with
`aism --print-resume`. 🔴 The target CLI must be on `PATH`; if missing, `aism`
prints the command instead of failing silently.

## 8. Non-interactive CLI (scripting surface)

Even though the interactive UI is the default, every capability is a flag so it
composes in pipes:

```
aism list [filters] [--json]            # print sessions, one per line / JSON
aism search <query> [filters] [--json]  # content search, ranked
aism preview <tool> <id>                # render transcript (used by fzf too)
aism resume <tool> <id> [--fork]        # resume without the picker
aism path <tool> <id>                   # print source_ref (jsonl path / db)
aism reindex                            # rebuild content cache
aism doctor                             # check fzf/rg/bat, source availability
```

`--json` emits the `Session` records (§3) for downstream tooling.

## 9. Configuration

- Zero-config by default. Optional `~/.config/aism/config.toml`:
  - `claude_root`, `opencode_db` path overrides (else env/default).
  - `default_tool_filter`, `default_sort`, `preview_tool` (`bat`/`plain`).
  - `include_tools`, `include_reasoning` defaults for content extraction.
- Env overrides respected: `$CLAUDE_CONFIG_DIR`, `$OPENCODE_DB`,
  `$XDG_CACHE_HOME`, `$XDG_DATA_HOME`, `$PAGER`.

## 10. Edge cases & defensive rules

- Corrupt/partial JSONL line → skip the line, keep the session (log at
  `--verbose`); a session is never dropped for one bad event.
- Empty sessions (no user text) → listed, title falls back to `"(empty)"`.
- Very large JSONL (observed 24 MB / 12k lines) → header scan reads only the
  lines needed for metadata; full parse only on preview/extract.
- DB locked / mid-write → read-only connection + `busy_timeout`; on failure,
  retry once then surface a clear error via `doctor`.
- Missing `fzf`/`rg` → `doctor` explains install; interactive mode refuses to
  start with an actionable message rather than a stack trace.
- Path filters match against the **real cwd**, never the encoded folder name.
- Timezones normalized to UTC internally; displayed in local time.

## 11. Explicit non-goals (v1)

- Reading opencode's legacy file storage tree (DB only).
- Writing to / mutating either tool's store (strictly read-only, except our own
  cache).
- Cross-machine sync, cloud sharing, web UI.
- Editing, merging, or deleting sessions.

## 12. Milestones

1. ✅ **M1 — read models:** both adapters produce `Session` lists; `aism list`
   + `--json` + filters. Tested against fixture JSONL and a fixture DB.
2. ✅ **M2 — content search:** extraction cache + `aism search` + `aism preview`.
3. ✅ **M3 — fzf UI:** interactive browser, live content toggle, preview.
4. ✅ **M4 — resume:** verified resume for both tools + `doctor`.
5. ⬜ **M5 — polish:** config file (§9 not yet implemented), packaging as a
   `uv tool`/pipx install, richer preview (bat), search-index reasoning/tools.

## 13. Testing

- Adapters tested against **fixtures** (a tiny sample JSONL and a generated
  sample SQLite DB) — contract-focused: assert `Session` field shapes and
  content extraction, not incidental formatting.
- No test reads the user's real `~/.claude` or `opencode.db`.
- `doctor` covered by a smoke test (tool presence detection).
- fzf/preview orchestration tested by asserting the argv/preview command built,
  not by driving a live terminal.
- 12 tests pass (`uv run --with pytest python -m pytest`). Content-search tests
  use the pure-Python fallback so they pass without ripgrep installed.

## 14. As-built notes & deviations from the original design

- **Modules merged for simplicity** (per "keep it simple"): `index.py` +
  `search.py` → `content.py`; `resume.py` folded into each adapter's
  `resume_argv()` plus a small `_resume()` in `cli.py`; session loading/filters
  live in `cli.py` (no separate `catalog.py`). Added `util.py` and
  `__main__.py`. Zero third-party runtime dependencies (stdlib only).
- **Search index is text-only** in v1 (§5) — reasoning/tool output excluded.
- **opencode JSON parsed in Python**, not via `json_extract`, for portability.
- **`git_branch`** is Claude-only; **`agent`** is opencode-only; both degrade to
  `None` on the other tool. `--branch`/`--agent` filters reflect that.
- **Metadata cache** (`~/.cache/aism/claude-meta.json`) makes repeat Claude
  scans instant (keyed by file mtime+size); opencode is a single fast query and
  is not cached. Content cache lives in `~/.cache/aism/content/<tool>/<id>.txt`.
- **Verified live** against a real store (hundreds of sessions across both
  tools): cross-tool content search, name/path search, sort toggle, preview,
  and `resume --print` for both CLIs. Interactive fzf flow verified end-to-end
  in a tmux harness (session search, `ctrl-f` content search, `ctrl-t` sort).
- **Not yet built (M5):** `~/.config/aism/config.toml`, `bat`-rendered preview.
