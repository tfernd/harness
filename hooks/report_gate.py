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
from pathlib import Path
from typing import NamedTuple

from budget import get_agent_path
from common import HANDBACK_TOOL, PLUGIN_PREFIX, data_folder, find_project, get_fenced_indices, get_unfenced_lines, write_atomic

ORDER = ("Answer", "Not proven", "Problems", "Next time", "Open", "Feedback", "Verdict")
REQUIRED = ("Answer", "Not proven", "Verdict")
ANSWER_HEADING = re.compile(r"^## Answer\s*$", re.M)
SECTION_HEADING = re.compile(rf"^## ({'|'.join(ORDER)})\s*$", re.M)
REPORT_TITLE = re.compile(r"^# Report: [^,\n]*, *(.+?)\s*$", re.M)
MAX_SEND_BACKS = 3
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


def get_headings(report: str, /) -> list[str]:

    return [line[3:].strip() for line in get_unfenced_lines(report) if line.startswith("## ")]


def check_headings(names: list[str], /) -> list[Problem]:

    problems = [Problem(heading, f"missing: {heading}") for heading in REQUIRED if heading not in names]
    problems += [Problem(name, f"not a section of the form: {name} (leave it out)") for name in dict.fromkeys(names) if name not in ORDER]
    problems += [Problem(heading, f"duplicated: {heading}") for heading in ORDER if names.count(heading) > 1]
    known = [name for name in dict.fromkeys(names) if name in ORDER]
    problems += [Problem(name, f"out of order: {name}") for name, expected in zip(known, sorted(known, key=ORDER.index), strict=True) if name != expected]
    if "Verdict" in names and names[-1] != "Verdict":
        problems.append(Problem("Verdict", "Verdict must be the last section"))

    return problems


def check_report(report: str, /) -> list[Problem]:

    return check_headings(get_headings(report))


def read_assistant_blocks(path: str, /) -> list[dict]:

    blocks: list[dict] = []
    with open(path, errors="replace") as file:
        for line in file:
            try:
                entry = json.loads(line)
                content = entry.get("message", {}).get("content")
            except (ValueError, AttributeError):
                continue
            if entry.get("type") == "assistant":
                blocks += [block for block in content if isinstance(block, dict)] if isinstance(content, list) else []

    return blocks


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

    wrong = list(dict.fromkeys(problem.section for problem in problems))
    lines = [f"- {section}: " + "; ".join(problem.text for problem in problems if problem.section == section) for section in wrong]
    ask = (
        f"Call {HANDBACK_TOOL} again with the whole report, these sections fixed; the main session gets only what that call carries."
        if is_handback
        else "Send again only these sections, each as its `## ` heading line and its body; every other section stays as it was."
    )

    return "Your report breaks the report skill's form in these sections only:\n" + "\n".join(lines) + "\n" + ask


def finish(event: dict, /) -> None:

    for stale in (get_send_backs_path(event), get_kept_path(event)):
        if stale.exists():
            stale.unlink()


def is_awaited(report: str, kept: Kept | None, /) -> bool:

    heading = ANSWER_HEADING if kept is None else SECTION_HEADING

    return not heading.search(report) or (kept is not None and report == kept.raw)


def wait_for_report(event: dict, path: str, kept: Kept | None, /) -> list[dict]:

    blocks = read_assistant_blocks(path)
    waited = 0.0
    while is_awaited(get_report(event, blocks, is_resend=kept is not None), kept) and waited < REPORT_WAIT_S:
        time.sleep(REPORT_POLL_S)
        waited += REPORT_POLL_S
        blocks = read_assistant_blocks(path)

    return blocks


def check_handback(event: dict, /) -> int:

    report = (event.get("tool_input") or {}).get("message")
    if not event.get("agent_id") or not is_judged(event) or not isinstance(report, str):
        return 0
    if get_send_backs(event) >= MAX_SEND_BACKS:
        return 0
    problems = check_report(report)
    if not problems:
        return 0
    write_atomic(get_send_backs_path(event), str(get_send_backs(event) + 1))
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
    name = (event.get("agent_type") or "").removeprefix(PLUGIN_PREFIX)
    path = event.get("agent_transcript_path") or ""
    tries = get_send_backs(event)
    kept = get_kept(event, tries)
    blocks = wait_for_report(event, path, kept) if os.path.isfile(path) else []
    sent = get_report(event, blocks, is_resend=kept is not None)
    report = merge_reports(kept.merged, sent) if kept and sent else (kept.merged if kept else sent)
    problems = check_report(report)
    if not problems:
        finish(event)
        return 0
    listed = "; ".join(problem.text for problem in problems)
    has_ended = bool(blocks) and blocks[-1].get("name") == HANDBACK_TOOL or (os.path.isfile(path) and not sent)
    if has_ended or tries >= MAX_SEND_BACKS:
        finish(event)
        cause = "and it has already ended" if has_ended else f"after {tries} send-backs"
        print(json.dumps({"systemMessage": f"Sub-agent {name} stopped with a bad report {cause}: {listed}"}))
        return 0
    write_atomic(get_send_backs_path(event), str(tries + 1))
    write_atomic(get_kept_path(event), json.dumps({"raw": sent, "merged": report}))
    print(json.dumps({"decision": "block", "reason": make_send_back(problems)}))

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"the harness report gate failed and let the agent stop: {error!r}", file=sys.stderr)
        sys.exit(1)
