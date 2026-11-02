#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""PreToolUse hook on every tool: in a project with `.harness.json`, a sub-agent past its time budget is refused every
tool call but the handback and told to send its report now, as a partial one. A call without `agent_id` came from the main session and
passes.

The budget is the first `Budget: N` outside a fence and a backtick quote in the agent's brief (its transcript's first line), opening a line or a
sentence, so prose such as `over budget: 20` does not count; N is minutes, or hours with `hours` or `h`. A number followed by another word (`Budget: 5 files`) does not count. Without one the role's default stands: `.harness.json`'s `budget` maps a role to minutes and REPLACES the whole DEFAULT_BUDGET
table (a role it does not list has no budget); DEFAULT_BUDGET stands when the key is absent. The clock starts at the first line's timestamp. The handback
always passes, so the agent is never trapped. Only that first line is read, since this runs on every call.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from common import HANDBACK_TOOL, PLUGIN_PREFIX, find_project, get_unfenced_lines

DEFAULT_BUDGET = {"scout": 5, "cold-reader": 5, "runner": 10, "reviewer": 10, "auditor": 10, "worker": 15}
BUDGET_LINE = re.compile(r"(?:^|[.;]\s+)[\s\-*#]*(?:time\s+)?budget\b[:*\s~]*([0-9]+(?:\.[0-9]+)?)\s*(?:(minutes?|mins?|m|hours?|hrs?|h)\b|(?=\W*$))", re.I)
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


def get_minutes(brief: str, /) -> float | None:
    """The minutes of the brief's `Budget:` line, None when it has none."""

    for line in get_unfenced_lines(brief):
        match = BUDGET_LINE.search(QUOTED.sub("", line))
        if match:
            is_hours = (match.group(2) or "").lower().startswith("h")
            return float(match.group(1)) * (60 if is_hours else 1)

    return None


def get_default(config: dict, role: str, /) -> float | None:  # keys are data
    """The minutes `.harness.json` (or DEFAULT_BUDGET) gives a role, None when it gives none."""

    minutes = config.get("budget", DEFAULT_BUDGET).get(role)

    return float(minutes) if isinstance(minutes, (int, float)) and not isinstance(minutes, bool) else None


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
    started = parse_time(first.get("timestamp"))
    role = (event.get("agent_type") or "").removeprefix(PLUGIN_PREFIX)
    minutes = get_minutes(get_brief(first))
    if minutes is None:
        minutes = get_default(config, role)
    if started is None or minutes is None:
        return 0
    spent = (time.time() - started) / 60
    if spent <= minutes:
        return 0
    print(
        f"Blocked by the harness budget rule: your budget of {minutes:g} minutes is spent ({spent:.0f} minutes since you "
        "started). Stop now. Send your report now as a partial report: done, not done, what is on disk. It is still judged by the report form. A handback and a final message both pass.",
        file=sys.stderr,
    )

    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # a bug in the rule must not block every call
        print(f"the harness budget rule failed and let the call run: {error!r}", file=sys.stderr)
        sys.exit(1)
