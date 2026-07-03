# ai-session-manager (`aism`)

Browse, search, and resume every local **Claude Code** and **opencode** session
from one `fzf` window.

```
uv run aism                      # interactive picker (default)
uv run aism search "rate limit"  # find sessions that mention something
uv run aism list --path ~/Github/myproject --tool claude
uv run aism resume opencode ses_xxx
uv run aism doctor               # check deps + source availability
```

In the picker: type to fuzzy-match **name + path**; `ctrl-f` = search **all**
(name + path + message content); `ctrl-s` back to sessions; `ctrl-t` cycle
sort (updated/created/messages/path); `enter` resume; `ctrl-o` print path;
`ctrl-y` copy id; `shift-↑/↓` scroll preview.

- 🔎 **Live full-text search** across message content of both tools.
- 📁 **Filter by working directory**, tool, branch, model, agent, date.
- ↩️ **Resume** the selected session in its original directory (`enter`).
- 🧩 Read-only. Never mutates your session stores.

## How it reads your sessions

| Tool        | Location                                   | Format |
|-------------|--------------------------------------------|--------|
| Claude Code | `~/.claude/projects/<cwd>/<uuid>.jsonl`    | JSONL event log |
| opencode    | `~/.local/share/opencode/opencode.db`      | SQLite (read-only) |

See [SPEC.md](./SPEC.md) for the full design, data-format details, and
milestones.

## Install

Homebrew tap: https://github.com/Yarden-zamir/homebrew-tap

```
brew install yarden-zamir/tap/aism
```

This pulls `uv`, `fzf`, and `ripgrep` (uv manages the Python runtime, so there's
no separate Python dependency). Then run `aism`.

To run from source instead: `uv run aism`.

## Requirements

- Python ≥ 3.11 (the Homebrew formula lets [`uv`](https://docs.astral.sh/uv/) provide it)
- [`fzf`](https://github.com/junegunn/fzf) and [`ripgrep`](https://github.com/BurntSushi/ripgrep)
- optional: [`bat`](https://github.com/sharkdp/bat) for nicer previews

## Commands

| Command | What it does |
|---------|--------------|
| `aism` | Interactive fzf picker (metadata + live content search) |
| `aism list [filters] [--json]` | List sessions |
| `aism search <query> [filters]` | Sessions whose content matches |
| `aism preview <tool> <id>` | Render a transcript |
| `aism resume <tool> <id> [--fork] [--print]` | Resume (or print the command) |
| `aism path <tool> <id>` | Print the session's source path |
| `aism reindex` | Rebuild the content search cache |
| `aism doctor` | Check `fzf`/`rg`/`bat` + source availability |

Filters: `--tool`, `--path`, `--branch`, `--agent`, `--model`, `--since`,
`--until`, `--grep`.

## Status

Working (v0.1.0) — M1–M4 done, verified against real Claude + opencode stores.
See [SPEC.md](./SPEC.md) §14 for as-built notes and §12 for remaining polish
(config file, packaged install). Run via `uv run aism` today.

## License

MIT © Yarden-zamir
