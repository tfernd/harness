#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from budget import LABELLED_BUDGET, QUOTED, get_turn_limit
from common import PLUGIN_PREFIX, find_project, get_unfenced_lines, make_note_output

DEFAULT_REQUIRED = {
    "worker": ["Goal:", "Write set:", "Judge:"],
    "reviewer": ["Goal:", "Input:", "Tree:"],
    "auditor": ["Goal:", "Input:", "Judge:"],
    "runner": ["Goal:", "Runs:"],
    "designer": ["Goal:", "Write set:"],
    "releaser": ["Goal:", "Write set:"],
    "*": ["Goal:"],
}
GENERIC_AGENTS = frozenset({"", "general-purpose", "explore", "plan", "claude"})
GENERIC_REFUSAL = (
    "Blocked by the harness brief rule: {name} has no harness role, so it gets no role skills, no report form and no turn budget. "
    "Send the same brief to a role: harness:scout finds a fact, harness:worker makes a change, harness:runner runs checks, "
    "harness:reviewer reviews, harness:planner plans, harness:researcher reads outside sources, harness:designer designs, harness:releaser releases."
)
MISSING_AGENT_REFUSAL = (
    "Blocked by the harness brief rule: {name} is no agent of this plugin (it holds no agents/{role}.md). "
    "Use one of its roles: {roles}."
)
LINE_MARKS = " \t-*#"


def get_missing(prompt: str, labels: list[str], /) -> list[str]:

    lines = [line.lstrip(LINE_MARKS) for line in prompt.splitlines()]

    return [label for label in labels if not any(line.startswith(label) for line in lines)]


def has_unreadable_budget(prompt: str, /) -> bool:

    lines = [QUOTED.sub("", line) for line in get_unfenced_lines(prompt)]

    return any(LABELLED_BUDGET.search(line) and get_turn_limit(line) is None for line in lines)


def get_roles() -> list[str]:

    plugin = Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or Path(__file__).resolve().parent.parent)

    return sorted(path.stem for path in (plugin / "agents").glob("*.md"))


def main() -> int:
    event = json.load(sys.stdin)
    if event.get("agent_id"):
        return 0
    _, config = find_project(event.get("cwd") or os.getcwd())
    tool_input = event.get("tool_input") or {}
    given = tool_input.get("subagent_type")
    agent_type = given.strip().casefold() if isinstance(given, str) else ""
    if agent_type in GENERIC_AGENTS:
        print(GENERIC_REFUSAL.format(name=f"`{given.strip()}`" if agent_type else "an agent with no type"), file=sys.stderr)
        return 2
    role = agent_type.removeprefix(PLUGIN_PREFIX)
    roles = get_roles()
    if agent_type.startswith(PLUGIN_PREFIX) and roles and (not re.fullmatch(r"[\w-]+", role) or role not in roles):
        print(MISSING_AGENT_REFUSAL.format(name=f"`{given.strip()}`", role=role, roles=", ".join(f"{PLUGIN_PREFIX}{name}" for name in roles)), file=sys.stderr)
        return 2
    if "brief" not in config:
        return 0
    required = (config["brief"] or {}).get("required", DEFAULT_REQUIRED)
    missing = get_missing(tool_input.get("prompt") or "", required.get(role, required.get("*", [])))
    notes = []
    if has_unreadable_budget(tool_input.get("prompt") or ""):
        notes.append("a budget counts model turns, and this brief's budget line names none, so the agent gets the default. Next time write `Budget: 30 turns`, or reword the line if it means something else.")
    if missing:
        notes.append(f"a brief for {role} needs the lines {', '.join(missing)}, and this one lacks them.")
    if notes:
        print(json.dumps(make_note_output("\n".join(f"The harness brief rule let this call run: {note}" for note in notes))))

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"the harness brief rule failed and let the call run: {error!r}", file=sys.stderr)
        sys.exit(1)
