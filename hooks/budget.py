#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""PreToolUse hook on every tool: in a project with `.harness.json`, a sub-agent past its budget of model turns is refused every
tool call but the handback and told to send its report now, as a partial one. A call without `agent_id` came from the main session and
passes.

A turn is one model message, however many tools it calls, so a slow machine or a long test costs nothing. The budget is the first
`Budget: N` or `Budget: N turns` outside a fence and a backtick quote in the agent's brief (its transcript's first line), opening a line or a
sentence, so prose such as `over budget: 20` does not count. Any other unit (`Budget: 5 files`, `Budget: 5 minutes`) does not count; the brief rule refuses it. Without one the role's default stands: `.harness.json`'s `budget` maps a role to turns and REPLACES the whole DEFAULT_BUDGET
table (a role it does not list has no budget); DEFAULT_BUDGET stands when the key is absent. The handback
always passes, so the agent is never trapped. Only that first line is read, since this runs on every call.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from common import HANDBACK_TOOL, PLUGIN_PREFIX, find_project, get_turns, get_unfenced_lines, read_events

# Turns, near the 99th percentile of past agents of each role, so a default stops a runaway agent and no ordinary one.
DEFAULT_BUDGET = {"scout": 35, "cold-reader": 20, "runner": 30, "reviewer": 35, "auditor": 35, "worker": 70}
BUDGET_LABEL = re.compile(r"(?:^|[.;]\s+)[\s\-*#]*budget\b", re.I)
# A line that labels a budget, as opposed to prose that opens with the word.
LABELLED_BUDGET = re.compile(BUDGET_LABEL.pattern + r"\**\s*:", re.I)
BUDGET_LINE = re.compile(BUDGET_LABEL.pattern + r"[:*\s~]*([0-9]+)\s*(?:turns?\b|(?=\W*$))", re.I)
QUOTED = re.compile(r"`[^`]*`")
TAIL_BYTES = 262144


def get_agent_path(event: dict, /) -> Path | None:  # keys are data
    """The agent's own transcript: `subagents/agent-<id>.jsonl` in the folder named like the session's, or the stop event's."""

    given = event.get("agent_transcript_path") or ""
    if os.path.isfile(given):
        return Path(given)
    session = event.get("transcript_path") or ""
    agent_id = event.get("agent_id") or ""
    if not session or not agent_id:
        return None
    path = Path(session).with_suffix("") / "subagents" / f"agent-{agent_id}.jsonl"

    return path if path.is_file() else None


def parse_time(text: object, /) -> float | None:
    """Epoch seconds of an ISO timestamp, None when it is not one."""

    # Python 3.10 reads a fraction of exactly 3 or 6 digits only.
    clean = re.sub(r"\.([0-9]+)", lambda match: "." + match.group(1)[:6].ljust(6, "0"), str(text).replace("Z", "+00:00"))
    try:
        moment = datetime.fromisoformat(clean)
    except ValueError:
        return None

    return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).timestamp()


def get_brief(entry: dict, /) -> str:  # keys are data
    """The text of a transcript's first line."""

    content = (entry.get("message") or {}).get("content")
    if isinstance(content, list):
        return "\n".join(block.get("text") or "" for block in content if isinstance(block, dict))

    return content if isinstance(content, str) else ""


def get_turn_limit(brief: str, /) -> int | None:
    """The turns of the brief's `Budget:` line, None when it has none."""

    for line in get_unfenced_lines(brief):
        match = BUDGET_LINE.search(QUOTED.sub("", line))
        if match:
            return int(match.group(1))

    return None


def get_default(config: dict, role: str, /) -> int | None:  # keys are data
    """The turns `.harness.json` (or DEFAULT_BUDGET) gives a role, None when it gives none."""

    turns = config.get("budget", DEFAULT_BUDGET).get(role)

    return int(turns) if isinstance(turns, (int, float)) and not isinstance(turns, bool) else None


def get_duration(path: Path | None, /) -> float | None:
    """Seconds from an agent transcript's first timestamp to its last, None when unknown."""

    if path is None:
        return None
    with open(path, "rb") as file:
        first = parse_time(json.loads(file.readline()).get("timestamp"))
        file.seek(0, os.SEEK_END)
        file.seek(max(0, file.tell() - TAIL_BYTES))
        lines = file.read().decode(errors="replace").splitlines()
    for line in reversed(lines):
        try:
            last = parse_time(json.loads(line).get("timestamp"))
        except (ValueError, AttributeError):
            continue
        if last is not None:
            return None if first is None else round(last - first, 1)

    return None


def main() -> int:
    event = json.load(sys.stdin)
    if not event.get("agent_id") or event.get("tool_name") == HANDBACK_TOOL:
        return 0
    root, config = find_project(event.get("cwd") or os.getcwd())
    path = get_agent_path(event)
    if root is None or path is None:
        return 0
    with open(path, errors="replace") as file:
        first = json.loads(file.readline())
    role = (event.get("agent_type") or "").removeprefix(PLUGIN_PREFIX)
    limit = get_turn_limit(get_brief(first))
    if limit is None:
        limit = get_default(config, role)
    if limit is None:
        return 0
    turns = get_turns(read_events(path))
    # The message of this very call may not have reached the transcript yet, as a live run showed; it counts all the same.
    call_id = event.get("tool_use_id")
    is_written = not call_id or any(call.get("id") == call_id for call in (turns[-1] if turns else ()))
    num_turns = len(turns) + (not is_written)
    if num_turns <= limit:
        return 0
    print(
        f"Blocked by the harness budget rule: your budget of {limit} turns is spent ({num_turns} turns so far). "
        "Stop now. Send your report now as a partial report: done, not done, what is on disk. It is still judged by the report form. A handback and a final message both pass.",
        file=sys.stderr,
    )

    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # a bug in the rule must not block every call
        print(f"the harness budget rule failed and let the call run: {error!r}", file=sys.stderr)
        sys.exit(1)
