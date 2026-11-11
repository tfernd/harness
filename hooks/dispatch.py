#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///

from __future__ import annotations

import contextlib
import importlib
import io
import json
import re
import sys
from typing import NamedTuple

ROUTES = {
    "SessionStart": (("", "context.py", ""),),
    "SubagentStart": (("", "context.py", ""),),
    "PreToolUse": (
        ("", "budget.py", ""),
        ("SubagentHandback", "report_gate.py", "handback"),
        ("Bash|Write|Edit|NotebookEdit", "guard.py", ""),
        ("Bash|Write|Edit|NotebookEdit", "skill_gate.py", ""),
        ("Bash", "commit_gate.py", ""),
    ),
    "PostToolUse": (("Agent|Task|Edit|Write|NotebookEdit|Bash", "turn.py", "add"),),
    "UserPromptSubmit": (("", "turn.py", "reset"),),
    "SubagentStop": (("", "report_gate.py", ""),),
    "Stop": (("", "turn.py", "stop"),),
}
PERMISSION_RANK = {"allow": 0, "ask": 1, "deny": 2}
BLOCKING_CODE = 2


class Result(NamedTuple):

    code: int
    stdout: str
    stderr: str


def is_routed(matcher: str, event: dict, /) -> bool:

    return not matcher or re.fullmatch(matcher, str(event.get("tool_name") or "")) is not None


def run_script(script: str, argument: str, raw: str, /) -> Result:

    out, err = io.StringIO(), io.StringIO()
    saved = sys.argv, sys.stdin
    sys.argv = [script, *([argument] if argument else [])]
    sys.stdin = io.StringIO(raw)
    code = 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = importlib.import_module(script.removesuffix(".py")).main() or 0
    except SystemExit as stop:
        code = stop.code if isinstance(stop.code, int) else 1
    except Exception as error:
        code = 1
        err.write(f"the harness {script} failed and let the call run: {error!r}\n")
    finally:
        sys.argv, sys.stdin = saved

    return Result(code, out.getvalue(), err.getvalue())


class Merged(NamedTuple):

    top: dict
    specific: dict
    contexts: list[str]
    messages: list[str]
    plain: list[str]


def add_result(merged: Merged, result: Result, /) -> bool:

    text = result.stdout.strip()
    if not text:
        return False
    try:
        payload = json.loads(text)
    except ValueError:
        merged.plain.append(text)
        return False
    if not isinstance(payload, dict):
        merged.plain.append(text)
        return False
    specific = payload.pop("hookSpecificOutput", None) or {}
    context = specific.pop("additionalContext", "")
    if context:
        merged.contexts.append(context)
    message = payload.pop("systemMessage", "")
    if message:
        merged.messages.append(message)
    rank = PERMISSION_RANK.get(specific.get("permissionDecision"), -1)
    if rank < PERMISSION_RANK.get(merged.specific.get("permissionDecision"), -1):
        specific = {key: value for key, value in specific.items() if not key.startswith("permissionDecision")}
    merged.specific.update(specific)
    merged.top.update(payload)

    return payload.get("decision") == "block" or merged.specific.get("permissionDecision") == "deny"


def print_merged(merged: Merged, name: str, /) -> None:

    top = dict(merged.top)
    if merged.messages:
        top["systemMessage"] = "\n".join(merged.messages)
    if merged.contexts or merged.specific:
        specific = {"hookEventName": name, **merged.specific}
        if merged.contexts:
            specific["additionalContext"] = "\n".join(merged.contexts)
        top["hookSpecificOutput"] = specific
    if top:
        print(json.dumps(top))
    if merged.plain:
        print("\n".join(merged.plain))


def main() -> int:
    name = sys.argv[1]
    raw = sys.stdin.read()
    event = json.loads(raw)
    merged = Merged({}, {}, [], [], [])
    errors: list[str] = []
    for matcher, script, argument in ROUTES[name]:
        if not is_routed(matcher, event):
            continue
        result = run_script(script, argument, raw)
        if result.code == BLOCKING_CODE:
            print("".join(errors) + result.stderr, end="", file=sys.stderr)
            return BLOCKING_CODE
        if result.code != 0 and result.stderr:
            errors.append(result.stderr)
        if add_result(merged, result):
            break
    print_merged(merged, name)
    print("".join(errors), end="", file=sys.stderr)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"the harness dispatcher failed and let the call run: {error!r}", file=sys.stderr)
        sys.exit(1)
