#!/usr/bin/env -S python3 -I
"""SubagentStop hook: in a project with `.harness.json`, a harness role stops only with a report in the `report` skill's
form, whose claims its own transcript backs.

The headings come first, each once and in order; then each section has the body the skill gives it. `worker`, `reviewer`
and `auditor` owe the full form; `scout`, `runner` and `cold-reader` the short form. They count with or without the
`harness:` prefix; every other agent type is not judged. The report is the agent's last block, handback or text, holding
`## Answer`, else its last message.

The claims come from the agent's transcript, never from git, since parallel agents share a tree: each file it changed
through Edit, Write or NotebookEdit is named in the report by its absolute or project-relative path (`guard.scratch` is
exempt), an `exit <N>` needs a Bash call, and a READ `path:line` names an existing file with that many lines.

A bad report goes back to the agent, up to MAX_SEND_BACKS times; then the agent may stop and the orchestrator is warned.
Once it stops, one row goes to `ledger.jsonl` in the plugin's data folder, and each item of FEEDBACK FOR THE ORCHESTRATOR
goes to the project's `harness-feedback/inbox.md`, where the Stop hook (`turn.py`) holds its session's turn until each is
handled.

`.harness.json` may set, under `report`: `short` and `full` (more roles owing that form), `causes` (more causes a problem
may name).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from budget import get_agent_path, get_duration  # noqa: E402
from common import INBOX, PLUGIN_PREFIX, data_folder, find_project, get_report_form, get_scratch, get_unfenced_lines  # noqa: E402

FULL = (
    "Answer",
    "Work",
    "NOT CHECKED",
    "OUTSIDE",
    "DECIDE",
    "PROBLEMS MET",
    "COMPLIANCE",
    "LEARNED",
    "REPORT CARD",
    "FEEDBACK FOR THE ORCHESTRATOR",
)
SHORT = ("Answer", "Work", "NOT CHECKED", "PROBLEMS MET", "REPORT CARD")
REQUIRED = {"full": FULL, "short": SHORT}
# The sections where "none" is not an answer.
NEVER_NONE = {"Answer", "Work", "PROBLEMS MET", "COMPLIANCE", "LEARNED", "REPORT CARD"}
NO_PLACEHOLDER = {"Answer", "Work", "COMPLIANCE"}
PLACEHOLDER = re.compile(r"\b(pending|tbd|not yet known)\b", re.I)
CAUSES = ("brief", "tool", "rule", "environment", "other agent", "the agent itself")
CLOSING_TAGS = re.compile(r"(</[A-Za-z][A-Za-z0-9_-]*>|\s)*$")
EXIT_CODE = re.compile(r"exit\s+[0-9]+", re.I)
ANSWER_HEADING = re.compile(r"^## Answer\s*$", re.M)
READ_CLAIM = re.compile(r"READ `([^`:]+):([0-9]+)(?:-([0-9]+))?`")
EDIT_TOOLS = {"Edit", "Write", "NotebookEdit"}
# What a FEEDBACK item says when it holds no feedback.
NO_FEEDBACK = re.compile(r"(none|none needed|no feedback|n/?a)[ .]*", re.I)
NO_GATE = re.compile(r"no gates? (was |were )?applied", re.I)
SCORE = re.compile(r"^[1-5](/5)?$")
SCORES = ("Task", "Brief", "Ease")
WHAT_LABEL = "What would have helped"
HOW_LABEL = "How I would do it again"
MAX_SEND_BACKS = 3


def read_sections(report: str, /) -> list[tuple[str, list[str]]]:
    """The `## ` sections in order, each with its non-blank lines; a fenced block is an example, so holds no heading."""

    sections: list[tuple[str, list[str]]] = []
    for line in get_unfenced_lines(report):
        if line.startswith("## "):
            sections.append((line[3:].strip(), []))
        elif sections and line.strip():
            sections[-1][1].append(line)

    return sections


def get_items(lines: list[str], /) -> list[str]:
    """One string per item: a bullet or an unindented line; indented continuation lines join their item."""

    items: list[str] = []
    for line in lines:
        if line.startswith("- ") or not line[0].isspace() or not items:
            items.append(line)
        else:
            items[-1] += " " + line.strip()

    return items


def item_text(item: str, /) -> str:
    """An item without its bullet, trailing closing tags and trailing blanks."""

    return CLOSING_TAGS.sub("", re.sub(r"^- +", "", item))


def is_none(lines: list[str], /) -> bool:
    return item_text(" ".join(lines)).rstrip(" .").lower() == "none"


def check_headings(sections: list[tuple[str, list[str]]], required: tuple[str, ...], /) -> list[str]:
    """Each required heading once, and in order."""

    names = [name for name, _ in sections]
    problems: list[str] = []
    last = -1
    for heading in required:
        if heading not in names:
            problems.append(f"missing: {heading}")
            continue
        if names.count(heading) > 1:
            problems.append(f"duplicated: {heading}")
        index = names.index(heading)
        if index < last:
            problems.append(f"out of order: {heading}")
        else:
            last = index

    return problems


def check_problems(lines: list[str], cause_pattern: re.Pattern[str], /) -> list[str]:
    """Each PROBLEMS MET item names a cause from the list, or one line says no problem was met."""

    if len(lines) == 1 and re.match(r"(- +)?no problem met", lines[0]):
        return []

    return [
        f"PROBLEMS MET item names no cause from the skill's list: {item[:70]}"
        for item in get_items(lines)
        if not cause_pattern.search(item)
    ]


def check_compliance(lines: list[str], /) -> list[str]:
    text = "\n".join(lines)
    if EXIT_CODE.search(text) or NO_GATE.search(text):
        return []

    return ["COMPLIANCE names no gate with an exit code and does not say no gate applied"]


def get_scores(lines: list[str], /) -> dict[str, str]:  # keys are data
    """The Value cell of each table row, by the row's name."""

    scores: dict[str, str] = {}
    for line in lines:
        if line.lstrip().startswith("|"):
            cells = [cell.strip() for cell in line.split("|")]
            if len(cells) > 2:
                scores.setdefault(cells[1], cells[2])

    return scores


def find_label(lines: list[str], label: str, /) -> tuple[int, str]:
    """The index of the first line starting with a label, bold or not, and the text after the label; (-1, "") if none."""

    pattern = re.compile(rf"^\s*\*{{0,2}}{label}:?\*{{0,2}}:?\s*(.*)")
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if match:
            return index, match.group(1).strip()

    return -1, ""


def check_report_card(lines: list[str], /) -> list[str]:
    """A Value 1 to 5 for Task, Brief and Ease, then the two labelled lines in order."""

    problems: list[str] = []
    scores = get_scores(lines)
    for name in SCORES:
        if name not in scores:
            problems.append(f"REPORT CARD has no {name} row")
        elif not SCORE.match(scores[name]):
            problems.append(f"REPORT CARD {name} value is '{scores[name]}', not an integer 1 to 5")
    rows = [index for index, line in enumerate(lines) if line.lstrip().startswith("|")]
    what_line, what_text = find_label(lines, WHAT_LABEL)
    how_line, how_text = find_label(lines, HOW_LABEL)
    for label, line, text in ((WHAT_LABEL, what_line, what_text), (HOW_LABEL, how_line, how_text)):
        if line < 0:
            problems.append(f'REPORT CARD has no "{label}" line')
        elif not text:
            problems.append(f'REPORT CARD "{label}" has no text')
    if what_line >= 0 and rows and what_line < rows[-1]:
        problems.append("REPORT CARD lines must follow the table")
    if what_line >= 0 and 0 <= how_line < what_line:
        problems.append(f'REPORT CARD "{HOW_LABEL}" must follow "{WHAT_LABEL}"')

    return problems


def check_report(report: str, required: tuple[str, ...], cause_pattern: re.Pattern[str], /) -> list[str]:
    """Every way a report breaks its form."""

    sections = read_sections(report)
    problems = check_headings(sections, required)
    bodies = dict(reversed(sections))
    for heading in required:
        if heading not in bodies:
            continue
        lines = bodies[heading]
        if not lines:
            problems.append(f"{heading} is empty")
            continue
        if heading in NEVER_NONE and is_none(lines):
            problems.append(f"{heading} says none; it says what it checked or met")
            continue
        if heading in NO_PLACEHOLDER and PLACEHOLDER.search("\n".join(lines)):
            problems.append(f"{heading} holds placeholder text (pending, TBD or not yet known)")
        if heading == "COMPLIANCE":
            problems += check_compliance(lines)
        elif heading == "PROBLEMS MET":
            problems += check_problems(lines, cause_pattern)
        elif heading == "REPORT CARD":
            problems += check_report_card(lines)

    return problems


def read_assistant_blocks(path: str, /) -> tuple[list[dict], set[str]]:  # keys are data
    """The content blocks of a transcript's assistant lines, and the ids of the tool calls whose result was an error."""

    blocks: list[dict] = []
    failed: set[str] = set()
    with open(path, errors="replace") as file:
        for line in file:
            try:
                entry = json.loads(line)
                content = entry.get("message", {}).get("content")
            except (ValueError, AttributeError):
                continue
            for block in content if isinstance(content, list) else ():
                if not isinstance(block, dict):
                    continue
                if entry.get("type") == "assistant":
                    blocks.append(block)
                elif entry.get("type") == "user" and block.get("type") == "tool_result" and block.get("is_error"):
                    failed.add(block.get("tool_use_id"))

    return blocks, failed


def get_report(event: dict, blocks: list[dict], /) -> str:  # keys are data
    """The agent's last block, handback or text, holding `## Answer`, else its last message. User lines never count."""

    last = event.get("last_assistant_message") or ""
    if ANSWER_HEADING.search(last):
        return last
    report = ""
    for block in blocks:
        is_handback = block.get("type") == "tool_use" and block.get("name") == "SubagentHandback"
        text = (block.get("input") or {}).get("message") if is_handback else block.get("text")
        if isinstance(text, str) and ANSWER_HEADING.search(text):
            report = text

    return report or last


def get_changed_files(blocks: list[dict], failed: set[str], cwd: str, /) -> list[str]:  # keys are data
    """The resolved paths the agent changed through the edit tools; a call whose result was an error changed nothing."""

    paths: set[str] = set()
    for block in blocks:
        if block.get("type") == "tool_use" and block.get("name") in EDIT_TOOLS and block.get("id") not in failed:
            tool_input = block.get("input") or {}
            path = tool_input.get("file_path") or tool_input.get("notebook_path")
            if path:
                paths.add(os.path.realpath(os.path.join(cwd, path)))

    return sorted(paths)


def is_named(path: str, report: str, folders: tuple[str, ...], /) -> bool:
    """Whether a report holds a path whole: absolute, or relative to one of the folders (`./` allowed)."""

    spellings = [path, *(os.path.relpath(path, folder) for folder in folders if path.startswith(folder + os.sep))]
    pattern = "|".join(re.escape(spelling) for spelling in spellings)

    return re.search(rf"(?<![\w./-])(?:\./)?(?:{pattern})(?![\w/-]|\.\w)", report) is not None


def check_read_claims(report: str, root: str, /) -> list[str]:
    """Each READ `path:line` names an existing file with at least that many lines; `path:a-b` checks `b`."""

    problems: list[str] = []
    for path, first, last in READ_CLAIM.findall(report):
        full = os.path.join(root, os.path.expanduser(path))
        if not os.path.isfile(full):
            problems.append(f"READ names a file that does not exist: {path}")
            continue
        with open(full, "rb") as file:
            count = sum(1 for _ in file)
        line = int(last or first)
        if line > count:
            problems.append(f"READ {path}:{line} is past the end of the file, which has {count} lines")

    return problems


def check_claims(report: str, event: dict, root: str, scratch: str, blocks: list[dict], failed: set[str], /) -> list[str]:  # keys are data
    """What the report claims against what its transcript shows; no transcript leaves only the READ claims."""

    problems = check_read_claims(report, root)
    if not os.path.isfile(event.get("agent_transcript_path") or ""):
        return problems
    cwd = event.get("cwd") or root
    folders = (root, os.path.realpath(cwd))
    for path in get_changed_files(blocks, failed, cwd):
        is_exempt = scratch and (path == scratch or path.startswith(scratch + os.sep))
        if not is_exempt and not is_named(path, report, folders):
            problems.append(f"the report does not name a file the agent changed: {path}")
    has_bash = any(block.get("type") == "tool_use" and block.get("name") == "Bash" for block in blocks)
    if EXIT_CODE.search(report) and not has_bash:
        problems.append("the report claims an exit code, and the transcript holds no Bash call")

    return problems


def get_feedback(report: str, /) -> list[str]:
    """The items of FEEDBACK FOR THE ORCHESTRATOR that are not "none"."""

    lines = dict(reversed(read_sections(report))).get("FEEDBACK FOR THE ORCHESTRATOR", [])
    texts = [item_text(item) for item in get_items(lines)]

    return [text for text in texts if text and not NO_FEEDBACK.fullmatch(text)]


def file_feedback(root: str, session: str, role: str, items: list[str], /) -> list[str]:
    """Appends each item new to this session to the project's inbox; returns the ids of all the items."""

    inbox = os.path.join(root, INBOX)
    known = open(inbox, errors="replace").read() if os.path.exists(inbox) else ""
    ids = []
    for text in items:
        item_id = hashlib.sha1(text.encode()).hexdigest()[:8]
        ids.append(item_id)
        if f"id={item_id} session={session} " not in known:
            os.makedirs(os.path.dirname(inbox), exist_ok=True)
            with open(inbox, "a") as file:
                file.write(f"- id={item_id} session={session} agent={role} {text}\n")

    return ids


def write_ledger(event: dict, root: str, role: str, report: str, send_backs: int, problems: list[str], ids: list[str], /) -> None:  # keys are data
    """Appends one row for the stopped agent to the plugin's ledger, which the `retro` skill reads."""

    sections = dict(reversed(read_sections(report)))
    scores = get_scores(sections.get("REPORT CARD", []))
    causes = re.findall(rf"cause:\s*({'|'.join(CAUSES)}|[^;)|]+)", "\n".join(sections.get("PROBLEMS MET", [])), re.I)
    try:
        duration = get_duration(get_agent_path(event))
    except (OSError, ValueError, AttributeError):
        duration = None
    row = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "project": root,
        "session": event.get("session_id"),
        "agent_id": event.get("agent_id"),
        "role": role,
        "accepted": not problems,
        "send_backs": send_backs,
        "duration_s": duration,
        "open_problems": problems,
        "scores": {name: scores.get(name) for name in SCORES},
        "causes": [cause.strip().lower() for cause in causes],
        "feedback_ids": ids,
        "report": report,
    }
    with open(data_folder() / "ledger.jsonl", "a") as file:
        file.write(json.dumps(row) + "\n")


def get_send_backs_path(event: dict, /) -> Path:  # keys are data
    """The file counting how many times this agent has been sent back."""

    folder = data_folder() / "send-backs"
    folder.mkdir(exist_ok=True)

    return folder / f"{event.get('agent_id') or 'unknown'}.count"


def get_send_backs(event: dict, /) -> int:  # keys are data
    path = get_send_backs_path(event)

    return int(path.read_text()) if path.exists() else 0


def finish(event: dict, root: str, role: str, report: str, problems: list[str], /) -> None:  # keys are data
    """The agent stops: its feedback and its ledger row are filed, and its send-back count is dropped."""

    path = get_send_backs_path(event)
    send_backs = get_send_backs(event)
    if path.exists():
        path.unlink()
    session = event.get("session_id") or "unknown"
    write_ledger(event, root, role, report, send_backs, problems, file_feedback(root, session, role, get_feedback(report)))


def main() -> int:
    event = json.load(sys.stdin)
    root, config = find_project(event.get("cwd") or os.getcwd())
    settings = config.get("report", {})
    name = (event.get("agent_type") or "").removeprefix(PLUGIN_PREFIX)
    form = get_report_form(name, settings)
    if root is None or not form:
        return 0
    required = REQUIRED[form]
    # A cause followed by " |" is the form's own list, copied and not chosen, so it does not count.
    causes = "|".join(re.escape(cause) for cause in (*CAUSES, *settings.get("causes", ())))
    cause_pattern = re.compile(rf"cause:\s*({causes})(?![a-z]|\s*\|)", re.I)
    path = event.get("agent_transcript_path") or ""
    blocks, failed = read_assistant_blocks(path) if os.path.isfile(path) else ([], set())
    report = get_report(event, blocks)
    problems = check_report(report, required, cause_pattern)
    problems += check_claims(report, event, str(root), get_scratch(root, config), blocks, failed)
    if not problems:
        finish(event, str(root), name, report, [])
        return 0
    listed = "; ".join(problems)
    tries = get_send_backs(event)
    if tries >= MAX_SEND_BACKS:
        finish(event, str(root), name, report, problems)
        warning = f"Sub-agent {name} stopped with a bad report after {tries} send-backs: {listed}"
        print(json.dumps({"systemMessage": warning}))
        return 0
    get_send_backs_path(event).write_text(str(tries + 1))
    headings = "\n".join(f"## {heading}" for heading in required)
    reason = (
        f"Your report breaks the report skill's form: {listed}\n"
        f"Send the WHOLE report again, not only the fix. Each heading on its own line, once, in this order:\n{headings}\n"
        'A section has a body; "none" only in OUTSIDE, DECIDE, NOT CHECKED and FEEDBACK FOR THE ORCHESTRATOR. A PROBLEMS '
        'MET with no problem reads "no problem met: <what ran clean>"; otherwise each item says "cause: <one of '
        f'{", ".join(CAUSES)}>". COMPLIANCE names a gate with its exit code, or says no gate applied. REPORT CARD has a '
        "Task, Brief and Ease row with a Value 1 to 5, then the two labelled lines."
    )
    print(json.dumps({"decision": "block", "reason": reason}))

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # a bug in the gate must not trap an agent
        print(f"the harness report gate failed and let the agent stop: {error!r}", file=sys.stderr)
        sys.exit(1)
