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
import shutil
import subprocess
import sys
from pathlib import Path

CHECKOUT = Path(__file__).resolve().parent.parent
KIRO_TOOLS = {
    "execute_bash": "Bash",
    "read_file": "Read",
    "fs_write": "Write",
    "fs_append": "Write",
    "str_replace": "Edit",
    "grep_search": "Grep",
    "file_search": "Glob",
    "invoke_sub_agent": "Agent",
}
AGENT_FIELDS = ("agent_name", "agent", "name", "subagent", "agent_type")
CORTEX_TOOLS = {
    "bash": "Bash",
    "read": "Read",
    "write": "Write",
    "edit": "Edit",
    "grep": "Grep",
    "glob": "Glob",
    "web_fetch": "WebFetch",
    "web_search": "WebSearch",
}
EVENT_NAMES = {"agentSpawn": "SessionStart", "AgentSpawn": "SessionStart"}
TEXT_EVENTS = ("SessionStart", "UserPromptSubmit")
BLOCK_EXIT = 2


def get_agent_type(tool_input: dict, /) -> str:
    for field in AGENT_FIELDS:
        value = tool_input.get(field)
        if isinstance(value, str) and value:
            return (
                "harness:" + value.removeprefix("harness-")
                if value.startswith("harness-")
                else value
            )
    return "host-agent"


def map_event(event: dict, host: str, event_name: str, /) -> dict:
    tools = KIRO_TOOLS if host == "kiro" else CORTEX_TOOLS
    mapped = dict(event)
    name = event_name or str(event.get("hook_event_name", ""))
    mapped["hook_event_name"] = EVENT_NAMES.get(name, name)

    tool = event.get("tool_name")
    if isinstance(tool, str):
        mapped["tool_name"] = tools.get(tool, tool)
    tool_input = event.get("tool_input")
    if isinstance(tool_input, dict):
        fixed = dict(tool_input)
        if "path" in fixed and "file_path" not in fixed:
            fixed["file_path"] = fixed["path"]
        if (
            mapped.get("tool_name") == "Bash"
            and "command" not in fixed
            and "cmd" in fixed
        ):
            fixed["command"] = fixed["cmd"]
        if mapped.get("tool_name") == "Agent" and not fixed.get("subagent_type"):
            fixed["subagent_type"] = get_agent_type(fixed)
        mapped["tool_input"] = fixed
    return mapped


def get_hook_output(stdout: str, /) -> dict:
    try:
        parsed = json.loads(stdout)
    except ValueError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    specific = parsed.get("hookSpecificOutput")
    return {**parsed, **specific} if isinstance(specific, dict) else parsed


def translate_kiro(stdout: str, stderr: str, event_name: str, /) -> int:
    output = get_hook_output(stdout)
    reason = str(
        output.get("permissionDecisionReason") or output.get("reason") or stderr.strip()
    )
    if output.get("permissionDecision") in ("ask", "deny"):
        print(reason or "Blocked by a harness hook.", file=sys.stderr)
        return BLOCK_EXIT
    if "updatedInput" in output:
        note = str(output.get("additionalContext") or "Use the corrected command.")
        print(
            f"Blocked: this call needs a change Kiro cannot apply for you. {note}",
            file=sys.stderr,
        )
        return BLOCK_EXIT
    if output.get("decision") == "block":
        print(stdout.strip())
        return 0
    context = output.get("additionalContext")
    if context and event_name in TEXT_EVENTS:
        print(context)
    elif not output and stdout.strip() and event_name in TEXT_EVENTS:
        print(stdout.strip())
    return 0


def translate_cortex(stdout: str, /) -> int:
    output = get_hook_output(stdout)
    if output.get("permissionDecision") == "ask":
        reason = str(
            output.get("permissionDecisionReason") or "Blocked by a harness hook."
        )
        print(json.dumps({"decision": "block", "reason": reason}))
    elif stdout.strip():
        print(stdout.strip())
    return 0


def run(argv: list[str], /) -> int:
    options = {"--host": "", "--event": ""}
    position = 0
    while position < len(argv) and argv[position] in options:
        options[argv[position]] = argv[position + 1]
        position += 2
    host, event_name, script_args = (
        options["--host"],
        options["--event"],
        argv[position:],
    )

    event = json.loads(sys.stdin.read() or "{}")
    mapped = map_event(event, host, event_name)
    event_name = str(mapped.get("hook_event_name", ""))

    environment = dict(os.environ)
    environment.setdefault("CLAUDE_PLUGIN_ROOT", str(CHECKOUT))
    if mapped.get("cwd"):
        environment.setdefault("CLAUDE_PROJECT_DIR", str(mapped["cwd"]))

    uv = shutil.which("uv")
    runner = [uv, "run", "--script"] if uv else [sys.executable]
    done = subprocess.run(
        [*runner, *script_args],
        check=False,
        input=json.dumps(mapped),
        capture_output=True,
        text=True,
        env=environment,
        timeout=60,
    )
    if done.returncode == BLOCK_EXIT:
        print(done.stderr, end="", file=sys.stderr)
        return BLOCK_EXIT
    if done.returncode != 0:
        print(
            f"harness shim: hook exited {done.returncode}: {done.stderr.strip()[:300]}",
            file=sys.stderr,
        )
        return 0
    return (
        translate_kiro(done.stdout, done.stderr, event_name)
        if host == "kiro"
        else translate_cortex(done.stdout)
    )


def main() -> int:
    try:
        return run(sys.argv[1:])
    except Exception as error:
        print(f"harness shim: {type(error).__name__}: {error}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
