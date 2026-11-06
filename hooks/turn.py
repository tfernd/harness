#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""The main session's turn, in a project with `.harness.json`: `reset` at its start, `add` per call, `stop` at its end.

`turn.py reset` (UserPromptSubmit) empties the call count and saves a hash of each rule file. A task notification also
fires UserPromptSubmit (probed in a headless run); while a status is still due (a `deferred` mark exists), `reset` keeps the
count and the saved hashes, and so it does for any notification or sub-agent's message, which are not the owner's new turn. `turn.py add`
(PostToolUse on Agent, Task, Edit, Write) counts a call of the main session; a call that carries `agent_id` came from a
sub-agent. `turn.py stop` (Stop) holds the turn, up to MAX_BLOCKS times, on three checks:
  - a turn with `min_calls` calls or more ends with the headings, unless a background agent of the session still runs:
    then the turn is a progress note, the count is kept, and the status is due once the last agent has finished;
  - a closing Lessons section needs a rule file changed this turn: its hash now differs from the one saved at `reset` (contents only, no git); a section that
    defers its lessons fails the same way, and "Lessons: none" on a line of its own is the only way to have none. A rule
    file edited before the turn's start and committed in it is no change, since only contents are compared;
  - when RETRO_ITEMS items wait in the project's `harness-feedback/inbox.md` past `retro-mark`, and this session filed one, a retro is due: it needs a line for its key `retro-<items>` in
    `harness-feedback/handled.md`: `rule written in FILE`, where FILE exists and differs from its hash saved at `reset` (a file
    outside the project needs only to exist), or `rejected: REASON` of at least 3 words. Once MAX_BLOCKS blocks are spent, the ids still open are released: one warning lists them and they no longer hold this session.

`.harness.json` may set, under `stop`: `min_calls` (3), `headings`, `rule_paths` (files or folders whose change counts as
a rule change; relative to the project, or absolute for rules kept outside it, such as this plugin's own checkout). `.claude/worktrees/` is no rule
path.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

# HANDLED_NAME is the path of the handled file; HANDLED below is the pattern of its lines.
from common import FILE_EDGES, HANDLED as HANDLED_NAME, INBOX, RETRO_MARK, data_folder, find_project, get_unfenced_lines, has_project_file, write_atomic

MIN_CALLS = 3
HEADINGS = ("Verdict", "Done", "Needs you", "Next", "Lessons")
RULE_PATHS = ("AGENTS.md", "CLAUDE.md", ".claude", ".harness.json")
# The files in a rule folder that hold no rule.
NOT_RULES = frozenset({"settings.local.json"})
# The folders under a rule path that hold no rule.
NOT_RULE_FOLDERS = frozenset({"__pycache__", ".git"})
# Read by index: [0] is the folder that holds worktrees, [1] the worktrees folder skipped inside it.
WORKTREES = (".claude", "worktrees")
MAX_BLOCKS = 3
# The line that starts the Lessons section: a heading or a bold label, or a plain "Lessons:" label.
LESSONS = re.compile(r"^\s*((#+\s+|\*\*)Lessons?|Lessons?:)", re.I)
# "Lessons: none" on a line of its own, with the colon inside or outside the bold markers.
LESSONS_NONE = re.compile(r"^\s*(#+\s+)?\*{0,2}Lessons?\*{0,2}:\*{0,2}\s*none\b", re.I | re.M)
SECTION_END = re.compile(r"^(#+[ \t]|\s*\*\*[^*]+\*\*)")
# Words that put the lessons off to a later turn; a "unit" is one accepted piece of work, such as a worker's change.
DEFERS = re.compile(r"next unit|next turn|next session|will add|to be written|will be written", re.I)
# A tool id and the first status after it, which is its own notification's.
# A prompt the app sends, not the owner; the head alone is read, so a pasted one further down does not count.
APP_PROMPT = re.compile(r"<task-notification>|<agent-message ")
APP_PROMPT_HEAD = 600
NOTIFICATION = re.compile(r"<tool-use-id>([^<]+)</tool-use-id>[\s\S]*?<status>([^<]+)</status>")
FINISHED_STATUSES = frozenset({"completed", "failed", "killed", "stopped"})
HANDLED = re.compile(r"^(retro-[0-9]+|[0-9a-f]{8}): (?:rule written in[ \t]*(?P<file>\S*)|rejected:(?P<reason>.*))$", re.M)
MIN_REASON_WORDS = 3
# Inbox items waiting before a session that filed one owes a retro: often enough to act, rare enough to be read.
RETRO_ITEMS = 20
RETRO_KEY = re.compile(r"retro-([0-9]+)")
# A hook's refusal as a tool result; a failed command that only quotes the wording is no refusal.
REFUSAL = re.compile(r"PreToolUse:\w+ hook error:.*?Blocked by the harness", re.S)
ITEM_ID = re.compile(r"^- id=([0-9a-f]{8}) session=(\S+) ", re.M)


class StatePaths(NamedTuple):
    """A session's state files: its call count, its rule state at the turn's start, its blocks this turn."""

    calls: Path
    rules: Path
    blocks: Path


def get_state_paths(session: str, /) -> StatePaths:
    """The session's call count, its rule state at the turn's start, and its blocks this turn."""

    folder = data_folder() / "turns"
    folder.mkdir(exist_ok=True)

    return StatePaths(folder / f"{session}.calls", folder / f"{session}.rules", folder / f"{session}.blocks")


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
                event = json.loads(line)
            except ValueError:
                continue
            # A line that is valid JSON but no object (a number, a list) is skipped like a torn one.
            if isinstance(event, dict):
                lines.append(event)

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
                # A background launch is told by the text of its tool result, which is the host's wording, not a field.
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


def has_refusal(transcript: list[dict], /) -> bool:  # keys are data
    """Whether a hook refused a call since the owner's last prompt."""

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


def check_lessons(message: str, rules_path: Path, root: Path, config: dict, transcript: list[dict], /) -> list[str]:  # keys are data
    """A closing Lessons section needs a rule file changed this turn, unless its line says none."""

    section = get_lessons(message)
    none = LESSONS_NONE.search(section)
    if none:
        tail = section[none.end() :].split("\n")[0]
        if has_refusal(transcript) and len(tail.split()) < MIN_REASON_WORDS:
            return ['a call was refused this turn, so a bare "Lessons: none" does not hold: write the lesson, or say why it teaches nothing, as "Lessons: none: REASON"']
    if not section or none:
        return []
    # Skipped when no state was saved (no `reset` ran in this session), or when a rule file differs from it: that is the
    # change the lessons need.
    saved = get_saved_rules(rules_path)
    if saved is None or saved != get_rule_state(root, config):
        return []
    if DEFERS.search(section):
        return ["the Lessons section defers its lessons and no rule file changed this turn: write them now, then say so"]

    return [
        "the Lessons section has no change to show: no rule file changed this turn. Write each lesson into its file now, "
        'then say so; or write "Lessons: none" on a line of its own when no problem was met'
    ]


def get_saved_rules(rules_path: Path, /) -> dict | None:  # keys are data
    """The rule state saved at the turn's start, None when the file is missing, empty or not a JSON object."""

    try:
        saved = json.loads(rules_path.read_text())
    except (OSError, ValueError):
        return None

    return saved if isinstance(saved, dict) else None


def check_handled_file(name: str, root: Path, rules_path: Path, config: dict, /) -> str:  # keys are data
    """Why a `rule written in FILE` line does not count, or an empty string when FILE was written this turn."""

    if not name:
        return "it names no file after `rule written in`"
    path = Path(os.path.expanduser(name))
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_file():
        return f"{name} does not exist: write the rule into an existing file, then name it"
    if not path.is_relative_to(root):
        return ""
    # Skipped when no state was saved (no `reset` ran in this session): only the file's existence counts.
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
    """The ids the handled file closes, and the reason each id with a failing line is not closed."""

    handled: set[str]
    invalid: dict[str, str]  # keys are data


def get_handled(root: Path, rules_path: Path, config: dict, /) -> Handled:  # keys are data
    """The ids with a valid line in the handled file, and the reason the last line fails for each id with none."""

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
    """The most inbox items a retro key among `keys` covers, 0 with none."""

    return max((int(match.group(1)) for key in keys if (match := RETRO_KEY.fullmatch(key))), default=0)


def get_open_feedback(root: Path, session: str, released: set[str], handled: set[str], /) -> list[str]:
    """The retro key due now, when RETRO_ITEMS inbox items wait past the mark and this session filed one; else empty.

    A valid line for a key moves the mark. An item only ever waits for one retro, so nothing asks for a verdict per item.
    """

    inbox = root / INBOX
    if not inbox.exists():
        return []
    items = ITEM_ID.findall(inbox.read_text(errors="replace"))
    mark = root / RETRO_MARK
    text = mark.read_text().strip() if mark.exists() else ""
    # A mark past the inbox means the inbox was reset, and a line cannot cover items not yet filed.
    seen = int(text) if text.isdecimal() and text.isascii() and int(text) <= len(items) else 0
    closed = min(get_covered(handled), len(items))
    if closed > seen:
        write_atomic(mark, str(closed))
        seen = closed
    waiting = items[seen:]
    is_mine = any(owner == session for _, owner in waiting)
    if len(waiting) < RETRO_ITEMS or not is_mine or get_covered(released) > seen:
        return []

    return [f"retro-{len(items)}"]


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
            write_atomic(deferred_path, "1")
        elif missing:
            problems.append(
                f'the turn ran agents or edited files ({calls} calls), so the closing message needs the job status, as '
                f'"## NAME" lines: {"; ".join(missing)}'
            )
    released = set(released_path.read_text().split()) if released_path.exists() else set()
    handled: set[str] = set()
    invalid: dict[str, str] = {}
    open_ids: list[str] = []
    # Lessons and retros write rules into the repo's files, so they hold only a repo that opted in with its own file.
    if has_project_file(root):
        problems += check_lessons(message, rules_path, root, config, transcript)
        handled, invalid = get_handled(root, rules_path, config)
        open_ids = get_open_feedback(root, session, released, handled)
    # A retro may be the agent that runs: it is due again at the stop after the agents have finished.
    if open_ids and count_running_agents(transcript) > 0:
        open_ids = []
    if open_ids:
        problems.append(
            f"a retro is due: at least {RETRO_ITEMS} feedback items wait in {INBOX}. Run one `harness:analyst` on them, apply or reject its "
            f'proposals, then add "{open_ids[0]}: rule written in FILE" (FILE changed this turn) or "{open_ids[0]}: rejected: REASON" '
            f"(at least {MIN_REASON_WORDS} words) to {HANDLED_NAME}"
        )
    problems += [f"{item_id}: the line in {HANDLED_NAME} does not count, {invalid[item_id]}" for item_id in open_ids if item_id in invalid]
    # A write cut short leaves this empty, and an empty count must not drop the Stop checks.
    count = blocks_path.read_text().strip() if blocks_path.exists() else ""
    blocks = int(count) if count.isdecimal() and count.isascii() else 0
    if problems and blocks < MAX_BLOCKS:
        write_atomic(blocks_path, str(blocks + 1))
        listed = "\n".join(f"- {problem}" for problem in problems)
        print(json.dumps({"decision": "block", "reason": f"This turn ends with open checks:\n{listed}\nFix each, then stop."}))
        return 0
    if calls >= min_calls and not is_deferred:
        write_atomic(calls_path, "")
    if not is_deferred and deferred_path.exists():
        deferred_path.unlink()
    if open_ids:
        write_atomic(released_path, " ".join(sorted(released | set(open_ids))))
    write_atomic(blocks_path, "0")
    if problems:
        print(json.dumps({"systemMessage": f"The turn ends with open checks: {'; '.join(problems)}"}))

    return 0


def main() -> int:
    event = json.load(sys.stdin)
    root, config = find_project(event.get("cwd") or os.getcwd())
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    calls_path, rules_path, blocks_path = get_state_paths(event.get("session_id") or "unknown")
    if mode == "add":
        if not event.get("agent_id"):
            # One short append is not torn on Linux, so the counter needs no temporary file.
            with open(calls_path, "a") as file:
                file.write(f"{event.get('tool_name') or 'tool'}\n")
    elif mode == "reset":
        is_app_prompt = bool(APP_PROMPT.search(str(event.get("prompt") or "")[:APP_PROMPT_HEAD]))
        if not is_app_prompt and not get_state_path(event.get("session_id") or "unknown", "deferred").exists():
            write_atomic(calls_path, "")
            # Rule hashes serve only the lessons and retro checks of an opted-in project; elsewhere the walk could be huge.
            if has_project_file(root):
                write_atomic(rules_path, json.dumps(get_rule_state(root, config)))
        write_atomic(blocks_path, "0")
    elif mode == "stop":
        return stop(event, root, config)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # a bug in the gate must not trap the session
        print(f"the harness turn hook failed and let the call run: {error!r}", file=sys.stderr)
        sys.exit(1)
