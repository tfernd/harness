#!/usr/bin/env -S python3 -I
"""PreToolUse hook on Agent and Task: in a project whose `.harness.json` has a `brief` key, the main session's prompt for a
harness role holds the lines the role needs. A call that carries `agent_id` came from a sub-agent and passes.

`brief.required` maps a role, or `*` for the rest, to the labels a line of the prompt must start with; DEFAULT_REQUIRED
stands when it is not set. It applies only to the six roles, with or without the `harness:` prefix; every other
`subagent_type` passes.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import PLUGIN_PREFIX, ROLES, find_project  # noqa: E402

DEFAULT_REQUIRED = {"worker": ["Goal:", "Write set:", "Judge:"], "*": ["Goal:"]}
# What may stand before a label on its line: a list bullet, a heading mark, bold markers.
LINE_MARKS = " \t-*#"


def get_missing(prompt: str, labels: list[str], /) -> list[str]:
    """The labels no line of the prompt starts with."""

    lines = [line.lstrip(LINE_MARKS) for line in prompt.splitlines()]

    return [label for label in labels if not any(line.startswith(label) for line in lines)]


def main() -> int:
    event = json.load(sys.stdin)
    if event.get("agent_id"):
        return 0
    root, config = find_project(event.get("cwd") or os.getcwd())
    if root is None or "brief" not in config:
        return 0
    tool_input = event.get("tool_input") or {}
    role = (tool_input.get("subagent_type") or "").removeprefix(PLUGIN_PREFIX)
    if role not in ROLES:
        return 0
    required = (config["brief"] or {}).get("required", DEFAULT_REQUIRED)
    missing = get_missing(tool_input.get("prompt") or "", required.get(role, required.get("*", [])))
    if not missing:
        return 0
    print(f"Blocked by the harness brief rule: a brief for {role} needs the lines {', '.join(missing)}", file=sys.stderr)

    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # a bug in the rule must not block every call
        print(f"the harness brief rule failed and let the call run: {error!r}", file=sys.stderr)
        sys.exit(1)
