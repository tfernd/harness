#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

from common import EDIT_TOOLS, EDITS_KIND, FILE_EDGES, HANDLED as HANDLED_NAME, INBOX, RETRO_MARK, data_folder, ensure_harness_folder, find_project, get_unfenced_lines, is_project_root, write_atomic

MIN_CALLS = 3
HEADINGS = ("Verdict", "Done", "Needs you", "Next", "Lessons")
RULE_PATHS = ("AGENTS.md", "CLAUDE.md", ".claude")
NOT_RULES = frozenset({"settings.local.json"})
NOT_RULE_FOLDERS = frozenset({"__pycache__", ".git"})
WORKTREES = (".claude", "worktrees")
MAX_BLOCKS = 3
LESSONS = re.compile(r"^\s*((#+\s+|\*\*)Lessons?|Lessons?:)", re.I)
LESSONS_NONE = re.compile(r"^\s*(#+\s+)?\*{0,2}Lessons?\*{0,2}:\*{0,2}\s*none\b", re.I | re.M)
SECTION_END = re.compile(r"^(#+[ \t]|\s*\*\*[^*]+\*\*)")
DEFERS = re.compile(r"next unit|next turn|next session|will add|to be written|will be written", re.I)
APP_PROMPT = re.compile(r"<task-notification>|<agent-message ")
APP_PROMPT_HEAD = 600
NOTIFICATION = re.compile(r"<tool-use-id>([^<]+)</tool-use-id>[\s\S]*?<status>([^<]+)</status>")
FINISHED_STATUSES = frozenset({"completed", "failed", "killed", "stopped"})
AGENT_TOOLS = frozenset({"Agent", "Task"})
AGENTS_HEADING = "## Agents"
HANDLED = re.compile(r"^(retro-[0-9]+|[0-9a-f]{8}): (?:rule written in[ \t]*(?P<file>\S*)|rejected:(?P<reason>.*))$", re.M)
MIN_REASON_WORDS = 3
RETRO_ITEMS = 20
RETRO_KEY = re.compile(r"retro-([0-9]+)")
REFUSAL = re.compile(r"PreToolUse:\w+ hook error:.*?Blocked by the harness", re.S)
ITEM_ID = re.compile(r"^- id=([0-9a-f]{8}) session=(\S+) ", re.M)


class StatePaths(NamedTuple):

    calls: Path
    rules: Path
    blocks: Path


def get_state_paths(session: str, /) -> StatePaths:

    folder = data_folder() / "turns"
    folder.mkdir(exist_ok=True)

    return StatePaths(folder / f"{session}.calls", folder / f"{session}.rules", folder / f"{session}.blocks")


def get_state_path(session: str, kind: str, /) -> Path:

    return data_folder() / "turns" / f"{session}.{kind}"


def get_rule_files(path: Path, /) -> list[Path]:

    if path.is_file():
        return [path]
    files: list[Path] = []
    for folder, names, file_names in os.walk(path):
        is_claude = Path(folder).name == WORKTREES[0]
        names[:] = [name for name in names if name not in NOT_RULE_FOLDERS and not (is_claude and name == WORKTREES[1])]
        files.extend(Path(folder) / name for name in file_names)

    return sorted(files)


def get_rule_state(root: Path, config: dict, /) -> dict[str, str]:

    state: dict[str, str] = {}
    for name in config.get("stop", {}).get("rule_paths", RULE_PATHS):
        for file in get_rule_files((root / os.path.expanduser(name)).resolve()):
            if file.name not in NOT_RULES:
                state[str(file)] = hashlib.sha1(b"".join(file.read_bytes().split())).hexdigest()

    return state


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
        f"it was given, then its verdict and what happened to its problems (fixed in FILE, filed, rejected: why, or none). "
        f'Missing: {"; ".join(missing)}'
    ]


def get_lessons(message: str, /) -> str:

    section: list[str] = []
    is_inside = False
    for line in message.splitlines():
        if LESSONS.match(line):
            is_inside = True
            section.append(line)
        elif SECTION_END.match(line):
            is_inside = False
        elif is_inside:
            section.append(line)

    return "\n".join(section)


def has_refusal(transcript: list[dict], /) -> bool:

    for line in reversed(transcript):
        if line.get("type") != "user":
            continue
        content = line.get("message", {}).get("content")
        blocks = content if isinstance(content, list) else []
        if any(isinstance(block, dict) and block.get("is_error") and REFUSAL.search(str(block.get("content"))) for block in blocks):
            return True
        text = get_user_text(line)
        if text.strip() and not APP_PROMPT.search(text[:APP_PROMPT_HEAD]):
            return False

    return False


def check_lessons(message: str, rules_path: Path, root: Path, config: dict, transcript: list[dict], /) -> list[str]:

    section = get_lessons(message)
    none = LESSONS_NONE.search(section)
    if none:
        tail = section[none.end() :].split("\n")[0]
        if has_refusal(transcript) and len(tail.split()) < MIN_REASON_WORDS:
            return ['a call was refused this turn, so a bare "Lessons: none" does not hold: write the lesson, or say why it teaches nothing, as "Lessons: none: REASON"']
    if not section or none:
        return []
    saved = get_saved_rules(rules_path)
    if saved is None or saved != get_rule_state(root, config):
        return []
    if DEFERS.search(section):
        return ["the Lessons section defers its lessons and no rule file changed this turn: write them now, then say so"]

    return [
        "the Lessons section has no change to show: no rule file changed this turn. Write each lesson into its file now, "
        'then say so; or write "Lessons: none" on a line of its own when no problem was met'
    ]


def get_saved_rules(rules_path: Path, /) -> dict | None:

    try:
        saved = json.loads(rules_path.read_text())
    except (OSError, ValueError):
        return None

    return saved if isinstance(saved, dict) else None


def check_handled_file(name: str, root: Path, rules_path: Path, config: dict, /) -> str:

    if not name:
        return "it names no file after `rule written in`"
    path = Path(os.path.expanduser(name))
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_file():
        return f"{name} does not exist: write the rule into an existing file, then name it"
    if not path.is_relative_to(root):
        return ""
    saved = get_saved_rules(rules_path)
    if saved is None:
        return ""
    state = get_rule_state(root, config)
    if str(path) not in state:
        return f"{name} is no rule file (not under rule_paths): name the rule file that changed"
    if saved.get(str(path)) == state[str(path)]:
        return f"{name} was not changed this turn (same content as at the turn's start): write the rule into it"

    return ""


class Handled(NamedTuple):

    handled: set[str]
    invalid: dict[str, str]


def get_handled(root: Path, rules_path: Path, config: dict, /) -> Handled:

    path = root / HANDLED_NAME
    handled: set[str] = set()
    invalid: dict[str, str] = {}
    reason_owners: dict[str, str] = {}
    for match in HANDLED.finditer(path.read_text(errors="replace") if path.exists() else ""):
        item_id, name, reason = match.group(1), match.group("file"), match.group("reason")
        if name is None:
            is_short = len(reason.split()) < MIN_REASON_WORDS
            owner = reason_owners.setdefault(" ".join(reason.lower().split()), item_id)
            if is_short:
                problem = f"rejected needs a reason of at least {MIN_REASON_WORDS} words"
            else:
                problem = f"the same reason already closes {owner}: a reason that fits two items fits neither, so say why this one" if owner != item_id else ""
        else:
            problem = check_handled_file(name.strip(FILE_EDGES), root, rules_path, config)
        if problem:
            invalid[item_id] = problem
        else:
            handled.add(item_id)

    return Handled(handled, {item_id: why for item_id, why in invalid.items() if item_id not in handled})


def get_covered(keys: set[str], /) -> int:

    return max((int(match.group(1)) for key in keys if (match := RETRO_KEY.fullmatch(key))), default=0)


def get_open_feedback(root: Path, session: str, released: set[str], handled: set[str], /) -> list[str]:

    inbox = root / INBOX
    if not inbox.exists():
        return []
    items = ITEM_ID.findall(inbox.read_text(errors="replace"))
    mark = root / RETRO_MARK
    text = mark.read_text().strip() if mark.exists() else ""
    seen = int(text) if text.isdecimal() and text.isascii() and int(text) <= len(items) else 0
    closed = min(get_covered(handled), len(items))
    if closed > seen:
        ensure_harness_folder(root)
        write_atomic(mark, str(closed))
        seen = closed
    waiting = items[seen:]
    is_mine = any(owner == session for _, owner in waiting)
    if len(waiting) < RETRO_ITEMS or not is_mine or get_covered(released) > seen:
        return []

    return [f"retro-{len(items)}"]


def stop(event: dict, root: Path, config: dict, /) -> int:
    session = event.get("session_id") or "unknown"
    calls_path, rules_path, blocks_path = get_state_paths(session)
    deferred_path, released_path = get_state_path(session, "deferred"), get_state_path(session, "released")
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
    released = set(released_path.read_text().split()) if released_path.exists() else set()
    handled: set[str] = set()
    invalid: dict[str, str] = {}
    open_ids: list[str] = []
    if is_project_root(root):
        soft += check_lessons(message, rules_path, root, config, transcript)
        handled, invalid = get_handled(root, rules_path, config)
        open_ids = get_open_feedback(root, session, released, handled)
    if open_ids and count_running_agents(transcript) > 0:
        open_ids = []
    if open_ids:
        hard.append(
            f"a retro is due: at least {RETRO_ITEMS} feedback items wait in {INBOX}. Run one `harness:analyst` on them, apply or reject its "
            f'proposals, then add "{open_ids[0]}: rule written in FILE" (FILE changed this turn) or "{open_ids[0]}: rejected: REASON" '
            f"(at least {MIN_REASON_WORDS} words) to {HANDLED_NAME}"
        )
    hard += [f"{item_id}: the line in {HANDLED_NAME} does not count, {invalid[item_id]}" for item_id in open_ids if item_id in invalid]
    count = blocks_path.read_text().strip() if blocks_path.exists() else ""
    blocks = int(count) if count.isdecimal() and count.isascii() else 0
    if hard and blocks < MAX_BLOCKS:
        write_atomic(blocks_path, str(blocks + 1))
        listed = "\n".join([*(f"- {problem}" for problem in hard), *(f"- note, does not hold the turn: {problem}" for problem in soft)])
        print(json.dumps({"decision": "block", "reason": f"This turn ends with open checks:\n{listed}\nFix each, then stop."}))
        return 0
    if calls >= min_calls and not is_deferred:
        write_atomic(calls_path, "")
        write_atomic(get_state_path(session, EDITS_KIND), "")
    if not is_deferred and deferred_path.exists():
        deferred_path.unlink()
    if open_ids:
        write_atomic(released_path, " ".join(sorted(released | set(open_ids))))
    write_atomic(blocks_path, "0")
    if hard:
        print(json.dumps({"systemMessage": f"The turn ends with open checks: {'; '.join([*hard, *soft])}"}))
    elif soft:
        print(json.dumps({"systemMessage": f"Note, the turn is not held: {'; '.join(soft)}"}))

    return 0


def get_call_line(event: dict, /) -> str:

    name = event.get("tool_name") or "tool"
    tool_input = event.get("tool_input") or {}
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
    calls_path, rules_path, blocks_path = get_state_paths(event.get("session_id") or "unknown")
    if mode == "add":
        if not event.get("agent_id"):
            with open(calls_path, "a") as file:
                file.write(f"{get_call_line(event)}\n")
    elif mode == "reset":
        is_app_prompt = bool(APP_PROMPT.search(str(event.get("prompt") or "")[:APP_PROMPT_HEAD]))
        if not is_app_prompt:
            write_atomic(get_state_path(event.get("session_id") or "unknown", EDITS_KIND), "")
        if not is_app_prompt and not get_state_path(event.get("session_id") or "unknown", "deferred").exists():
            write_atomic(calls_path, "")
            if is_project_root(root):
                write_atomic(rules_path, json.dumps(get_rule_state(root, config)))
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
