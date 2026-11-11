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
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from common import HANDBACK_TOOL, PLUGIN_PREFIX, data_folder, find_project, get_turns, make_note_output, read_tail, write_atomic

STOP_TOOLS = ("TaskStop", "KillShell")
TAIL_BYTES = 262144
DEFAULT_PROGRESS_EVERY = 10
SUMMARY_CHARS = 80
SHORT_ID_CHARS = 6
PROGRESS_READ_BYTES = 65536
PROGRESS_SHOWN = 4
SUMMARY_KEYS = ("command", "file_path", "notebook_path", "path", "pattern", "description", "prompt", "url", "query")
PROGRESS_KEEP_DAYS = 7
SECONDS_PER_DAY = 86400


def get_agent_path(event: dict, /) -> Path | None:

    given = event.get("agent_transcript_path") or ""
    if os.path.isfile(given):
        return Path(given)
    session = event.get("transcript_path") or ""
    agent_id = event.get("agent_id") or ""
    if not session or not agent_id:
        return None
    path = Path(session).with_suffix("") / "subagents" / f"agent-{agent_id}.jsonl"

    return path if path.is_file() else None


def get_progress_every(config: dict, /) -> int:

    every = config.get("progress", {}).get("every", DEFAULT_PROGRESS_EVERY)
    if isinstance(every, bool) or not isinstance(every, (int, float)) or every < 1:
        return 0

    return int(every)


def get_progress_paths(event: dict, /) -> tuple[Path, Path] | None:

    session = event.get("session_id") or Path(event.get("transcript_path") or "").stem
    name = re.sub(r"[^A-Za-z0-9_-]", "", str(session))[:80]
    if not name:
        return None
    folder = data_folder() / "progress"

    return folder / f"{name}.jsonl", folder / f"{name}.offset"


def get_input_summary(tool_input: object, /) -> str:

    if isinstance(tool_input, dict):
        text = next((str(tool_input[key]) for key in SUMMARY_KEYS if tool_input.get(key)), json.dumps(tool_input))
    else:
        text = str(tool_input or "")

    return " ".join(text.split())[:SUMMARY_CHARS]


def prune_progress(folder: Path, /) -> None:

    cutoff = time.time() - PROGRESS_KEEP_DAYS * SECONDS_PER_DAY
    try:
        for path in folder.iterdir():
            if path.suffix in (".jsonl", ".offset", ".turns") and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
    except OSError:
        pass


def write_progress(event: dict, num_turns: int, /) -> None:

    paths = get_progress_paths(event)
    if paths is None:
        return
    line = {
        "time": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "agent_id": event.get("agent_id"),
        "agent_type": event.get("agent_type") or "",
        "calls": num_turns,
        "tool": event.get("tool_name") or "",
        "summary": get_input_summary(event.get("tool_input")),
    }
    paths[0].parent.mkdir(parents=True, exist_ok=True)
    prune_progress(paths[0].parent)
    with open(paths[0], "a") as file:
        file.write(json.dumps(line) + "\n")


def read_new_progress(event: dict, /) -> list[dict]:

    paths = get_progress_paths(event)
    if paths is None or not paths[0].is_file():
        return []
    try:
        offset = int(paths[1].read_text())
    except (OSError, ValueError):
        offset = 0
    with open(paths[0], "rb") as file:
        size = file.seek(0, os.SEEK_END)
        offset = offset if 0 <= offset <= size else 0
        file.seek(offset)
        chunk = file.read(PROGRESS_READ_BYTES)
    end = chunk.rfind(b"\n") + 1
    consumed = end or (len(chunk) if len(chunk) == PROGRESS_READ_BYTES else 0)
    if consumed:
        write_atomic(paths[1], str(offset + consumed))
    lines: list[dict] = []
    for text in chunk[:end].decode(errors="replace").splitlines():
        try:
            line = json.loads(text)
        except ValueError:
            continue
        if isinstance(line, dict):
            lines.append(line)

    return lines


def get_progress_text(lines: list[dict], /) -> str:

    latest = {str(line.get("agent_id")): line for line in lines}
    parts = []
    for agent_id, line in list(latest.items())[-PROGRESS_SHOWN:]:
        role = str(line.get("agent_type") or "agent").removeprefix(PLUGIN_PREFIX)
        parts.append(f"{role} {agent_id[:SHORT_ID_CHARS]} at {line.get('calls')} turns, last: {line.get('tool')} {line.get('summary')}".rstrip())

    return f"Agent progress: {'; '.join(parts)}" if parts else ""


class TurnCount(NamedTuple):

    count: int
    last: list[dict]


def fold_turns(events: list[dict], count: int, last_id: str | None, /) -> tuple[int, str | None]:

    for event in events:
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        has_call = isinstance(content, list) and any(isinstance(block, dict) and block.get("type") == "tool_use" for block in content)
        if event.get("type") != "assistant" or not has_call:
            continue
        message_id = message.get("id")
        if not (message_id and message_id == last_id):
            count += 1
        last_id = message_id

    return count, last_id


def parse_lines(data: bytes, /) -> list[dict]:

    events: list[dict] = []
    for line in data.decode(errors="replace").split("\n"):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)

    return events


def count_turns(path: Path, agent_id: str, /) -> TurnCount:

    name = re.sub(r"[^A-Za-z0-9_-]", "", agent_id)[:80]
    state_path = data_folder() / "budget" / f"{name}.turns" if name else None
    offset, count, last_id = 0, 0, None
    if state_path is not None and state_path.is_file():
        try:
            saved = json.loads(state_path.read_text())
            offset, count, last_id = int(saved["offset"]), int(saved["count"]), saved["last_id"]
        except (OSError, ValueError, KeyError, TypeError):
            offset, count, last_id = 0, 0, None
    with open(path, "rb") as file:
        size = file.seek(0, os.SEEK_END)
        if not 0 <= offset <= size:
            offset, count, last_id = 0, 0, None
        file.seek(offset)
        chunk = file.read()
    end = chunk.rfind(b"\n") + 1
    count, last_id = fold_turns(parse_lines(chunk[:end]), count, last_id)
    if state_path is not None and end:
        state_path.parent.mkdir(exist_ok=True)
        if not state_path.exists():
            prune_progress(state_path.parent)
        write_atomic(state_path, json.dumps({"offset": offset + end, "count": count, "last_id": last_id}))
    count, _ = fold_turns(parse_lines(chunk[end:]), count, last_id)
    latest = get_turns(parse_lines(read_tail(path, TAIL_BYTES)))

    return TurnCount(count, latest[-1] if latest else [])


def main() -> int:
    event = json.load(sys.stdin)
    if not event.get("agent_id"):
        note = get_progress_text(read_new_progress(event))
        if note:
            print(json.dumps(make_note_output(note)))
        return 0
    if event.get("tool_name") in (HANDBACK_TOOL, *STOP_TOOLS):
        return 0
    _, config = find_project(event.get("cwd") or os.getcwd())
    every = get_progress_every(config)
    path = get_agent_path(event)
    if path is None or not every:
        return 0
    turns = count_turns(path, str(event.get("agent_id")))
    call_id = event.get("tool_use_id")
    is_written = not call_id or any(call.get("id") == call_id for call in turns.last)
    num_turns = turns.count + (not is_written)
    is_first = not call_id or not is_written or turns.last[0].get("id") == call_id
    if num_turns % every == 0 and is_first:
        write_progress(event, num_turns)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"the harness progress note failed and let the call run: {error!r}", file=sys.stderr)
        sys.exit(1)
