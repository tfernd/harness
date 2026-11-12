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
from typing import NamedTuple

from common import EDIT_TOOLS, data_folder, find_project, get_unfenced_lines, write_atomic
from skill_gate import get_written_project_files

MIN_CALLS = 3
HEADINGS = ("Verdict", "Done", "Needs you", "Next")
MAX_BLOCKS = 3
APP_PROMPT = re.compile(r"<task-notification>|<agent-message ")
APP_PROMPT_HEAD = 600
NOTIFICATION = re.compile(r"<tool-use-id>([^<]+)</tool-use-id>[\s\S]*?<status>([^<]+)</status>")
FINISHED_STATUSES = frozenset({"completed", "failed", "killed", "stopped"})
AGENT_TOOLS = frozenset({"Agent", "Task"})
AGENTS_HEADING = "## Agents"


class StatePaths(NamedTuple):

    calls: Path
    blocks: Path


def get_state_paths(session: str, /) -> StatePaths:

    folder = data_folder() / "turns"
    folder.mkdir(exist_ok=True)

    return StatePaths(folder / f"{session}.calls", folder / f"{session}.blocks")


def get_state_path(session: str, kind: str, /) -> Path:

    return data_folder() / "turns" / f"{session}.{kind}"


def read_transcript(path: str, /) -> list[dict]:
    if not path or not os.path.isfile(path):
        return []
    lines = []
    with open(path, errors="replace") as file:
        for line in file:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                lines.append(event)

    return lines


def get_user_text(line: dict, /) -> str:
    content = line.get("message", {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(block.get("text") or "" for block in content if isinstance(block, dict))

    return ""


def get_notice_text(line: dict, /) -> str:

    attachment = line.get("attachment")
    if line.get("type") == "attachment" and isinstance(attachment, dict) and isinstance(attachment.get("prompt"), str):
        return attachment["prompt"]
    if line.get("type") == "queue-operation" and isinstance(line.get("content"), str):
        return line["content"]

    return get_user_text(line) if line.get("type") == "user" else ""


def count_running_agents(transcript: list[dict], /) -> int:

    launched: set[str] = set()
    finished: set[str] = set()
    agent_calls: set[str] = set()
    for line in transcript:
        content = line.get("message", {}).get("content")
        blocks = content if isinstance(content, list) else []
        if line.get("type") == "assistant":
            for block in blocks:
                is_call = block.get("type") == "tool_use" and block.get("name") in AGENT_TOOLS
                if is_call:
                    agent_calls.add(block.get("id"))
                if is_call and (block.get("input") or {}).get("run_in_background") is True:
                    launched.add(block.get("id"))
        elif line.get("type") == "user":
            for block in blocks:
                is_result = isinstance(block, dict) and block.get("type") == "tool_result"
                if is_result and block.get("tool_use_id") in agent_calls and "Async agent launched" in json.dumps(block.get("content")):
                    launched.add(block.get("tool_use_id"))
        found = NOTIFICATION.findall(get_notice_text(line))
        finished.update(tool_id for tool_id, status in found if status in FINISHED_STATUSES)

    return len(launched - finished)


def get_closing_message(event: dict, transcript: list[dict], /) -> str:

    message = event.get("last_assistant_message") or ""
    if not message:
        for line in transcript:
            content = line.get("message", {}).get("content")
            if line.get("type") == "assistant" and isinstance(content, list):
                texts = [block.get("text") for block in content if block.get("type") == "text" and block.get("text")]
                message = texts[-1] if texts else message

    return "\n".join(get_unfenced_lines(message))


def get_agents_section(message: str, /) -> str:

    lines: list[str] = []
    is_inside = False
    for line in message.splitlines():
        if line.startswith("## "):
            is_inside = line.strip() == AGENTS_HEADING
        elif is_inside:
            lines.append(line)

    return "\n".join(lines)


def check_agents(message: str, call_lines: list[str], /) -> list[str]:

    agent_lines = [line.split("\t", 1) for line in call_lines if line.split("\t", 1)[0] in AGENT_TOOLS and "\t" in line]
    names = list(dict.fromkeys(parts[1] for parts in agent_lines))
    section = " ".join(get_agents_section(message).lower().split())
    missing = [name for name in names if name.lower() not in section]
    if not missing:
        return []

    return [
        f'the turn ran agents, so the status needs an "{AGENTS_HEADING}" section: one line per agent, starting with the description '
        f"it was given, then its verdict and what happened to its problems (fixed in FILE, rejected: why, or none). "
        f'Missing: {"; ".join(missing)}'
    ]


def stop(event: dict, root: Path, config: dict, /) -> int:
    session = event.get("session_id") or "unknown"
    calls_path, blocks_path = get_state_paths(session)
    deferred_path = get_state_path(session, "deferred")
    settings = config.get("stop", {})
    call_lines = calls_path.read_text().splitlines() if calls_path.exists() else []
    calls = len(call_lines)
    min_calls = settings.get("min_calls", MIN_CALLS)
    transcript = read_transcript(event.get("transcript_path") or "")
    message = get_closing_message(event, transcript)
    hard: list[str] = []
    soft: list[str] = []
    is_deferred = False
    if calls >= min_calls:
        found = {line.strip() for line in message.splitlines()}
        missing = [name for name in settings.get("headings", HEADINGS) if f"## {name}" not in found]
        if missing and count_running_agents(transcript) > 0:
            is_deferred = True
            write_atomic(deferred_path, "1")
        elif missing:
            hard.append(
                f'the turn ran agents or edited files ({calls} calls), so the closing message needs the job status, as '
                f'"## NAME" lines: {"; ".join(missing)}'
            )
        if not is_deferred:
            soft += check_agents(message, call_lines)
    count = blocks_path.read_text().strip() if blocks_path.exists() else ""
    blocks = int(count) if count.isdecimal() and count.isascii() else 0
    if hard and blocks < MAX_BLOCKS:
        write_atomic(blocks_path, str(blocks + 1))
        listed = "\n".join([*(f"- {problem}" for problem in hard), *(f"- note, does not hold the turn: {problem}" for problem in soft)])
        print(json.dumps({"decision": "block", "reason": f"This turn ends with open checks:\n{listed}\nFix each, then stop."}))
        return 0
    if calls >= min_calls and not is_deferred:
        write_atomic(calls_path, "")
    if not is_deferred and deferred_path.exists():
        deferred_path.unlink()
    write_atomic(blocks_path, "0")
    if hard:
        print(json.dumps({"systemMessage": f"The turn ends with open checks: {'; '.join([*hard, *soft])}"}))
    elif soft:
        print(json.dumps({"systemMessage": f"Note, the turn is not held: {'; '.join(soft)}"}))

    return 0


def get_call_line(event: dict, root: Path, cwd: str, /) -> str:

    name = event.get("tool_name") or "tool"
    tool_input = event.get("tool_input") or {}
    if name == "Bash":
        command = tool_input.get("command")
        written = get_written_project_files(command, root, cwd) if isinstance(command, str) else []

        return f"{name}\t{written[0]}" if written else ""
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if name in EDIT_TOOLS and isinstance(path, str) and path:
        return f"{name}\t{path}"
    description = tool_input.get("description")
    if name in AGENT_TOOLS and isinstance(description, str) and description.strip():
        return f"{name}\t{' '.join(description.split())}"

    return name


def main() -> int:
    event = json.load(sys.stdin)
    root, config = find_project(event.get("cwd") or os.getcwd())
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    calls_path, blocks_path = get_state_paths(event.get("session_id") or "unknown")
    if mode == "add":
        if not event.get("agent_id"):
            line = get_call_line(event, root, event.get("cwd") or os.getcwd())
            if line:
                with open(calls_path, "a") as file:
                    file.write(f"{line}\n")
    elif mode == "reset":
        is_app_prompt = bool(APP_PROMPT.search(str(event.get("prompt") or "")[:APP_PROMPT_HEAD]))
        if not is_app_prompt and not get_state_path(event.get("session_id") or "unknown", "deferred").exists():
            write_atomic(calls_path, "")
        write_atomic(blocks_path, "0")
    elif mode == "stop":
        return stop(event, root, config)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"the harness turn hook failed and let the call run: {error!r}", file=sys.stderr)
        sys.exit(1)
