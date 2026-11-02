#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""SubagentStop hook: in a project with `.harness.json`, every sub-agent stops only with a report in the `report` skill's
form, whose claims its own transcript backs.

Answer, Not proven and Verdict are required; Problems, Next time, Open and Feedback appear when they have something to say.
Each heading comes once, in the form's order, with Verdict last. Each section has the shape the skill gives it. The report is
the agent's last block, handback or text, holding `## Answer`, else its last message.

The claims come from the agent's transcript, never from git, since parallel agents share a tree: each file it changed
through Edit, Write or NotebookEdit is named in the report by its absolute or project-relative path (`guard.scratch` is
exempt), a claim that a check passed needs a Bash call, each `exit <N>` is the result of a Bash call (the transcript shows a
code only for a failed call, `Exit code N`; a call that did not fail is 0), and a READ `path:line` names an existing file with
that many lines; a text quoted after it must lie within 3 lines of that line.

A bad report goes back to the agent, up to MAX_SEND_BACKS times; then the agent may stop and the orchestrator is warned.
Once it stops, one row goes to `ledger.jsonl` in the plugin's data folder, and each Feedback item goes to the project's
`harness-feedback/inbox.md`, where it waits for a retro (`turn.py`).

`.harness.json` may set, under `report`: `causes` (more causes a problem may name).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

from budget import get_agent_path, get_brief, get_default, get_duration, get_turn_limit
from common import EDIT_TOOLS, HANDBACK_TOOL, INBOX, PLUGIN_PREFIX, data_folder, find_project, get_scratch, get_unfenced_lines, read_events
from nudge import get_turn_stats

# The form's sections in order; the rest are left out when they have nothing to say.
ORDER = ("Answer", "Not proven", "Problems", "Next time", "Open", "Feedback", "Verdict")
REQUIRED = ("Answer", "Not proven", "Verdict")
PLACEHOLDER = re.compile(r"\b(pending|tbd|not yet known)\b", re.I)
CAUSES = ("brief", "tool", "rule", "environment", "other agent", "the agent itself")
# A bare "nothing" under Not proven says no more than an empty section.
MIN_NOT_PROVEN_WORDS = 3
VERDICT = re.compile(r"^\W*(done|partial|blocked)\b\W*(\S.*)", re.I | re.S)
# A path with a folder, or a file name with an extension.
FILE_NAME = re.compile(r"[\w.-]+/[\w./-]+|\b[\w-]+\.[A-Za-z]\w*\b")
# A statement that a check succeeded, which only a run can back.
PASS_CLAIM = re.compile(r"\b(tests?|lint|checks?|gates?|build)\b[^.\n]{0,40}\b(pass(?:es|ed)?|clean|green)\b", re.I)
CLOSING_TAGS = re.compile(r"(</[A-Za-z][A-Za-z0-9_-]*>|\s)*$")
EXIT_CODE = re.compile(r"exit\s+[0-9]+", re.I)
ANSWER_HEADING = re.compile(r"^## Answer\s*$", re.M)
READ_CLAIM = re.compile(r"READ `([^`:]+):([0-9]+)(?:-([0-9]+))?`")
# The text a READ claim quotes: right after the claim, in double quotes or backticks.
READ_QUOTE = re.compile(r'[\s:,;\u2013\u2014-]*(?:"([^"\n]+)"|`([^`\n]+)`)')
PATH_LINE = re.compile(r"[^\s:]+:[0-9]+(-[0-9]+)?")
QUOTE_WINDOW = 3
EXIT_CLAIM = re.compile(r"exit\s+([0-9]+)", re.I)
EXIT_RESULT = re.compile(r"\s*Exit code ([0-9]+)")
REPORT_TITLE = re.compile(r"^# Report: [^,\n]*, *(.+?)\s*$", re.M)
# What a FEEDBACK item says when it holds no feedback.
NO_FEEDBACK = re.compile(r"(none|none needed|no feedback|n/?a)[ .]*", re.I)
NO_PROBLEM = re.compile(r"(- +)?no problem", re.I)
MAX_SEND_BACKS = 3
# Seconds this hook waits for a report to reach the transcript, and between looks; well under the hook's timeout of 10.
REPORT_WAIT_S = 3
REPORT_POLL_S = 0.25


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


def check_headings(sections: list[tuple[str, list[str]]], /) -> list[str]:
    """The required headings are there, each heading is the form's and comes once, in order, with Verdict last."""

    names = [name for name, _ in sections]
    problems = [f"missing: {heading}" for heading in REQUIRED if heading not in names]
    problems += [f"not a section of the form: {name}" for name in dict.fromkeys(names) if name not in ORDER]
    problems += [f"duplicated: {heading}" for heading in ORDER if names.count(heading) > 1]
    known = [name for name in dict.fromkeys(names) if name in ORDER]
    problems += [f"out of order: {name}" for name, expected in zip(known, sorted(known, key=ORDER.index), strict=True) if name != expected]
    if "Verdict" in names and names[-1] != "Verdict":
        problems.append("Verdict must be the last section")

    return problems


def check_problems(lines: list[str], cause_pattern: re.Pattern[str], /) -> list[str]:
    """Each Problems item names a cause from the list and what would have helped."""

    if len(lines) == 1 and NO_PROBLEM.match(lines[0]):
        return []
    problems: list[str] = []
    for item in get_items(lines):
        if not cause_pattern.search(item):
            problems.append(f"Problems item names no cause from the skill's list: {item[:70]}")
        if "helped" not in item.lower():
            problems.append(f"Problems item does not say what would have helped: {item[:70]}")

    return problems


def check_feedback(lines: list[str], /) -> list[str]:
    """Each Feedback item names a file to change."""

    texts = [item_text(item) for item in get_items(lines)]

    return [f"Feedback item names no file to change: {text[:70]}" for text in texts if not NO_FEEDBACK.fullmatch(text) and not FILE_NAME.search(text)]


def check_section(heading: str, lines: list[str], cause_pattern: re.Pattern[str], /) -> list[str]:
    """Why one section's body breaks the form."""

    text = " ".join(lines)
    match heading:
        case "Answer" if is_none(lines):
            return ["Answer says none; it says what was asked and what was done"]
        case "Answer" if PLACEHOLDER.search(text):
            return ["Answer holds placeholder text (pending, TBD or not yet known)"]
        case "Not proven" if len(item_text(text).split()) < MIN_NOT_PROVEN_WORDS:
            return ["Not proven is bare; say what was not run or shown, or why nothing was left"]
        case "Problems" if not is_none(lines):
            return check_problems(lines, cause_pattern)
        case "Feedback":
            return check_feedback(lines)
        case "Verdict" if not VERDICT.match(item_text(text)):
            return ["Verdict must open with done, partial or blocked, then one sentence"]

    return []


def check_report(report: str, cause_pattern: re.Pattern[str], /) -> list[str]:
    """Every way a report breaks its form."""

    sections = read_sections(report)
    problems = check_headings(sections)
    bodies = dict(reversed(sections))  # a dict keeps the last pair of a repeated key: reversed, the FIRST occurrence wins
    for heading in ORDER:
        if heading not in bodies:
            continue
        if bodies[heading]:
            problems += check_section(heading, bodies[heading], cause_pattern)
        else:
            problems.append(f"{heading} is empty")

    return problems


def result_text(block: dict, /) -> str:  # keys are data
    """The text of a tool_result block, whether its content is a string or a list of text blocks."""

    content = block.get("content")
    if isinstance(content, list):
        return "\n".join(part.get("text") or "" for part in content if isinstance(part, dict))

    return content if isinstance(content, str) else ""


def read_assistant_blocks(path: str, /) -> tuple[list[dict], dict[str, str], str | None]:  # keys are data
    """The content blocks of a transcript's assistant lines, the text of each error result by tool call id, the model.

    The transcript carries an exit code only for a failed call, as the first line `Exit code N` of its error result.
    """

    blocks: list[dict] = []
    failed: dict[str, str] = {}
    model: str | None = None
    with open(path, errors="replace") as file:
        for line in file:
            try:
                entry = json.loads(line)
                content = entry.get("message", {}).get("content")
            except (ValueError, AttributeError):
                continue
            if entry.get("type") == "assistant" and isinstance((entry.get("message") or {}).get("model"), str):
                model = entry["message"]["model"]
            for block in content if isinstance(content, list) else ():
                if not isinstance(block, dict):
                    continue
                if entry.get("type") == "assistant":
                    blocks.append(block)
                elif entry.get("type") == "user" and block.get("type") == "tool_result" and block.get("is_error"):
                    failed[block.get("tool_use_id")] = result_text(block)

    return blocks, failed, model


def get_report(event: dict, blocks: list[dict], /) -> str:  # keys are data
    """The agent's last block, handback or text, holding `## Answer`, else its last message. User lines never count."""

    last = event.get("last_assistant_message") or ""
    if ANSWER_HEADING.search(last):
        return last
    report = ""
    for block in blocks:
        is_handback = block.get("type") == "tool_use" and block.get("name") == HANDBACK_TOOL
        text = (block.get("input") or {}).get("message") if is_handback else block.get("text")
        if isinstance(text, str) and ANSWER_HEADING.search(text):
            report = text

    return report or last


def count_lines(text: object, /) -> int:
    return len(text.splitlines()) if isinstance(text, str) else 0


def get_file_changes(blocks: list[dict], failed: dict[str, str], cwd: str, /) -> dict[str, int]:  # keys are data
    """The resolved path of each file changed through the edit tools, with an estimate of the lines it gained.

    A call whose result was an error changed nothing. The estimate sums the lines of each call's new text (`new_string`,
    `content` or `new_source`); it ignores the lines a call removed, so a rewrite counts in full.
    """

    changes: dict[str, int] = {}
    for block in blocks:
        if block.get("type") == "tool_use" and block.get("name") in EDIT_TOOLS and block.get("id") not in failed:
            tool_input = block.get("input") or {}
            path = tool_input.get("file_path") or tool_input.get("notebook_path")
            if path:
                key = os.path.realpath(os.path.join(cwd, path))
                added = sum(count_lines(tool_input.get(name)) for name in ("new_string", "content", "new_source"))
                changes[key] = changes.get(key, 0) + added

    return changes


def get_changed_files(blocks: list[dict], failed: dict[str, str], cwd: str, /) -> list[str]:  # keys are data
    """The resolved paths the agent changed through the edit tools; a call whose result was an error changed nothing."""

    return sorted(get_file_changes(blocks, failed, cwd))


def is_named(path: str, report: str, folders: tuple[str, ...], /) -> bool:
    """Whether a report holds a path whole: absolute, or relative to one of the folders (`./` allowed)."""

    spellings = [path, *(os.path.relpath(path, folder) for folder in folders if path.startswith(folder + os.sep))]
    pattern = "|".join(re.escape(spelling) for spelling in spellings)

    return re.search(rf"(?<![\w./-])(?:\./)?(?:{pattern})(?![\w/-]|\.\w)", report) is not None


def check_read_claims(report: str, root: str, /) -> list[str]:
    """Each READ `path:line` names an existing file with at least that many lines; `path:a-b` checks `b`.

    A claim followed by a quoted text needs that text on its lines or within QUOTE_WINDOW lines of them.
    """

    problems: list[str] = []
    for match in READ_CLAIM.finditer(report):
        path, first, last = match.groups()
        full = os.path.join(root, os.path.expanduser(path))
        if not os.path.isfile(full):
            problems.append(f"READ names a file that does not exist: {path}")
            continue
        with open(full, errors="replace") as file:
            lines = file.read().splitlines()
        count = len(lines)
        line = int(last or first)
        if line > count:
            problems.append(f"READ {path}:{line} is past the end of the file, which has {count} lines")
            continue
        quote = READ_QUOTE.match(report, match.end())
        quoted = quote and (quote.group(1) or quote.group(2))
        if quoted and not PATH_LINE.fullmatch(quoted):
            first_line = max(int(first) - 1 - QUOTE_WINDOW, 0)
            window = " ".join(" ".join(lines[first_line : line + QUOTE_WINDOW]).split())
            parts = [" ".join(part.split()) for part in re.split(r"\.\.\.|\u2026", quoted)]
            if not all(part in window for part in parts if part):
                problems.append(
                    f"READ {path}:{line} quotes text that is not on that line or within {QUOTE_WINDOW} lines of it "
                    f"({quoted[:50]!r}): quote the line's own text, or fix the line number"
                )

    return problems


def check_exit_claims(report: str, blocks: list[dict], failed: dict[str, str], /) -> list[str]:  # keys are data
    """Each `exit N` of the report is the result of a Bash call: a failed call's `Exit code N`, or 0 for a call that did not fail."""

    seen: set[int] = set()
    for block in blocks:
        if block.get("type") == "tool_use" and block.get("name") == "Bash":
            call_id = block.get("id")
            match = EXIT_RESULT.match(failed[call_id]) if call_id in failed else None
            if call_id not in failed:
                seen.add(0)
            elif match:
                seen.add(int(match.group(1)))
    claimed = sorted({int(code) for code in EXIT_CLAIM.findall(report)})

    return [
        f"the report claims `exit {code}` and no Bash call of the transcript ended with that code "
        f"(codes seen: {', '.join(map(str, sorted(seen))) or 'none'}): write the exit code each command printed, or drop the claim"
        for code in claimed
        if code not in seen
    ]


def check_claims(report: str, event: dict, root: str, scratch: str, blocks: list[dict], failed: dict[str, str], /) -> list[str]:  # keys are data
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
    # No Bash call at all is its own message; with some, each `exit N` is matched to a result.
    has_bash = any(block.get("type") == "tool_use" and block.get("name") == "Bash" for block in blocks)
    if PASS_CLAIM.search(report) and not has_bash:
        problems.append("the report says a check passed, and the transcript holds no Bash call")
    if EXIT_CODE.search(report) and not has_bash:
        problems.append("the report claims an exit code, and the transcript holds no Bash call")
    elif has_bash:
        problems += check_exit_claims(report, blocks, failed)

    return problems


def get_feedback(report: str, /) -> list[str]:
    """The items of Feedback that are not "none"."""

    lines = dict(reversed(read_sections(report))).get("Feedback", [])
    texts = [item_text(item) for item in get_items(lines)]

    return [text for text in texts if text and not NO_FEEDBACK.fullmatch(text)]


def get_task_title(report: str, /) -> str:
    """The task text of the title line `# Report: <role>, <task>`, empty when there is none."""

    match = REPORT_TITLE.search(report)

    return match.group(1) if match else ""


def file_feedback(root: str, session: str, role: str, items: list[str], /) -> list[str]:
    """Appends each item new to this session to the project's inbox; returns the ids of all the items."""

    inbox = os.path.join(root, INBOX)
    known = open(inbox, errors="replace").read() if os.path.exists(inbox) else ""
    ids: list[str] = []
    for text in dict.fromkeys(items):
        item_id = hashlib.sha1(text.encode()).hexdigest()[:8]
        ids.append(item_id)
        if f"id={item_id} session={session} " not in known:
            os.makedirs(os.path.dirname(inbox), exist_ok=True)
            with open(inbox, "a") as file:
                file.write(f"- id={item_id} session={session} agent={role} {text}\n")

    return ids


def get_budget_turns(event: dict, config: dict, role: str, /) -> int | None:  # keys are data
    """The turns budget.py gives this agent: its brief's `Budget:` line, else the role's default; None if neither."""

    path = get_agent_path(event)
    turns = None
    if path is not None:
        try:
            with open(path, errors="replace") as file:
                turns = get_turn_limit(get_brief(json.loads(file.readline())))
        except (OSError, ValueError, AttributeError):
            pass

    return turns if turns is not None else get_default(config, role)


def write_ledger(
    event: dict, root: str, role: str, report: str, send_backs: int, problems: list[str], ids: list[str], extra: dict, /
) -> None:  # keys are data
    """Appends one row for the stopped agent to the plugin's ledger, which the `retro` skill reads.

    `extra` holds the fields read from the transcript and the config: model, budget_turns, files_changed.
    """

    sections = dict(reversed(read_sections(report)))
    verdict = VERDICT.match(" ".join(sections.get("Verdict", [])))
    causes = re.findall(rf"cause:\s*({'|'.join(CAUSES)}|[^;)|]+)", "\n".join(sections.get("Problems", [])), re.I)
    try:
        path = get_agent_path(event)
        duration = get_duration(path)
        tool_turns = get_turn_stats(read_events(path)) if path else None
    except (OSError, ValueError, AttributeError):
        duration = tool_turns = None
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
        "verdict": verdict.group(1).lower() if verdict else None,
        "causes": [cause.strip().lower() for cause in causes],
        "feedback_ids": ids,
        "model": event.get("model") or extra.get("model"),
        "budget_turns": extra.get("budget_turns"),
        "files_changed": extra.get("files_changed", []),
        "claim_marks": {mark: len(re.findall(rf"\b{mark}\b", report)) for mark in ("READ", "DERIVED", "PROBED")},
        "brief_hash": hashlib.sha1(get_task_title(report).encode()).hexdigest()[:8] if get_task_title(report) else None,
        "tool_turns": tool_turns,
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


def get_extra(event: dict, blocks: list[dict], failed: dict[str, str], model: str | None, config: dict, role: str, root: str, /) -> dict:  # keys are data
    """The ledger fields that come from the transcript and the config."""

    cwd = event.get("cwd") or root
    changes = get_file_changes(blocks, failed, cwd)
    files = [{"path": os.path.relpath(path, root) if path.startswith(root + os.sep) else path, "lines_added": added} for path, added in changes.items()]

    return {"model": model, "budget_turns": get_budget_turns(event, config, role), "files_changed": files}


def finish(event: dict, root: str, role: str, report: str, problems: list[str], extra: dict, /) -> None:  # keys are data
    """The agent stops: its feedback and its ledger row are filed, and its send-back count is dropped."""

    path = get_send_backs_path(event)
    send_backs = get_send_backs(event)
    if path.exists():
        path.unlink()
    session = event.get("session_id") or "unknown"
    write_ledger(event, root, role, report, send_backs, problems, file_feedback(root, session, role, get_feedback(report)), extra)


def wait_for_report(event: dict, path: str, /) -> tuple[list[dict], dict[str, str], str | None]:  # keys are data
    """The transcript's blocks, read again until a report holds its first heading: a handback can reach the file after this hook starts.

    REPORT_WAIT_S is not defended by a case, since none can write the file late; past it the agent counts as ended with no report.
    """

    blocks, failed, model = read_assistant_blocks(path)
    waited = 0.0
    while not ANSWER_HEADING.search(get_report(event, blocks)) and waited < REPORT_WAIT_S:
        time.sleep(REPORT_POLL_S)
        waited += REPORT_POLL_S
        blocks, failed, model = read_assistant_blocks(path)

    return blocks, failed, model


def main() -> int:
    event = json.load(sys.stdin)
    root, config = find_project(event.get("cwd") or os.getcwd())
    settings = config.get("report", {})
    name = (event.get("agent_type") or "").removeprefix(PLUGIN_PREFIX)
    if root is None:
        return 0
    # A cause counts as a whole word, and not when a `|` follows it: the skill's template lists the causes as
    # `brief | tool | ...`, and a copied list is not a choice.
    causes = "|".join(re.escape(cause) for cause in (*CAUSES, *settings.get("causes", ())))
    cause_pattern = re.compile(rf"cause:\s*({causes})(?![a-z]|\s*\|)", re.I)
    path = event.get("agent_transcript_path") or ""
    blocks, failed, model = wait_for_report(event, path) if os.path.isfile(path) else ([], {}, None)
    report = get_report(event, blocks)
    problems = check_report(report, cause_pattern)
    problems += check_claims(report, event, str(root), get_scratch(root, config), blocks, failed)
    extra = get_extra(event, blocks, failed, model, config, name, str(root))
    if not problems:
        finish(event, str(root), name, report, [], extra)
        return 0
    listed = "; ".join(problems)
    tries = get_send_backs(event)
    # An agent that handed back has ended, so a send-back would reach nobody and lose its row and feedback.
    has_ended = bool(blocks) and blocks[-1].get("name") == HANDBACK_TOOL or (os.path.isfile(path) and not report)
    if has_ended or tries >= MAX_SEND_BACKS:
        finish(event, str(root), name, report, problems, extra)
        cause = "and it has already ended" if has_ended else f"after {tries} send-backs"
        warning = f"Sub-agent {name} stopped with a bad report {cause}: {listed}"
        print(json.dumps({"systemMessage": warning}))
        return 0
    get_send_backs_path(event).write_text(str(tries + 1))
    headings = "\n".join(f"## {heading}" for heading in ORDER)
    reason = (
        f"Your report breaks the report skill's form: {listed}\n"
        f"Send the WHOLE report again, not only the fix. Sections in this order, each heading on its own line, once; Answer, Not proven and Verdict always, the rest only if they have something to say:\n{headings}\n"
        f'Each Problems item says "cause: <one of {", ".join(CAUSES)}>" and what would have helped. Each Feedback item names a file to change. '
        "Verdict is last and opens with done, partial or blocked, then one sentence."
    )
    print(json.dumps({"decision": "block", "reason": reason}))

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # a bug in the gate must not trap an agent
        print(f"the harness report gate failed and let the agent stop: {error!r}", file=sys.stderr)
        sys.exit(1)
