#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""PreToolUse hook on Agent and Task: in a project whose `.harness.json` has a `brief` key, the main session's prompt for a
harness role holds the lines the role needs. A call that carries `agent_id` came from a sub-agent and passes.

`brief.required` maps a role, or `*` for the rest, to the labels a line of the prompt must start with. A custom `required` REPLACES
DEFAULT_REQUIRED: a role it does not list is unchecked unless a `*` entry covers it. DEFAULT_REQUIRED stands when it is not set. A `Budget:` line that names no turns (`Budget: 5 minutes`) is refused too, since `budget.py` would
silently use the default. It applies to every agent type, with or without the `harness:` prefix.
"""

from __future__ import annotations

import json
import os
import sys

from budget import LABELLED_BUDGET, QUOTED, get_turn_limit
from common import PLUGIN_PREFIX, find_project, get_unfenced_lines

DEFAULT_REQUIRED = {"worker": ["Goal:", "Write set:", "Judge:"], "*": ["Goal:"]}
# What may stand before a label on its line: a list bullet, a heading mark, bold markers.
LINE_MARKS = " \t-*#"


def get_missing(prompt: str, labels: list[str], /) -> list[str]:
    """The labels no line of the prompt starts with."""

    lines = [line.lstrip(LINE_MARKS) for line in prompt.splitlines()]

    return [label for label in labels if not any(line.startswith(label) for line in lines)]


def has_unreadable_budget(prompt: str, /) -> bool:
    """Whether a line of the prompt labels a budget that `budget.py` cannot read."""

    lines = [QUOTED.sub("", line) for line in get_unfenced_lines(prompt)]

    return any(LABELLED_BUDGET.search(line) and get_turn_limit(line) is None for line in lines)


def main() -> int:
    event = json.load(sys.stdin)
    if event.get("agent_id"):
        return 0
    root, config = find_project(event.get("cwd") or os.getcwd())
    if root is None or "brief" not in config:
        return 0
    tool_input = event.get("tool_input") or {}
    role = (tool_input.get("subagent_type") or "").removeprefix(PLUGIN_PREFIX)
    required = (config["brief"] or {}).get("required", DEFAULT_REQUIRED)
    missing = get_missing(tool_input.get("prompt") or "", required.get(role, required.get("*", [])))
    if has_unreadable_budget(tool_input.get("prompt") or ""):
        print("Blocked by the harness brief rule: a budget counts model turns. Write `Budget: 30 turns`.", file=sys.stderr)
        return 2
    if not missing:
        return 0
    print(f"Blocked by the harness brief rule: a brief for {role or "this agent"} needs the lines {', '.join(missing)}", file=sys.stderr)

    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # a bug in the rule must not block every call
        print(f"the harness brief rule failed and let the call run: {error!r}", file=sys.stderr)
        sys.exit(1)
