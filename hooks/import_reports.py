#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import NamedTuple

from common import HANDBACK_TOOL, read_events
from nudge import get_turn_stats
from report_gate import CAUSES, read_sections

SCORES = ("Task", "Brief", "Ease")

CAUSE = re.compile(rf"cause:\s*({'|'.join(CAUSES)})", re.I)
TASK = re.compile(r"[1-5](/5)?")


def get_scores(lines: list[str], /) -> dict[str, str]:

    scores: dict[str, str] = {}
    for line in lines:
        if line.lstrip().startswith("|"):
            cells = [cell.strip() for cell in line.split("|")]
            if len(cells) > 2:
                scores.setdefault(cells[1], cells[2])

    return scores


class FoundReport(NamedTuple):

    text: str
    event: dict


def find_report(events: list[dict], /) -> FoundReport:

    for event in reversed(events):
        if event.get("type") != "assistant":
            continue
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        blocks = [block for block in content if isinstance(block, dict)]
        for block in reversed(blocks):
            if block.get("type") == "tool_use" and block.get("name") == HANDBACK_TOOL:
                handback = block.get("input")
                return FoundReport(str(handback.get("message", "") if isinstance(handback, dict) else ""), event)
        text = "\n".join(str(block.get("text", "")) for block in blocks if block.get("type") == "text")
        if text.strip():
            return FoundReport(text, event)

    return FoundReport("", {})


def read_role(path: Path, /) -> str:

    try:
        return str(json.loads(path.with_suffix(".meta.json").read_text()).get("agentType") or "unknown")
    except (OSError, ValueError):
        return "unknown"


def make_row(path: Path, /) -> dict | None:

    events = read_events(path)
    report, last = find_report(events)
    sections = dict(reversed(read_sections(report)))
    if "REPORT CARD" not in sections:
        return None
    scores = get_scores(sections["REPORT CARD"])
    if not TASK.fullmatch(scores.get("Task", "").strip()):
        scores = {}
    causes = CAUSE.findall("\n".join(sections.get("PROBLEMS MET", sections.get("Problems", []))))

    return {
        "time": last.get("timestamp") or time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "project": next((e["cwd"] for e in events if e.get("cwd")), None),
        "session": next((e["sessionId"] for e in events if e.get("sessionId")), None),
        "agent_id": path.stem.removeprefix("agent-"),
        "role": read_role(path),
        "accepted": True,
        "send_backs": 0,
        "open_problems": [],
        "scores": {name: scores.get(name) for name in SCORES} if scores else None,
        "causes": [cause.strip().lower() for cause in causes],
        "tool_turns": get_turn_stats(events),
        "report": report,
        "imported": True,
    }


def read_known(ledger: Path, /) -> set[str]:

    known: set[str] = set()
    if ledger.is_file():
        for line in ledger.read_text(errors="replace").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                known.add(str(row.get("agent_id")))

    return known


def main() -> int:
    parser = argparse.ArgumentParser(description="Import past sub-agent report cards into the ledger.")
    parser.add_argument("--ledger", help="ledger file; default $CLAUDE_PLUGIN_DATA/ledger.jsonl")
    parser.add_argument("--source", action="append", help="folder of project transcripts; default ~/.claude/projects")
    parser.add_argument("--dry-run", action="store_true", help="print counts, write nothing")
    args = parser.parse_args()

    ledger: Path | None = None
    if args.ledger:
        ledger = Path(args.ledger)
    elif os.environ.get("CLAUDE_PLUGIN_DATA"):
        ledger = Path(os.environ["CLAUDE_PLUGIN_DATA"]) / "ledger.jsonl"
    elif not args.dry_run:
        print("harness-import: pass --ledger PATH or set CLAUDE_PLUGIN_DATA", file=sys.stderr)
        return 2

    paths: list[Path] = []
    for source in args.source or [str(Path.home() / ".claude" / "projects")]:
        folder = Path(source).expanduser()
        if not folder.is_dir():
            print(f"harness-import: warning: source {folder} is not a folder; nothing read from it", file=sys.stderr)
            continue
        paths += sorted(folder.glob("*/*/subagents/agent-*.jsonl"))

    known = read_known(ledger) if ledger else set()
    rows: list[dict] = []
    seen = skipped = 0
    for path in paths:
        row = make_row(path)
        if row is None:
            continue
        seen += 1
        if row["agent_id"] in known:
            skipped += 1
        else:
            rows.append(row)

    print(f"transcripts: {len(paths)}; with a report card: {seen}; already in ledger: {skipped}; to add: {len(rows)}")
    if rows and not args.dry_run and ledger:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with open(ledger, "ab+") as binary:
            binary.seek(0, os.SEEK_END)
            has_text = binary.tell() > 0
            if has_text:
                binary.seek(-1, os.SEEK_END)
            lacks_newline = has_text and binary.read(1) != b"\n"
        with open(ledger, "a") as file:
            if lacks_newline:
                file.write("\n")
            for row in rows:
                file.write(json.dumps(row) + "\n")
        print(f"wrote {len(rows)} rows to {ledger}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
