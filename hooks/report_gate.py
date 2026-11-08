#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""SubagentStop hook: in every project, every sub-agent of this plugin (`harness:*`) stops only with a report in the `report`
skill's form, whose claims its own transcript backs. An agent of another kind (a built-in helper, another plugin's agent) is
never judged or sent back.

Answer, Not proven and Verdict are required; Problems, Next time, Open and Feedback appear when they have something to say.
Each heading comes once, in the form's order, with Verdict last. Each section has the shape the skill gives it. The report is
the agent's last block, handback or text, holding `## Answer`, else its last message.

The claims come from the agent's transcript, never from git, since parallel agents share a tree: each file it changed
through Edit, Write or NotebookEdit is named in the report by its absolute or project-relative path (`guard.scratch` is
exempt), a claim that a check passed needs a Bash call, each `exit <N>` is the result of a Bash call (the transcript shows a
code only for a failed call, `Exit code N`; a call that did not fail is 0) or a code a Bash call printed (`rg exit 1`, `rc=2`,
make's `Error 2`), and a READ `path:line` names an existing file with that many lines, by its path from the project root or by
an end of path that only one project file has; a text quoted after it must lie within 3 lines of that line.

A bad report goes back to the agent, up to MAX_SEND_BACKS times; then the agent may stop and the orchestrator is warned.
The send-back names only the sections that are wrong and asks for only those. The gate keeps the report it judged; on the
next stop it merges: a section of the new message replaces the sections of the same heading, a section not resent is kept,
a section whose heading is not the form's is dropped, and the sections come in the form's order. A whole new report works as
before. The merged report is what is judged and what is filed: once the agent stops, one row goes to `ledger.jsonl` in the
plugin's data folder, and each Feedback item goes to the project's `__harness__/feedback/inbox.md`, where it waits for a retro
(`turn.py`).

`report_gate.py handback` runs on PreToolUse of the handback tool, where an agent of the app ends: a send-back at its stop
would reach nobody. It runs the same checks on the report the call carries, reading the claims from the agent's transcript,
and refuses a bad one (exit 2) so the agent calls again with the whole report fixed. Its refusals and the stop's send-backs
share one count. It also refuses a handback while a Bash command the agent started in the background has no finished
notification in its transcript: the report would describe a run that is not over.

The owner file may set, under `report`: `causes` (more causes a problem may name).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import NamedTuple

from budget import get_agent_path, get_brief, get_default, get_duration, get_turn_limit
from common import EDIT_TOOLS, HANDBACK_TOOL, INBOX, ensure_harness_folder, PLUGIN_PREFIX, data_folder, find_project, get_feedback_root, get_fenced_indices, get_scratch, get_unfenced_lines, read_events, write_atomic
from nudge import get_turn_stats
from turn import FINISHED_STATUSES, NOTIFICATION, get_notice_text

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
# After a send-back the new message may hold any section of the form.
SECTION_HEADING = re.compile(rf"^## ({'|'.join(ORDER)})\s*$", re.M)
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
# An exit code a command printed rather than ended with: `rg exit 1`, `rc=2`, make's `Error 2`, `returncode: 1`.
PRINTED_EXIT = r"\b(?:exit|code|rc|status|returncode|returned|error)\b\D{{0,12}}\b{code}\b"
# The project's files, for a READ path given by its end: git's list, else a walk of this many files at most.
GIT_TIMEOUT_S = 3
MAX_WALK_FILES = 20000
SKIPPED_FOLDERS = frozenset({"node_modules", "__pycache__"})
# Characters a report may hold outside fenced blocks, which are evidence the reader skips. Every character of a report stays
# in the main session's context; the owner file's `report.max_chars` overrides it.
MAX_REPORT_CHARS = 6000
# Seconds this hook waits for a report to reach the transcript, and between looks; well under the hook's timeout of 10.
REPORT_WAIT_S = 3
REPORT_POLL_S = 0.25


class Problem(NamedTuple):
    """One way a report breaks the form, with the section the agent must send again to fix it."""

    section: str
    text: str


class Kept(NamedTuple):
    """What the gate keeps between a send-back and the next stop: the message judged and the merged report."""

    raw: str
    merged: str


class SplitReport(NamedTuple):
    """A report cut at its `## ` headings: the lines before the first, and each section as its heading and lines."""

    preamble: list[str]
    sections: list[tuple[str, list[str]]]


def split_report(report: str, /) -> SplitReport:
    """The lines before the first `## ` heading, and each section as its heading and all its lines, heading line first."""

    lines = report.splitlines()
    fenced = get_fenced_indices(lines)
    preamble: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    for index, line in enumerate(lines):
        if line.startswith("## ") and index not in fenced:
            sections.append((line[3:].strip(), [line]))
        elif sections:
            sections[-1][1].append(line)
        else:
            preamble.append(line)

    return SplitReport(preamble, sections)


def merge_reports(previous: str, new: str, /) -> str:
    """The previous report with the sections of the new message in place of those of the same heading.

    A section not resent stays; a section whose heading is not the form's is dropped; the result is in the form's order.
    The title is the new message's when it has one.
    """

    old_preamble, old_sections = split_report(previous)
    new_preamble, new_sections = split_report(new)
    resent = {heading for heading, _ in new_sections}
    kept = [(heading, lines) for heading, lines in old_sections if heading in ORDER and heading not in resent]
    merged = sorted([*kept, *new_sections], key=lambda section: ORDER.index(section[0]) if section[0] in ORDER else len(ORDER))
    preamble = new_preamble if REPORT_TITLE.search("\n".join(new_preamble)) else old_preamble

    return "\n".join([*preamble, *(line for _, lines in merged for line in lines)])


def get_section_at(report: str, position: int, /) -> str:
    """The form's section holding this character position of the report, Answer when it lies in none."""

    sections = read_sections(report[:position])
    heading = sections[-1][0] if sections else ""

    return heading if heading in ORDER else "Answer"


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


def check_headings(sections: list[tuple[str, list[str]]], /) -> list[Problem]:
    """The required headings are there, each heading is the form's and comes once, in order, with Verdict last."""

    names = [name for name, _ in sections]
    problems = [Problem(heading, f"missing: {heading}") for heading in REQUIRED if heading not in names]
    problems += [Problem(name, f"not a section of the form: {name} (leave it out)") for name in dict.fromkeys(names) if name not in ORDER]
    problems += [Problem(heading, f"duplicated: {heading}") for heading in ORDER if names.count(heading) > 1]
    known = [name for name in dict.fromkeys(names) if name in ORDER]
    problems += [Problem(name, f"out of order: {name}") for name, expected in zip(known, sorted(known, key=ORDER.index), strict=True) if name != expected]
    if "Verdict" in names and names[-1] != "Verdict":
        problems.append(Problem("Verdict", "Verdict must be the last section"))

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


def check_report(report: str, cause_pattern: re.Pattern[str], /) -> list[Problem]:
    """Every way a report breaks its form."""

    sections = read_sections(report)
    problems = check_headings(sections)
    bodies = dict(reversed(sections))  # a dict keeps the last pair of a repeated key: reversed, the FIRST occurrence wins
    for heading in ORDER:
        if heading not in bodies:
            continue
        if bodies[heading]:
            problems += [Problem(heading, text) for text in check_section(heading, bodies[heading], cause_pattern)]
        else:
            problems.append(Problem(heading, f"{heading} is empty"))

    return problems


def result_text(block: dict, /) -> str:  # keys are data
    """The text of a tool_result block, whether its content is a string or a list of text blocks."""

    content = block.get("content")
    if isinstance(content, list):
        return "\n".join(part.get("text") or "" for part in content if isinstance(part, dict))

    return content if isinstance(content, str) else ""


class AssistantBlocks(NamedTuple):
    """What a transcript holds of the assistant: its content blocks, each error result's text by call id, the model, each result's text by call id."""

    blocks: list[dict]  # keys are data
    failed: dict[str, str]
    model: str | None
    outputs: dict[str, str]


def read_assistant_blocks(path: str, /) -> AssistantBlocks:  # keys are data
    """The content blocks of a transcript's assistant lines, the text of each error result by tool call id, the model.

    The transcript carries an exit code only for a failed call, as the first line `Exit code N` of its error result.
    """

    blocks: list[dict] = []
    failed: dict[str, str] = {}
    outputs: dict[str, str] = {}
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
                elif entry.get("type") == "user" and block.get("type") == "tool_result":
                    outputs[block.get("tool_use_id")] = result_text(block)
                    if block.get("is_error"):
                        failed[block.get("tool_use_id")] = result_text(block)

    return AssistantBlocks(blocks, failed, model, outputs)


def get_report(event: dict, blocks: list[dict], /, *, is_resend: bool = False) -> str:  # keys are data
    """The agent's last block, handback or text, holding `## Answer`, else its last message. User lines never count.

    After a send-back (`is_resend`) a heading of any section of the form will do, since the agent sends only the sections asked for.
    """

    heading = SECTION_HEADING if is_resend else ANSWER_HEADING
    last = event.get("last_assistant_message") or ""
    if heading.search(last):
        return last
    report = ""
    for block in blocks:
        is_handback = block.get("type") == "tool_use" and block.get("name") == HANDBACK_TOOL
        text = (block.get("input") or {}).get("message") if is_handback else block.get("text")
        if isinstance(text, str) and heading.search(text):
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


def get_project_files(root: str, /) -> list[str]:
    """The project's files relative to its root: git's tracked and unignored ones, else a walk of MAX_WALK_FILES at most."""

    try:
        run = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        run = None
    if run is not None and run.returncode == 0:
        return run.stdout.splitlines()
    found: list[str] = []
    for folder, names, files in os.walk(root):
        names[:] = [name for name in names if not name.startswith(".") and name not in SKIPPED_FOLDERS]
        found += [os.path.relpath(os.path.join(folder, name), root) for name in files]
        if len(found) >= MAX_WALK_FILES:
            break

    return found


def find_by_end(path: str, files: list[str], /) -> list[str]:
    """The project files whose path is `path` or ends with it after a folder."""

    end = path.removeprefix("./")

    return [name for name in files if name == end or name.endswith("/" + end)]


def check_read_claims(report: str, root: str, /) -> list[Problem]:
    """Each READ `path:line` names an existing file with at least that many lines; `path:a-b` checks `b`.

    A path not found from the root is looked up by its end: one project file ending with it is that file. A claim followed
    by a quoted text needs that text on its lines or within QUOTE_WINDOW lines of them.
    """

    problems: list[Problem] = []
    files: list[str] | None = None
    for match in READ_CLAIM.finditer(report):
        path, first, last = match.groups()
        section = get_section_at(report, match.start())
        full = os.path.join(root, os.path.expanduser(path))
        if not os.path.isfile(full):
            files = get_project_files(root) if files is None else files
            found = find_by_end(path, files)
            if len(found) > 1:
                problems.append(Problem(section, f"READ names {path}, and {len(found)} project files end with it: give its path from the project root"))
                continue
            if not found:
                problems.append(Problem(section, f"READ names a file that does not exist: {path}"))
                continue
            full = os.path.join(root, found[0])
        with open(full, errors="replace") as file:
            lines = file.read().splitlines()
        count = len(lines)
        line = int(last or first)
        if line > count:
            problems.append(Problem(section, f"READ {path}:{line} is past the end of the file, which has {count} lines"))
            continue
        quote = READ_QUOTE.match(report, match.end())
        quoted = quote and (quote.group(1) or quote.group(2))
        if quoted and not PATH_LINE.fullmatch(quoted):
            first_line = max(int(first) - 1 - QUOTE_WINDOW, 0)
            window = " ".join(" ".join(lines[first_line : line + QUOTE_WINDOW]).split())
            parts = [" ".join(part.split()) for part in re.split(r"\.\.\.|\u2026", quoted)]
            if not all(part in window for part in parts if part):
                problems.append(
                    Problem(
                        section,
                        f"READ {path}:{line} quotes text that is not on that line or within {QUOTE_WINDOW} lines of it "
                        f"({quoted[:50]!r}): quote the line's own text, or fix the line number",
                    )
                )

    return problems


def check_exit_claims(report: str, blocks: list[dict], failed: dict[str, str], outputs: dict[str, str], /) -> list[Problem]:  # keys are data
    """Each `exit N` of the report is the result of a Bash call: a failed call's `Exit code N`, 0 for a call that did not fail, or a code a call printed."""

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
    printed = "\n".join(outputs.get(block.get("id"), "") for block in blocks if block.get("type") == "tool_use" and block.get("name") == "Bash")

    return [
        Problem(
            get_section_at(report, re.search(rf"exit\s+{code}\b", report, re.I).start()),
            f"the report claims `exit {code}` and no Bash call of the transcript ended with that code "
            f"(codes seen: {', '.join(map(str, sorted(seen))) or 'none'}): write the exit code each command printed, or drop the claim",
        )
        for code in claimed
        if code not in seen and not re.search(PRINTED_EXIT.format(code=code), printed, re.I)
    ]


def get_max_chars(settings: object, /) -> int:
    """The report length limit: `report.max_chars` when it is a positive integer, else the default."""

    value = settings.get("max_chars") if isinstance(settings, dict) else None

    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else MAX_REPORT_CHARS


def check_length(report: str, limit: int, /) -> list[Problem]:
    """One problem when the report, outside its fenced blocks, is over the limit; it names the longest section."""

    count = len("\n".join(get_unfenced_lines(report)))
    if count <= limit:
        return []
    sections = read_sections(report)
    longest = max(sections, key=lambda section: len("\n".join(section[1])))[0] if sections else "Answer"
    text = (
        f"the report is {count} characters, over the limit of {limit}: cut repeated detail, keep each claim with its evidence, "
        "move long lists to a file in `__scratch__/` and name it"
    )

    return [Problem(longest, text)]


def check_claims(
    report: str, event: dict, root: str, scratch: str, blocks: list[dict], failed: dict[str, str], outputs: dict[str, str], /
) -> list[Problem]:  # keys are data
    """What the report claims against what its transcript shows; no transcript leaves only the READ claims."""

    problems = check_read_claims(report, root)
    if not os.path.isfile(event.get("agent_transcript_path") or ""):
        return problems
    cwd = event.get("cwd") or root
    folders = (root, os.path.realpath(cwd))
    for path in get_changed_files(blocks, failed, cwd):
        is_exempt = scratch and (path == scratch or path.startswith(scratch + os.sep))
        if not is_exempt and not is_named(path, report, folders):
            problems.append(Problem("Answer", f"the report does not name a file the agent changed: {path}"))
    # No Bash call at all is its own message; with some, each `exit N` is matched to a result.
    has_bash = any(block.get("type") == "tool_use" and block.get("name") == "Bash" for block in blocks)
    pass_claim = PASS_CLAIM.search(report)
    exit_claim = EXIT_CODE.search(report)
    if pass_claim and not has_bash:
        problems.append(Problem(get_section_at(report, pass_claim.start()), "the report says a check passed, and the transcript holds no Bash call"))
    if exit_claim and not has_bash:
        problems.append(Problem(get_section_at(report, exit_claim.start()), "the report claims an exit code, and the transcript holds no Bash call"))
    elif has_bash:
        problems += check_exit_claims(report, blocks, failed, outputs)

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
            ensure_harness_folder(Path(root))
            os.makedirs(os.path.dirname(inbox), exist_ok=True)
            with open(inbox, "a") as file:
                file.write(f"- id={item_id} session={session} agent={role} time={time.strftime('%Y-%m-%dT%H:%M:%S%z')} {text}\n")

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

    try:
        return int(path.read_text())
    except (OSError, ValueError):
        return 0


def get_kept_path(event: dict, /) -> Path:  # keys are data
    """The file holding the report the gate judged at the last send-back."""

    return get_send_backs_path(event).with_suffix(".report")


def get_kept(event: dict, tries: int, /) -> Kept | None:  # keys are data
    """The report kept at the last send-back, None before any send-back or when the file is unreadable."""

    path = get_kept_path(event)
    if not tries or not path.exists():
        return None
    try:
        data = json.loads(path.read_text())

        return Kept(str(data["raw"]), str(data["merged"]))
    except (ValueError, KeyError, TypeError):
        return None


def make_send_back(problems: list[Problem], /, *, is_handback: bool = False) -> str:
    """The reason of a send-back: the sections that are wrong with what is wrong in each, and the form of those sections only.

    A refused handback asks for the whole report again, since the main session gets only what the handback carries.
    """

    hints = {
        "Problems": f'Each Problems item says "cause: <one of {", ".join(CAUSES)}>" and what would have helped, for example: '
        '"- The first test run failed on a missing fixture (cause: brief). A Runs: line naming the fixture would have helped."',
        "Feedback": "Each Feedback item names a file to change.",
        "Verdict": "Verdict is last and opens with done, partial or blocked, then one sentence.",
    }
    wrong = list(dict.fromkeys(problem.section for problem in problems))
    lines = [f"- {section}: " + "; ".join(problem.text for problem in problems if problem.section == section) for section in wrong]
    advice = " ".join(hints[section] for section in wrong if section in hints)

    ask = (
        f"Call {HANDBACK_TOOL} again with the whole report, these sections fixed; the main session gets only what that call carries. "
        if is_handback
        else "Send again only these sections, each as its `## ` heading line and its body; every other section stays as it was. "
    )

    return ("Your report breaks the report skill's form in these sections only:\n" + "\n".join(lines) + "\n" + ask + advice).strip()


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
    for stale in (path, get_kept_path(event)):
        if stale.exists():
            stale.unlink()
    session = event.get("session_id") or "unknown"
    write_ledger(event, root, role, report, send_backs, problems, file_feedback(str(get_feedback_root(Path(root))), session, role, get_feedback(report)), extra)


def is_awaited(report: str, kept: Kept | None, /) -> bool:
    """Whether the report is not there yet: it holds no heading, or it is the message already judged."""

    heading = ANSWER_HEADING if kept is None else SECTION_HEADING

    return not heading.search(report) or (kept is not None and report == kept.raw)


def wait_for_report(event: dict, path: str, kept: Kept | None, /) -> AssistantBlocks:  # keys are data
    """The transcript's blocks, read again until a new report holds a heading: a handback can reach the file after this hook starts.

    After a send-back the message judged then does not count as new.

    REPORT_WAIT_S is not defended by a case, since none can write the file late; past it the agent counts as ended with no report.
    """

    found = read_assistant_blocks(path)
    waited = 0.0
    while is_awaited(get_report(event, found.blocks, is_resend=kept is not None), kept) and waited < REPORT_WAIT_S:
        time.sleep(REPORT_POLL_S)
        waited += REPORT_POLL_S
        found = read_assistant_blocks(path)

    return found


def get_problems(report: str, event: dict, root: Path, config: dict, found: AssistantBlocks, /) -> list[Problem]:  # keys are data
    """Everything wrong with a report: its form, its length and the claims its transcript does not back."""

    settings = config.get("report", {})
    # A cause counts as a whole word, and not when a `|` follows it: the skill's template lists the causes as
    # `brief | tool | ...`, and a copied list is not a choice.
    causes = "|".join(re.escape(cause) for cause in (*CAUSES, *settings.get("causes", ())))
    cause_pattern = re.compile(rf"cause:\s*({causes})(?![a-z]|\s*\|)", re.I)
    problems = check_report(report, cause_pattern)
    problems += check_length(report, get_max_chars(settings))
    problems += check_claims(report, event, str(root), get_scratch(root, config), found.blocks, found.failed, found.outputs)

    return problems


def count_running_jobs(path: Path, outputs: dict[str, str], /) -> int:  # keys are data
    """The Bash commands the agent started in the background whose finished notification is not in its transcript.

    A launch is a Bash call with `run_in_background` true whose result says it runs in the background; its end is a task
    notification naming the call's id with a finished status, the wording `turn.py` reads for agents.
    """

    launched: set[str] = set()
    finished: set[str] = set()
    for line in read_events(path):
        content = (line.get("message") or {}).get("content") if line.get("type") == "assistant" else None
        for block in content if isinstance(content, list) else ():
            is_background = isinstance(block, dict) and block.get("name") == "Bash" and (block.get("input") or {}).get("run_in_background") is True
            if is_background and "in background" in outputs.get(block.get("id"), ""):
                launched.add(block["id"])
        finished.update(tool_id for tool_id, status in NOTIFICATION.findall(get_notice_text(line)) if status in FINISHED_STATUSES)

    return len(launched - finished)


def check_handback(event: dict, /) -> int:  # keys are data
    """PreToolUse on the handback: a bad report is refused while the agent can still fix it.

    The count is the one the stop reads, so the two send back MAX_SEND_BACKS times at most between them; past it the
    handback goes through and the stop files the report with its problems.
    """

    root, config = find_project(event.get("cwd") or os.getcwd())
    report = (event.get("tool_input") or {}).get("message")
    tries = get_send_backs(event)
    if not event.get("agent_id") or not is_judged(event) or not isinstance(report, str) or tries >= MAX_SEND_BACKS:
        return 0
    path = get_agent_path(event)
    found = read_assistant_blocks(str(path)) if path is not None else AssistantBlocks([], {}, None, {})
    # A PreToolUse event names only the session's transcript; the claims are read from the agent's own.
    judged = {**event, "agent_transcript_path": str(path)} if path is not None else event
    problems = get_problems(report, judged, root, config, found)
    running = count_running_jobs(path, found.outputs) if path is not None else 0
    if running:
        problems.append(Problem("Answer", f"{running} background command(s) you started are still running; wait for their completion notice (it wakes you), then report their result"))
    if not problems:
        return 0
    write_atomic(get_send_backs_path(event), str(tries + 1))
    print(make_send_back(problems, is_handback=True), file=sys.stderr)

    return 2


def is_judged(event: dict, /) -> bool:  # keys are data
    """Whether the agent is one of this plugin's: its type opens with the plugin prefix."""

    return str(event.get("agent_type") or "").startswith(PLUGIN_PREFIX)


def main() -> int:
    event = json.load(sys.stdin)
    if sys.argv[1:2] == ["handback"]:
        return check_handback(event)
    if not is_judged(event):
        return 0
    root, config = find_project(event.get("cwd") or os.getcwd())
    name = (event.get("agent_type") or "").removeprefix(PLUGIN_PREFIX)
    path = event.get("agent_transcript_path") or ""
    tries = get_send_backs(event)
    kept = get_kept(event, tries)
    found = wait_for_report(event, path, kept) if os.path.isfile(path) else AssistantBlocks([], {}, None, {})
    sent = get_report(event, found.blocks, is_resend=kept is not None)
    report = merge_reports(kept.merged, sent) if kept and sent else (kept.merged if kept else sent)
    problems = get_problems(report, event, root, config, found)
    extra = get_extra(event, found.blocks, found.failed, found.model, config, name, str(root))
    texts = [problem.text for problem in problems]
    if not problems:
        finish(event, str(root), name, report, [], extra)
        return 0
    listed = "; ".join(texts)
    # An agent that handed back has ended, so a send-back would reach nobody and lose its row and feedback.
    has_ended = bool(found.blocks) and found.blocks[-1].get("name") == HANDBACK_TOOL or (os.path.isfile(path) and not sent)
    if has_ended or tries >= MAX_SEND_BACKS:
        finish(event, str(root), name, report, texts, extra)
        cause = "and it has already ended" if has_ended else f"after {tries} send-backs"
        warning = f"Sub-agent {name} stopped with a bad report {cause}: {listed}"
        print(json.dumps({"systemMessage": warning}))
        return 0
    write_atomic(get_send_backs_path(event), str(tries + 1))
    write_atomic(get_kept_path(event), json.dumps({"raw": sent, "merged": report}))
    reason = make_send_back(problems)
    print(json.dumps({"decision": "block", "reason": reason}))

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # a bug in the gate must not trap an agent
        print(f"the harness report gate failed and let the agent stop: {error!r}", file=sys.stderr)
        sys.exit(1)
