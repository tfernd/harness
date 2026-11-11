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
import subprocess
import sys
import time
from pathlib import Path
from typing import NamedTuple

from budget import get_agent_path, get_brief, get_default, get_duration, get_turn_limit
from common import EDIT_TOOLS, HANDBACK_TOOL, INBOX, ensure_harness_folder, PLUGIN_PREFIX, data_folder, find_project, get_feedback_root, get_fenced_indices, get_scratch, get_unfenced_lines, read_events, write_atomic
from nudge import get_turn_stats
from turn import FINISHED_STATUSES, NOTIFICATION, get_notice_text

ORDER = ("Answer", "Not proven", "Problems", "Next time", "Open", "Feedback", "Verdict")
REQUIRED = ("Answer", "Not proven", "Verdict")
PLACEHOLDER = re.compile(r"\b(pending|tbd|not yet known)\b", re.I)
CAUSES = ("brief", "tool", "rule", "environment", "other agent", "the agent itself")
MIN_NOT_PROVEN_WORDS = 3
VERDICT = re.compile(r"^\W*(done|partial|blocked)\b\W*(\S.*)", re.I | re.S)
FILE_NAME = re.compile(r"[\w.-]+/[\w./-]+|\b[\w-]+\.[A-Za-z]\w*\b")
PASS_CLAIM = re.compile(r"\b(tests?|lint|checks?|gates?|build)\b[^.\n]{0,40}\b(pass(?:es|ed)?|clean|green)\b", re.I)
CLOSING_TAGS = re.compile(r"(</[A-Za-z][A-Za-z0-9_-]*>|\s)*$")
EXIT_CODE = re.compile(r"exit\s+[0-9]+", re.I)
ANSWER_HEADING = re.compile(r"^## Answer\s*$", re.M)
SECTION_HEADING = re.compile(rf"^## ({'|'.join(ORDER)})\s*$", re.M)
READ_CLAIM = re.compile(r"READ `([^`:]+):([0-9]+)(?:-([0-9]+))?`")
READ_QUOTE = re.compile(r'[\s:,;\u2013\u2014-]*(?:"([^"\n]+)"|`([^`\n]+)`)')
PATH_LINE = re.compile(r"[^\s:]+:[0-9]+(-[0-9]+)?")
QUOTE_WINDOW = 3
EXIT_CLAIM = re.compile(r"exit\s+([0-9]+)", re.I)
EXIT_RESULT = re.compile(r"\s*Exit code ([0-9]+)")
REPORT_TITLE = re.compile(r"^# Report: [^,\n]*, *(.+?)\s*$", re.M)
NO_FEEDBACK = re.compile(r"(none|none needed|no feedback|n/?a)[ .]*", re.I)
NO_PROBLEM = re.compile(r"(- +)?no problem", re.I)
MAX_SEND_BACKS = 3
MAX_JOB_SEND_BACKS = 2
JOB_SHOWN_CHARS = 80
JOB_NAMED_CHARS = 20
PRINTED_EXIT = r"\b(?:exit|code|rc|status|returncode|returned|error)\b\D{{0,12}}\b{code}\b"
GIT_TIMEOUT_S = 3
MAX_WALK_FILES = 20000
SKIPPED_FOLDERS = frozenset({"node_modules", "__pycache__"})
MAX_REPORT_CHARS = 6000
CANNOT_CLAIM = re.compile(r"\b(?:can['\u2019]?t|cannot|couldn['\u2019]?t|unable to|not possible|no access|not allowed|blocked)\b", re.I)
NOT_ATTEMPTED = re.compile(r"not attempted", re.I)
CANNOT_SKIPPED_SECTIONS = frozenset({"Verdict"})
CANNOT_SHOWN_CHARS = 100
NEGATION_START = r"(?:it|this|that)\s+(?:is|was)\s+not|(?:it|this|that)['\u2019]s\s+not|(?:it|this|that)\s+(?:isn['\u2019]t|wasn['\u2019]t)"
REVEAL_START = r"(?:it|this|that)(?:['\u2019]s|\s+is|\s+was)\b"
SENTENCE_START = r"(?:^|[.!?]\s+)"
WRITING_TICS = {
    "negation first, then the reveal (\"It is not X. It is Y.\")": re.compile(
        rf"{SENTENCE_START}(?:{NEGATION_START})\s+[^.\n]{{1,80}}?(?:[.;,]\s+|\s+\u2014\s+|\s+-\s+){REVEAL_START}", re.I | re.M
    ),
    "a run of nots ending in just (\"Not X. Not Y. Just Z.\")": re.compile(
        rf"{SENTENCE_START}not\s+[^.\n]{{1,60}}\.\s+not\s+[^.\n]{{1,60}}\.\s+just\b", re.I | re.M
    ),
}
TICS_FILE = "skills/report/references/prose.md"
REPORT_WAIT_S = 3
REPORT_POLL_S = 0.25


class Problem(NamedTuple):

    section: str
    text: str


class Kept(NamedTuple):

    raw: str
    merged: str


class SplitReport(NamedTuple):

    preamble: list[str]
    sections: list[tuple[str, list[str]]]


def split_report(report: str, /) -> SplitReport:

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

    old_preamble, old_sections = split_report(previous)
    new_preamble, new_sections = split_report(new)
    resent = {heading for heading, _ in new_sections}
    kept = [(heading, lines) for heading, lines in old_sections if heading in ORDER and heading not in resent]
    merged = sorted([*kept, *new_sections], key=lambda section: ORDER.index(section[0]) if section[0] in ORDER else len(ORDER))
    preamble = new_preamble if REPORT_TITLE.search("\n".join(new_preamble)) else old_preamble

    return "\n".join([*preamble, *(line for _, lines in merged for line in lines)])


def get_section_at(report: str, position: int, /) -> str:

    sections = read_sections(report[:position])
    heading = sections[-1][0] if sections else ""

    return heading if heading in ORDER else "Answer"


def read_sections(report: str, /) -> list[tuple[str, list[str]]]:

    sections: list[tuple[str, list[str]]] = []
    for line in get_unfenced_lines(report):
        if line.startswith("## "):
            sections.append((line[3:].strip(), []))
        elif sections and line.strip():
            sections[-1][1].append(line)

    return sections


def get_items(lines: list[str], /) -> list[str]:

    items: list[str] = []
    for line in lines:
        if line.startswith("- ") or not line[0].isspace() or not items:
            items.append(line)
        else:
            items[-1] += " " + line.strip()

    return items


def item_text(item: str, /) -> str:

    return CLOSING_TAGS.sub("", re.sub(r"^- +", "", item))


def is_none(lines: list[str], /) -> bool:
    return item_text(" ".join(lines)).rstrip(" .").lower() == "none"


def check_headings(sections: list[tuple[str, list[str]]], /) -> list[Problem]:

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

    texts = [item_text(item) for item in get_items(lines)]

    return [f"Feedback item names no file to change: {text[:70]}" for text in texts if not NO_FEEDBACK.fullmatch(text) and not FILE_NAME.search(text)]


def check_section(heading: str, lines: list[str], cause_pattern: re.Pattern[str], /) -> list[str]:

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

    sections = read_sections(report)
    problems = check_headings(sections)
    bodies = dict(reversed(sections))
    for heading in ORDER:
        if heading not in bodies:
            continue
        if bodies[heading]:
            problems += [Problem(heading, text) for text in check_section(heading, bodies[heading], cause_pattern)]
        else:
            problems.append(Problem(heading, f"{heading} is empty"))

    return problems


def result_text(block: dict, /) -> str:

    content = block.get("content")
    if isinstance(content, list):
        return "\n".join(part.get("text") or "" for part in content if isinstance(part, dict))

    return content if isinstance(content, str) else ""


class AssistantBlocks(NamedTuple):

    blocks: list[dict]
    failed: dict[str, str]
    model: str | None
    outputs: dict[str, str]


def read_assistant_blocks(path: str, /) -> AssistantBlocks:

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


def get_report(event: dict, blocks: list[dict], /, *, is_resend: bool = False) -> str:

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


def get_file_changes(blocks: list[dict], failed: dict[str, str], cwd: str, /) -> dict[str, int]:

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


def get_changed_files(blocks: list[dict], failed: dict[str, str], cwd: str, /) -> list[str]:

    return sorted(get_file_changes(blocks, failed, cwd))


def is_named(path: str, report: str, folders: tuple[str, ...], /) -> bool:

    spellings = [path, *(os.path.relpath(path, folder) for folder in folders if path.startswith(folder + os.sep))]
    pattern = "|".join(re.escape(spelling) for spelling in spellings)

    return re.search(rf"(?<![\w./-])(?:\./)?(?:{pattern})(?![\w/-]|\.\w)", report) is not None


def get_project_files(root: str, /) -> list[str]:

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

    end = path.removeprefix("./")

    return [name for name in files if name == end or name.endswith("/" + end)]


def check_read_claims(report: str, root: str, /) -> list[Problem]:

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


def check_exit_claims(report: str, blocks: list[dict], failed: dict[str, str], outputs: dict[str, str], /) -> list[Problem]:

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

    value = settings.get("max_chars") if isinstance(settings, dict) else None

    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else MAX_REPORT_CHARS


def check_length(report: str, limit: int, /) -> list[Problem]:

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
) -> list[Problem]:

    problems = check_read_claims(report, root)
    if not os.path.isfile(event.get("agent_transcript_path") or ""):
        return problems
    cwd = event.get("cwd") or root
    folders = (root, os.path.realpath(cwd))
    for path in get_changed_files(blocks, failed, cwd):
        is_exempt = scratch and (path == scratch or path.startswith(scratch + os.sep))
        if not is_exempt and not is_named(path, report, folders):
            problems.append(Problem("Answer", f"the report does not name a file the agent changed: {path}"))
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


def get_cannot_path(event: dict, /) -> Path:

    return get_send_backs_path(event).with_suffix(".cannot")


def get_cannot_problems(report: str, event: dict, found: AssistantBlocks, /) -> list[Problem]:

    if found.failed or not found.blocks or read_count(get_cannot_path(event)):
        return []
    problems: list[Problem] = []
    for heading, lines in read_sections(report):
        if heading in CANNOT_SKIPPED_SECTIONS:
            continue
        for line in lines:
            if CANNOT_CLAIM.search(line) and not NOT_ATTEMPTED.search(line):
                shown = " ".join(line.split())[:CANNOT_SHOWN_CHARS]
                text = (
                    f'the line "{shown}" says something could not be done, and no call of the transcript failed or was refused. '
                    "Try it and quote the error, or write `not attempted: <why>`."
                )
                problems.append(Problem(heading if heading in ORDER else "Answer", text))

    return problems


def get_tics_note(report: str, /) -> str:

    text = "\n".join(get_unfenced_lines(report))
    found = [name for name, pattern in WRITING_TICS.items() if pattern.search(text)]
    if not found:
        return ""

    return f"Writing tics in the report (a note, nothing is held): {'; '.join(found)}. The full list and the plain rewrite are in {TICS_FILE}."


def get_feedback(report: str, /) -> list[str]:

    lines = dict(reversed(read_sections(report))).get("Feedback", [])
    texts = [item_text(item) for item in get_items(lines)]

    return [text for text in texts if text and not NO_FEEDBACK.fullmatch(text)]


def get_task_title(report: str, /) -> str:

    match = REPORT_TITLE.search(report)

    return match.group(1) if match else ""


def file_feedback(root: str, session: str, role: str, items: list[str], /) -> list[str]:

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


def get_budget_turns(event: dict, config: dict, role: str, /) -> int | None:

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
) -> None:

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


def get_send_backs_path(event: dict, /) -> Path:

    folder = data_folder() / "send-backs"
    folder.mkdir(exist_ok=True)

    return folder / f"{event.get('agent_id') or 'unknown'}.count"


def read_count(path: Path, /) -> int:

    try:
        return int(path.read_text())
    except (OSError, ValueError):
        return 0


def get_send_backs(event: dict, /) -> int:

    return read_count(get_send_backs_path(event))


def get_jobs_path(event: dict, /) -> Path:

    return get_send_backs_path(event).with_suffix(".jobs")


def get_job_send_backs(event: dict, /) -> int:

    return read_count(get_jobs_path(event))


def get_kept_path(event: dict, /) -> Path:

    return get_send_backs_path(event).with_suffix(".report")


def get_kept(event: dict, tries: int, /) -> Kept | None:

    path = get_kept_path(event)
    if not tries or not path.exists():
        return None
    try:
        data = json.loads(path.read_text())

        return Kept(str(data["raw"]), str(data["merged"]))
    except (ValueError, KeyError, TypeError):
        return None


def make_send_back(problems: list[Problem], /, *, is_handback: bool = False) -> str:

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


def get_extra(event: dict, blocks: list[dict], failed: dict[str, str], model: str | None, config: dict, role: str, root: str, /) -> dict:

    cwd = event.get("cwd") or root
    changes = get_file_changes(blocks, failed, cwd)
    files = [{"path": os.path.relpath(path, root) if path.startswith(root + os.sep) else path, "lines_added": added} for path, added in changes.items()]

    return {"model": model, "budget_turns": get_budget_turns(event, config, role), "files_changed": files}


def finish(event: dict, root: str, role: str, report: str, problems: list[str], extra: dict, /) -> None:

    path = get_send_backs_path(event)
    send_backs = get_send_backs(event)
    for stale in (path, get_kept_path(event), get_jobs_path(event), get_cannot_path(event)):
        if stale.exists():
            stale.unlink()
    session = event.get("session_id") or "unknown"
    write_ledger(event, root, role, report, send_backs, problems, file_feedback(str(get_feedback_root(Path(root))), session, role, get_feedback(report)), extra)


def is_awaited(report: str, kept: Kept | None, /) -> bool:

    heading = ANSWER_HEADING if kept is None else SECTION_HEADING

    return not heading.search(report) or (kept is not None and report == kept.raw)


def wait_for_report(event: dict, path: str, kept: Kept | None, /) -> AssistantBlocks:

    found = read_assistant_blocks(path)
    waited = 0.0
    while is_awaited(get_report(event, found.blocks, is_resend=kept is not None), kept) and waited < REPORT_WAIT_S:
        time.sleep(REPORT_POLL_S)
        waited += REPORT_POLL_S
        found = read_assistant_blocks(path)

    return found


def get_problems(report: str, event: dict, root: Path, config: dict, found: AssistantBlocks, /) -> list[Problem]:

    settings = config.get("report", {})
    causes = "|".join(re.escape(cause) for cause in (*CAUSES, *settings.get("causes", ())))
    cause_pattern = re.compile(rf"cause:\s*({causes})(?![a-z]|\s*\|)", re.I)
    problems = check_report(report, cause_pattern)
    problems += check_length(report, get_max_chars(settings))
    problems += check_claims(report, event, str(root), get_scratch(root, config), found.blocks, found.failed, found.outputs)

    return problems


def find_running_jobs(path: Path, outputs: dict[str, str], /) -> list[str]:

    launched: dict[str, str] = {}
    finished: set[str] = set()
    for line in read_events(path):
        content = (line.get("message") or {}).get("content") if line.get("type") == "assistant" else None
        for block in content if isinstance(content, list) else ():
            is_background = isinstance(block, dict) and block.get("name") == "Bash" and (block.get("input") or {}).get("run_in_background") is True
            if is_background and "in background" in outputs.get(block.get("id"), ""):
                launched[block["id"]] = str((block.get("input") or {}).get("command") or "")
        finished.update(tool_id for tool_id, status in NOTIFICATION.findall(get_notice_text(line)) if status in FINISHED_STATUSES)

    return [command for tool_id, command in launched.items() if tool_id not in finished]


def make_job_text(commands: list[str], /) -> str:

    shown = "; ".join(f"`{' '.join(command.split())[:JOB_SHOWN_CHARS]}`" for command in commands)

    return (
        f"{len(commands)} background command(s) you started are still running: {shown}. Stop each one you no longer need with the "
        f"TaskStop tool (KillShell, if that is the name in your tool list), or wait for its completion notice if you need its result; then report"
    )


def names_jobs(report: str, commands: list[str], /) -> bool:

    sections = dict(read_sections(report))
    text = " ".join(sections.get("Not proven", [])).lower()
    named = [" ".join(command.split())[:JOB_NAMED_CHARS].lower() for command in commands]

    return "running" in text or any(name and name in " ".join(text.split()) for name in named)


def get_job_problems(report: str, commands: list[str], job_tries: int, tries: int, /) -> list[Problem]:

    if not commands:
        return []
    if job_tries < MAX_JOB_SEND_BACKS:
        return [Problem("Answer", make_job_text(commands))]
    if tries < MAX_SEND_BACKS and not names_jobs(report, commands):
        return [Problem("Not proven", "a background command is still running after the send-backs; name it here as left running, with the command that stops it")]

    return []


def check_handback(event: dict, /) -> int:

    root, config = find_project(event.get("cwd") or os.getcwd())
    report = (event.get("tool_input") or {}).get("message")
    tries = get_send_backs(event)
    job_tries = get_job_send_backs(event)
    if not event.get("agent_id") or not is_judged(event) or not isinstance(report, str):
        return 0
    path = get_agent_path(event)
    found = read_assistant_blocks(str(path)) if path is not None else AssistantBlocks([], {}, None, {})
    judged = {**event, "agent_transcript_path": str(path)} if path is not None else event
    problems = get_problems(report, judged, root, config, found) if tries < MAX_SEND_BACKS else []
    running = find_running_jobs(path, found.outputs) if path is not None else []
    has_form_problem = bool(problems)
    cannot = get_cannot_problems(report, judged, found) if tries < MAX_SEND_BACKS else []
    problems += cannot
    has_form_problem = has_form_problem or bool(cannot)
    problems += get_job_problems(report, running, job_tries, tries)
    if not problems:
        note = get_tics_note(report)
        if note:
            print(json.dumps({"systemMessage": note}))
        return 0
    if cannot:
        write_atomic(get_cannot_path(event), "1")
    if running and job_tries < MAX_JOB_SEND_BACKS:
        write_atomic(get_jobs_path(event), str(job_tries + 1))
    if has_form_problem or any(problem.section == "Not proven" for problem in problems):
        write_atomic(get_send_backs_path(event), str(tries + 1))
    print(make_send_back(problems, is_handback=True), file=sys.stderr)

    return 2


def is_judged(event: dict, /) -> bool:

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
    cannot = get_cannot_problems(report, event, found) if tries < MAX_SEND_BACKS else []
    problems += cannot
    extra = get_extra(event, found.blocks, found.failed, found.model, config, name, str(root))
    texts = [problem.text for problem in problems]
    if not problems:
        finish(event, str(root), name, report, [], extra)
        note = get_tics_note(report)
        if note:
            print(json.dumps({"systemMessage": note}))
        return 0
    listed = "; ".join(texts)
    has_ended = bool(found.blocks) and found.blocks[-1].get("name") == HANDBACK_TOOL or (os.path.isfile(path) and not sent)
    if has_ended or tries >= MAX_SEND_BACKS:
        finish(event, str(root), name, report, texts, extra)
        cause = "and it has already ended" if has_ended else f"after {tries} send-backs"
        warning = f"Sub-agent {name} stopped with a bad report {cause}: {listed}"
        print(json.dumps({"systemMessage": warning}))
        return 0
    write_atomic(get_send_backs_path(event), str(tries + 1))
    if cannot:
        write_atomic(get_cannot_path(event), "1")
    write_atomic(get_kept_path(event), json.dumps({"raw": sent, "merged": report}))
    reason = make_send_back(problems)
    print(json.dumps({"decision": "block", "reason": reason}))

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"the harness report gate failed and let the agent stop: {error!r}", file=sys.stderr)
        sys.exit(1)
