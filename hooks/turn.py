#!/usr/bin/env -S python3 -I
"""The main session's turn, in a project with `.harness.json`: `reset` at its start, `add` per call, `stop` at its end.

`turn.py reset` (UserPromptSubmit) empties the call count and saves the state of the rule files. A task notification also
fires UserPromptSubmit (probed in a headless run), so a count left for a status that is still due is kept. `turn.py add`
(PostToolUse on Agent, Task, Edit, Write) counts a call of the main session; a call that carries `agent_id` came from a
sub-agent. `turn.py stop` (Stop) holds the turn, up to MAX_BLOCKS times, on three checks:
  - a turn with `min_calls` calls or more ends with the headings, unless a background agent of the session still runs:
    then the turn is a progress note, the count is kept, and the status is due once the last agent has finished;
  - a closing Lessons section needs a rule file changed this turn, against the state saved at its start; a section that
    defers its lessons fails the same way, and "Lessons: none" on a line of its own is the only way to have none. A rule
    file dirty at the turn's start and committed in it is no change;
  - each id this session filed in the project's `harness-feedback/inbox.md` needs a line in
    `harness-feedback/handled.md`. Once the blocks run out, its open ids stop holding this session, after one warning.

`.harness.json` may set, under `stop`: `min_calls` (3), `headings`, `rule_paths` (files or folders whose change counts as
a rule change; relative to the project, or absolute, as for this plugin's own checkout). `.claude/worktrees/` is no rule
path.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import HANDLED as HANDLED_NAME, INBOX, data_folder, find_project, get_unfenced_lines  # noqa: E402

MIN_CALLS = 3
HEADINGS = ("Verdict", "Done", "Needs you", "Next", "Lessons")
RULE_PATHS = ("AGENTS.md", "CLAUDE.md", ".claude", ".harness.json")
# The files in a rule folder that hold no rule.
NOT_RULES = {"settings.local.json"}
# The folders under a rule path that hold no rule.
NOT_RULE_FOLDERS = {"__pycache__", ".git"}
WORKTREES = (".claude", "worktrees")
MAX_BLOCKS = 3
# The line that starts the Lessons section: a heading or a bold label, or a plain "Lessons:" label.
LESSONS = re.compile(r"^\s*((#+\s+|\*\*)Lessons?|Lessons?:)", re.I)
# "Lessons: none" on a line of its own, with the colon inside or outside the bold markers.
LESSONS_NONE = re.compile(r"^\s*(#+\s+)?\*{0,2}Lessons?\*{0,2}:\*{0,2}\s*none\b", re.I | re.M)
SECTION_END = re.compile(r"^(#+[ \t]|\s*\*\*[^*]+\*\*)")
# Words that put the lessons off to a later turn.
DEFERS = re.compile(r"next unit|next turn|next session|will add|to be written|will be written", re.I)
# A tool id and the first status after it, which is its own notification's.
NOTIFICATION = re.compile(r"<tool-use-id>([^<]+)</tool-use-id>[\s\S]*?<status>([^<]+)</status>")
FINISHED_STATUSES = {"completed", "failed", "killed"}
HANDLED = re.compile(r"^([0-9a-f]{8}): (rule written in|rejected:)", re.M)
ITEM_ID = re.compile(r"^- id=([0-9a-f]{8}) session=(\S+) ", re.M)


def get_state_paths(session: str, /) -> tuple[Path, Path, Path]:
    """The session's call count, its rule state at the turn's start, and its blocks this turn."""

    folder = data_folder() / "turns"
    folder.mkdir(exist_ok=True)

    return folder / f"{session}.calls", folder / f"{session}.rules", folder / f"{session}.blocks"


def get_state_path(session: str, kind: str, /) -> Path:
    """A session's file of another kind: `deferred` marks a status still due, `released` lists the ids that stopped holding."""

    return data_folder() / "turns" / f"{session}.{kind}"


def get_rule_files(path: Path, /) -> list[Path]:
    """The rule files at a path: the file, or the files under the folder, past the folders that hold no rule."""

    if path.is_file():
        return [path]
    files: list[Path] = []
    for folder, names, file_names in os.walk(path):
        is_claude = Path(folder).name == WORKTREES[0]
        names[:] = [name for name in names if name not in NOT_RULE_FOLDERS and not (is_claude and name == WORKTREES[1])]
        files.extend(Path(folder) / name for name in file_names)

    return sorted(files)


def get_rule_state(root: Path, config: dict, /) -> dict[str, str]:  # keys are data
    """A hash of each rule file, whitespace removed, so a re-indent or a blank line is no change to a rule."""

    state: dict[str, str] = {}
    for name in config.get("stop", {}).get("rule_paths", RULE_PATHS):
        for file in get_rule_files((root / os.path.expanduser(name)).resolve()):
            if file.name not in NOT_RULES:
                state[str(file)] = hashlib.sha1(b"".join(file.read_bytes().split())).hexdigest()

    return state


def read_transcript(path: str, /) -> list[dict]:  # keys are data
    if not path or not os.path.isfile(path):
        return []
    lines = []
    with open(path, errors="replace") as file:
        for line in file:
            try:
                lines.append(json.loads(line))
            except ValueError:
                continue

    return lines


def get_user_text(line: dict, /) -> str:  # keys are data
    content = line.get("message", {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(block.get("text") or "" for block in content if isinstance(block, dict))

    return ""


def count_running_agents(transcript: list[dict], /) -> int:  # keys are data
    """The background Agent or Task calls with no final task notification yet."""

    launched: set[str] = set()
    finished: set[str] = set()
    for line in transcript:
        content = line.get("message", {}).get("content")
        blocks = content if isinstance(content, list) else []
        if line.get("type") == "assistant":
            for block in blocks:
                is_call = block.get("type") == "tool_use" and block.get("name") in ("Agent", "Task")
                if is_call and (block.get("input") or {}).get("run_in_background") is True:
                    launched.add(block.get("id"))
        elif line.get("type") == "user":
            for block in blocks:
                is_result = isinstance(block, dict) and block.get("type") == "tool_result"
                if is_result and "Async agent launched" in json.dumps(block.get("content")):
                    launched.add(block.get("tool_use_id"))
            found = NOTIFICATION.findall(get_user_text(line))
            finished.update(tool_id for tool_id, status in found if status in FINISHED_STATUSES)

    return len(launched - finished)


def get_closing_message(event: dict, transcript: list[dict], /) -> str:  # keys are data
    """The turn's closing message; a fenced block holds an example, not the turn's own headings."""

    message = event.get("last_assistant_message") or ""
    if not message:
        for line in transcript:
            content = line.get("message", {}).get("content")
            if line.get("type") == "assistant" and isinstance(content, list):
                texts = [block.get("text") for block in content if block.get("type") == "text" and block.get("text")]
                message = texts[-1] if texts else message

    return "\n".join(get_unfenced_lines(message))


def get_lessons(message: str, /) -> str:
    """The closing message from its Lessons line to the next heading or bold label line."""

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


def check_lessons(message: str, rules_path: Path, root: Path, config: dict, /) -> list[str]:  # keys are data
    """A closing Lessons section needs a rule file changed this turn, unless its line says none."""

    section = get_lessons(message)
    if not section or LESSONS_NONE.search(section):
        return []
    if not rules_path.exists() or json.loads(rules_path.read_text()) != get_rule_state(root, config):
        return []
    if DEFERS.search(section):
        return ["the Lessons section defers its lessons and no rule file changed this turn: write them now, then say so"]

    return [
        "the Lessons section has no change to show: no rule file changed this turn. Write each lesson into its file now, "
        'then say so; or write "Lessons: none" on a line of its own when no problem was met'
    ]


def get_open_feedback(root: Path, session: str, released: set[str], /) -> list[str]:
    """The ids this session filed in the inbox with no line in the handled file, past those already released."""

    inbox = root / INBOX
    if not inbox.exists():
        return []
    handled_path = root / HANDLED_NAME
    handled = {match.group(1) for match in HANDLED.finditer(handled_path.read_text())} if handled_path.exists() else set()
    ids = [item_id for item_id, owner in ITEM_ID.findall(inbox.read_text()) if owner == session]

    return [item_id for item_id in ids if item_id not in handled and item_id not in released]


def stop(event: dict, root: Path, config: dict, /) -> int:  # keys are data
    session = event.get("session_id") or "unknown"
    calls_path, rules_path, blocks_path = get_state_paths(session)
    deferred_path, released_path = get_state_path(session, "deferred"), get_state_path(session, "released")
    settings = config.get("stop", {})
    calls = len(calls_path.read_text().splitlines()) if calls_path.exists() else 0
    min_calls = settings.get("min_calls", MIN_CALLS)
    transcript = read_transcript(event.get("transcript_path") or "")
    message = get_closing_message(event, transcript)
    problems: list[str] = []
    is_deferred = False
    if calls >= min_calls:
        found = {line.strip() for line in message.splitlines()}
        missing = [name for name in settings.get("headings", HEADINGS) if f"## {name}" not in found]
        if missing and count_running_agents(transcript) > 0:
            is_deferred = True
            deferred_path.write_text("1")
        elif missing:
            problems.append(
                f'the turn ran agents or edited files ({calls} calls), so the closing message needs the job status, as '
                f'"## NAME" lines: {"; ".join(missing)}'
            )
    problems += check_lessons(message, rules_path, root, config)
    released = set(released_path.read_text().split()) if released_path.exists() else set()
    open_ids = get_open_feedback(root, session, released)
    if open_ids:
        problems.append(
            f"sub-agent feedback is unhandled, ids {' '.join(open_ids)} ({INBOX}): for each, have its rule, role, skill, hook "
            f'or gate written now, then add "<id>: rule written in FILE" or "<id>: rejected: REASON" to {HANDLED_NAME}'
        )
    blocks = int(blocks_path.read_text()) if blocks_path.exists() else 0
    if problems and blocks < MAX_BLOCKS:
        blocks_path.write_text(str(blocks + 1))
        listed = "\n".join(f"- {problem}" for problem in problems)
        print(json.dumps({"decision": "block", "reason": f"This turn ends with open checks:\n{listed}\nFix each, then stop."}))
        return 0
    if calls >= min_calls and not is_deferred:
        calls_path.write_text("")
    if not is_deferred and deferred_path.exists():
        deferred_path.unlink()
    if open_ids:
        released_path.write_text(" ".join(sorted(released | set(open_ids))))
    blocks_path.write_text("0")
    if problems:
        print(json.dumps({"systemMessage": f"The turn ends with open checks: {'; '.join(problems)}"}))

    return 0


def main() -> int:
    event = json.load(sys.stdin)
    root, config = find_project(event.get("cwd") or os.getcwd())
    if root is None:
        return 0
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    calls_path, rules_path, blocks_path = get_state_paths(event.get("session_id") or "unknown")
    if mode == "add":
        if not event.get("agent_id"):
            with open(calls_path, "a") as file:
                file.write(f"{event.get('tool_name') or 'tool'}\n")
    elif mode == "reset":
        if not get_state_path(event.get("session_id") or "unknown", "deferred").exists():
            calls_path.write_text("")
            rules_path.write_text(json.dumps(get_rule_state(root, config)))
        blocks_path.write_text("0")
    elif mode == "stop":
        return stop(event, root, config)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # a bug in the gate must not trap the session
        print(f"the harness turn hook failed and let the call run: {error!r}", file=sys.stderr)
        sys.exit(1)
