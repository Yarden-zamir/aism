from __future__ import annotations

from .claude import ClaudeAdapter
from .opencode import OpencodeAdapter


def all_adapters() -> list:
    return [ClaudeAdapter(), OpencodeAdapter()]


def get_adapters(tool: str | None = None) -> list:
    adapters = all_adapters()
    if tool:
        adapters = [a for a in adapters if a.tool == tool]
    return [a for a in adapters if a.available()]


def get_adapter(tool: str):
    for a in all_adapters():
        if a.tool == tool:
            return a
    raise KeyError(f"unknown tool: {tool}")
