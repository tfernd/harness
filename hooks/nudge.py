#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""PostToolUse hook on Read, Grep, Glob and Bash: in every project, adds one line of context at the moment an
agent wastes tool turns, and never refuses. It fires on an exact repeat of a small read with no edit since, and on
every RUN_LENGTH single small reads in a row, at most MAX_NUDGES times per agent, and stays silent past MAX_BYTES of transcript.
It also notes, once per agent, a test, lint or build piped into `tail` or `head` with no `pipefail`, which hides the failure. A call in the agent's own transcript counts,
so no state is kept. `report_gate.py` and `import_reports.py` write the same counts to the ledger for `harness:retro`.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

from budget import get_agent_path
from common import EDIT_TOOLS, find_project, get_turns, read_events

READ_TOOLS = frozenset({"Read", "Grep", "Glob"})
SMALL_COMMANDS = frozenset({"cat", "bat", "sed", "head", "tail", "grep", "rg", "ls", "wc", "find"})
LEADING_CD = re.compile(r"^cd\s+\S+\s*(?:&&|;)\s*")
# A command that batches several steps, or that writes, is not a small read.
BATCHED_OR_WRITING = re.compile(r";|&&|\|\||\n|>|^sed\s(.*\s)?-i|\s-delete\b|\s-exec")
# Three single small reads in a row could have been one call; MAX_NUDGES keeps the note from turning into noise.
RUN_LENGTH = 3
MAX_NUDGES = 2
# A longer transcript gets no nudge: this runs on every read, and only a whole transcript can count the cap.
MAX_BYTES = 1048576
# A pipe splits at one `|` (not `||`); a list splits at `;`, `&&`, `||` and a newline. Quoted text is blanked first.
QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
LIST_SPLIT = re.compile(r"&&|\|\||[;\n]")
PIPE_SPLIT = re.compile(r"(?<!\|)\|(?!\|)&?")
# A heredoc body is text, not commands: the command is read up to its operator.
HEREDOC = re.compile(r"<<(?!<)")
PIPEFAIL = re.compile(r"\bpipefail\b")
ZSH_STATUS = re.compile(r"\$\{?pipestatus")
BASH_STATUS = re.compile(r"\$\{?PIPESTATUS")
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
PIPE_SINKS = frozenset({"tail", "head"})
# Programs that are a gate alone, and those that are one with a subcommand (`cargo test`, `go test`).
GATE_PROGRAMS = frozenset({"pytest", "make", "ruff", "tsc"})
GATE_SUBCOMMANDS = {"cargo": {"test"}, "go": {"test"}, "npm": {"test", "run"}, "bun": {"test", "run"}, "pnpm": {"test", "run"}}
SCRIPT_RUNNERS = frozenset({"python", "python3", "bash", "sh", "zsh"})
TESTS_SCRIPT = re.compile(r"(?:^|/)tests/")
PIPEFAIL_TEXT = (
    "Harness note, not a refusal: a test, lint or build piped into tail or head reports the exit code of tail or head, "
    "so a failure can pass unseen. Start the command with `set -o pipefail;` and read `$pipestatus` in zsh."
)
ZSH_STATUS_TEXT = (
    "Harness note, not a refusal: in zsh the array is `$pipestatus` in lowercase; `$PIPESTATUS` is empty there. "
    "`set -o pipefail;` at the start also makes a pipe fail with its first failing command."
)
REPEAT_TEXT = "Harness note, not a refusal: you already made this same read and edited nothing since. Use what you have, unless a command changed it."
RUN_TEXT = (
    f"Harness note, not a refusal: your last {RUN_LENGTH} turns were one small read each. "
    "Get what you still need at once: one script, or parallel calls in one message."
)


class Waste(NamedTuple):
    """What a run of turns wasted; `nudges` holds (call id, text) in the order they fell due."""

    nudges: list[tuple[str, str]]
    longest_run: int
    small_reads: int
    repeats: int


def is_small_read(call: dict, /) -> bool:  # keys are data
    """Whether a call only reads, and reads one thing: a read tool, or one shell command that a script could have joined."""

    name = call.get("name")
    if name in READ_TOOLS:
        return True
    if name != "Bash":
        return False
    command = LEADING_CD.sub("", str((call.get("input") or {}).get("command") or "").strip())
    words = command.split()

    return bool(words) and words[0] in SMALL_COMMANDS and not BATCHED_OR_WRITING.search(command)


def is_gate(piece: str, /) -> bool:
    """Whether one command of a pipe runs a test, lint or build."""

    words = piece.split()
    while words and ASSIGNMENT.match(words[0]):
        words.pop(0)
    if words[:2] == ["uv", "run"]:
        words = [word for word in words[2:] if not word.startswith("-")]
    if not words:
        return False
    program = os.path.basename(words[0])
    if TESTS_SCRIPT.search(words[0]) or program in GATE_PROGRAMS:
        return True
    if program in SCRIPT_RUNNERS:
        return any(TESTS_SCRIPT.search(word) or word == "pytest" for word in words[1:3])

    return len(words) > 1 and words[1] in GATE_SUBCOMMANDS.get(program, ())


def get_pipe_note(command: str, /) -> str:
    """The note for a shell command that hides a gate's failure behind `tail` or `head`; empty when it does not."""

    if PIPEFAIL.search(command):
        return ""
    if os.path.basename(os.environ.get("SHELL") or "") == "zsh" and BASH_STATUS.search(command) and not ZSH_STATUS.search(command):
        return ZSH_STATUS_TEXT
    if ZSH_STATUS.search(command) or BASH_STATUS.search(command):
        return ""
    for part in LIST_SPLIT.split(QUOTED.sub("x", HEREDOC.split(command)[0])):
        pieces = PIPE_SPLIT.split(part)
        for index, piece in enumerate(pieces[1:], 1):
            words = piece.split()
            if words and os.path.basename(words[0]) in PIPE_SINKS and any(is_gate(earlier) for earlier in pieces[:index]):
                return PIPEFAIL_TEXT

    return ""


class PipeNudge(NamedTuple):
    """The id of a Bash call that hides a failure and the note to send."""

    call_id: str
    note: str


def get_pipe_nudge(turns: list[list[dict]], /) -> PipeNudge | None:
    """The first Bash call of the run that hides a failure, with its note; one per agent."""

    for turn in turns:
        for call in turn:
            if call.get("name") != "Bash":
                continue
            note = get_pipe_note(str((call.get("input") or {}).get("command") or ""))
            if note:
                return PipeNudge(str(call.get("id")), note)

    return None


def get_waste(turns: list[list[dict]], /) -> Waste:  # keys are data
    """Walks the turns in order. An edit forgets the reads before it; a command may change a file too, which the nudge's text allows for."""

    nudges: list[tuple[str, str]] = []
    seen: set[str] = set()
    run = longest_run = small_reads = repeats = 0
    for turn in turns:
        is_small_turn = len(turn) == 1 and is_small_read(turn[0])
        run = run + 1 if is_small_turn else 0
        longest_run = max(longest_run, run)
        if run and run % RUN_LENGTH == 0:
            nudges.append((str(turn[0].get("id")), RUN_TEXT))
        for call in turn:
            if not is_small_read(call):
                if call.get("name") in EDIT_TOOLS:
                    seen.clear()
                continue
            small_reads += 1
            key = json.dumps([call.get("name"), call.get("input")], sort_keys=True)
            if key in seen:
                repeats += 1
                nudges.append((str(call.get("id")), REPEAT_TEXT))
            seen.add(key)

    return Waste(nudges, longest_run, small_reads, repeats)


def get_turn_stats(events: list[dict], /) -> dict:  # keys are data
    """The ledger's `tool_turns` field for one agent's transcript."""

    turns = get_turns(events)
    waste = get_waste(turns)

    return {
        "turns": len(turns),
        "calls": sum(len(turn) for turn in turns),
        "one_call_turns": sum(len(turn) == 1 for turn in turns),
        "longest_small_run": waste.longest_run,
        "small_reads": waste.small_reads,
        "repeats": waste.repeats,
    }


def main() -> int:
    event = json.load(sys.stdin)
    path = get_agent_path(event) if event.get("agent_id") else Path(event.get("transcript_path") or "")
    if path is None or not path.is_file() or path.stat().st_size > MAX_BYTES:
        return 0
    turns = get_turns(read_events(path))
    if not turns:
        return 0
    call_id = str(event.get("tool_use_id") or turns[-1][-1].get("id"))
    waste = get_waste(turns)
    text = dict(waste.nudges[:MAX_NUDGES]).get(call_id)
    pipe_nudge = get_pipe_nudge(turns)
    if pipe_nudge and pipe_nudge[0] == call_id:
        text = f"{text} {pipe_nudge[1]}" if text else pipe_nudge[1]
    if text:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}))

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # a bug in a nudge must not touch the call
        print(f"the harness nudge hook failed: {error!r}", file=sys.stderr)
        sys.exit(1)
