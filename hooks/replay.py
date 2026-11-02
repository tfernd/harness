#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""Replay judge: run every Bash command of the owner's past sessions through the guard's always-on rules.

Why: those rules run in every project, so a false refusal costs the most. This reads `~/.claude/projects/**/*.jsonl`,
read-only, runs the guard in no-project mode in-process, and prints the total, the refusals by rule and a sample of each,
so a person can judge which class is false. A command runs from the folder its transcript line names, and a glob is
matched against today's files there. A command in one folder is counted once however many sessions hold it, and prints cut
to 120 characters on one line. It writes nothing. Stdlib only.

uv run --script hooks/replay.py [--root FOLDER] [--sample N] [--rule RULE] [--find TEXT]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Iterator
from pathlib import Path

from guard import find_command_breaches

MAX_SHOWN = 120
# A line holds a Bash call only if it holds this text, which saves parsing most of the bytes.
BASH_MARK = '"name":"Bash"'


def get_commands(path: Path, /) -> Iterator[tuple[str, str | None]]:
    """The Bash commands of one transcript's assistant lines with their folders; other lines replay the same calls."""

    with open(path, errors="replace") as file:
        for line in file:
            if BASH_MARK not in line or '"type":"assistant"' not in line:
                continue
            try:
                entry = json.loads(line)
                content = entry.get("message", {}).get("content")
            except (ValueError, AttributeError):
                continue
            if entry.get("type") != "assistant" or not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Bash":
                    command = (block.get("input") or {}).get("command")
                    if isinstance(command, str):
                        yield command, entry.get("cwd")


def show(command: str, /) -> str:
    """A command on one line, cut to MAX_SHOWN characters."""

    return json.dumps(command, ensure_ascii=False)[1:-1][:MAX_SHOWN]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path.home() / ".claude" / "projects", help="the folder of transcripts")
    parser.add_argument("--sample", type=int, default=15, help="the commands shown per rule")
    parser.add_argument("--rule", default="", help="show only this rule")
    parser.add_argument("--find", default="", help="show only the refused commands holding this text")
    arguments = parser.parse_args()
    os.environ.pop("CLAUDE_PROJECT_DIR", None)
    start = time.monotonic()
    calls = 0
    distinct: set[tuple[str, str | None]] = set()
    paths = sorted(arguments.root.rglob("*.jsonl"))
    for path in paths:
        for call in get_commands(path):
            calls += 1
            distinct.add(call)
    refused: dict[str, list[str]] = defaultdict(list)
    crashes = Counter()
    for command, cwd in sorted(distinct, key=lambda call: call[0]):
        try:
            for rule in find_command_breaches(command, cwd):
                refused[rule].append(command)
        except RecursionError:
            crashes["recursion"] += 1
    num_commands = len({command for command, _ in distinct})
    total_refused = len({command for commands in refused.values() for command in commands})
    print(f"{len(paths)} transcripts, {calls} Bash calls, {num_commands} distinct commands, {time.monotonic() - start:.0f}s")
    print(f"refused: {total_refused} distinct ({total_refused / max(num_commands, 1):.2%}); parser crashes: {sum(crashes.values())}")
    randomizer = random.Random(0)
    for rule, commands in sorted(refused.items(), key=lambda item: -len(item[1])):
        print(f"\n== {rule}: {len(commands)}")
        if arguments.rule and rule != arguments.rule:
            continue
        shown = [command for command in commands if arguments.find in command]
        for command in randomizer.sample(shown, min(arguments.sample, len(shown))):
            print(f"  {show(command)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
