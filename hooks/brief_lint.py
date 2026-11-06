#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""PreToolUse hook on Agent and Task: in a project whose `.harness.json` has a `brief` key, the main session's prompt for a
harness role should hold the lines the role needs. The call always runs; a prompt that falls short gets a note in
`additionalContext`. A call that carries `agent_id` came from a sub-agent and passes unchecked.

`brief.required` maps a role, or `*` for the rest, to the labels a line of the prompt must start with. A custom `required` REPLACES
DEFAULT_REQUIRED: a role it does not list is unchecked unless a `*` entry covers it. DEFAULT_REQUIRED stands when it is not set. A `Budget:` line that names no turns (`Budget: 5 minutes`) is noted too, since `budget.py` would
silently use the default. It applies to every agent type, with or without the `harness:` prefix.

One case refuses, in any project, with or without `.harness.json` or its `brief` key: an agent of a generic type (GENERIC_AGENTS, or none
named). It has no role, so it gets no role skills, no
report form and no default turn budget, and the longest agents in real transcripts were all of this kind.
"""

from __future__ import annotations

import json
import os
import sys

from budget import LABELLED_BUDGET, QUOTED, get_turn_limit
from common import PLUGIN_PREFIX, find_project, get_unfenced_lines, make_note_output

# Each role's lines come from its agent file: a reviewer reads the unit's spec ("Input:") and diffs against HEAD ("Tree:"),
# an auditor reruns "each Judge of the brief" and reads the brief and tree, a runner runs the commands the brief lists ("Runs:").
DEFAULT_REQUIRED = {
    "worker": ["Goal:", "Write set:", "Judge:"],
    "reviewer": ["Goal:", "Input:", "Tree:"],
    "auditor": ["Goal:", "Input:", "Judge:"],
    "runner": ["Goal:", "Runs:"],
    "*": ["Goal:"],
}
# Claude Code's built-in agent types that carry no harness role; the empty name is the type Claude Code picks when none is given.
GENERIC_AGENTS = frozenset({"", "general-purpose", "Explore", "Plan", "claude"})
GENERIC_REFUSAL = (
    "Blocked by the harness brief rule: {name} has no harness role, so it gets no role skills, no report form and no turn budget. "
    "Send the same brief to a role: harness:scout finds a fact, harness:worker makes a change, harness:runner runs checks, "
    "harness:reviewer reviews, harness:planner plans, harness:researcher reads outside sources."
)
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
    _, config = find_project(event.get("cwd") or os.getcwd())
    tool_input = event.get("tool_input") or {}
    agent_type = tool_input.get("subagent_type") or ""
    if agent_type in GENERIC_AGENTS:
        print(GENERIC_REFUSAL.format(name=f"`{agent_type}`" if agent_type else "an agent with no type"), file=sys.stderr)
        return 2
    if "brief" not in config:
        return 0
    role = agent_type.removeprefix(PLUGIN_PREFIX)
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
    except Exception as error:  # a bug in the rule must not block every call
        print(f"the harness brief rule failed and let the call run: {error!r}", file=sys.stderr)
        sys.exit(1)
