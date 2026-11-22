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
from collections import Counter, defaultdict
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import NamedTuple

GUARD_PREFIX = "Blocked by the harness guard"
COMMIT_PREFIX = "Blocked by the harness commit rule"
GUARD_ID_PATTERN = re.compile(r"^ \(rule: ([\w-]+)\): ")
COMMIT_CLAUSE_PATTERN = re.compile(r"^\s*(?:\([^)]*\))?:?\s*")
PLUGIN_PATTERN = re.compile(r"(?i)harness|hooks?\b|skills?\b|guard|(?<![a-z])gate|plugin|(?:skills|hooks|agents|templates)/|SKILL\.md")
LOG_NAME = "refusals.jsonl"
ID_CHARS = 8
SEARCH_CHARS = 40
COMMIT_CLAUSE_CHARS = 50
SENDBACK_FRICTION_MIN = 4
SENDBACK_TEXT = "Your report breaks the report skill's form"
VERSION_PATTERN = re.compile(r"plugins/cache/harness/harness/([0-9a-f]{6,40})")
CAUSE_PATTERN = re.compile(r"\(cause:\s*([^)]*)\)")
SECTION_PATTERN = re.compile(r"^- ([^:]+): ")
DATE_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})")
SAMPLE_CHARS = 160
RULE_KEY_CHARS = 60
SAMPLES_PER_RULE = 3
FRICTION_MIN_REFUSALS = 3
RETRY_WINDOW_CALLS = 3
RETRY_MIN_SIMILARITY = 0.9
SIGNATURE_CHARS = 600
MAX_LINES_PER_SECTION = 10
DEFAULT_DAYS = 7
EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
SCRATCH_PARTS = ("/tmp/", "/.local/state/", "/.claude/", "/.cache/")
BASH_WRITE_PATTERN = re.compile(r"write_text\(|\.write\(|\bsed\s+-i|\bperl\s+-pi|\bapply_patch\b|\bgit\s+apply\b|>\s*[^\s&|<>]+\s*<<|\btee\s+[^\s|]+\s*<<")
HEREDOC_PATTERN = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n.*?\n\s*\1\b", re.S)
CHECK_PATTERN = re.compile(r"(?:^|&&|\|\||;|\n|\(|\bthen\b|\bdo\b)\s*(?:(?:uv\s+run\s+(?:--\S+\s+)*|uvx\s+|npx\s+|python3?\s+-m\s+)*)(?:pytest|make\s+(?:-\S+\s+)*(?:test|check|lint|types?|typecheck|band|cases)|ruff\s+check|ty\s+check|mypy|pyright|tsc|(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:test|lint|check|typecheck)|cargo\s+(?:test|check|clippy)|go\s+(?:test|vet)|\S*(?:run_cases|check_skills|check_leaks)\.py|claude\s+plugin\s+(?:validate|test))\b")
RHYTHM_MANY_CHECKS = 4


class Refusal(NamedTuple):
    rule: str
    search: str
    sample: str
    is_sub_agent: bool
    is_retried: bool
    where: str
    time: str


class Scan(NamedTuple):
    refusals: list[Refusal]
    sendbacks: list[tuple[str, str, str]]
    stop_blocks: list[str]
    versions: dict[str, set[str]]


class Rhythm(NamedTuple):
    is_sub_agent: bool
    num_edits: int
    num_checks: int
    num_checks_after_few_edits: int
    num_checks_with_edit_in_call: int


class ReportNotes(NamedTuple):
    problems: list[str]
    feedback: list[str]
    num_project_items: int


class RuleKey(NamedTuple):
    rule: str
    search: str


def cut(text: str, /, *, limit: int = SAMPLE_CHARS) -> str:
    one_line = " ".join(text.split())
    return one_line[:limit]


def make_slug(project_dir: Path, /) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(project_dir))


def read_entries(path: Path, /) -> Iterator[dict]:
    with open(path, errors="replace") as file:
        for line in file:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict):
                yield entry


def is_in_window(entry: dict, cutoff: datetime, /) -> bool:
    stamp = entry.get("timestamp")
    if not isinstance(stamp, str):
        return True
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")) >= cutoff
    except ValueError:
        return True


def get_text(content: object, /) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = [block.get("text", "") if block.get("type") == "text" else get_text(block.get("content")) for block in content if isinstance(block, dict)]
    return "\n".join(part for part in parts if isinstance(part, str))


def make_signature(tool_input: object, /) -> str:
    if isinstance(tool_input, dict):
        for key in ("command", "file_path", "prompt"):
            if isinstance(tool_input.get(key), str):
                return tool_input[key][:SIGNATURE_CHARS]
    return json.dumps(tool_input, sort_keys=True)[:SIGNATURE_CHARS]


def make_search_pattern(text: str, /) -> str:
    return cut(text.replace("`", ""), limit=SEARCH_CHARS)


def make_rule_key(text: str, /) -> RuleKey:
    if text.startswith(COMMIT_PREFIX):
        clause = COMMIT_CLAUSE_PATTERN.sub("", text[len(COMMIT_PREFIX) :], count=1)
        return RuleKey("commit rule: " + cut(clause.split(". ", 1)[0], limit=COMMIT_CLAUSE_CHARS), "")
    rest = text[len(GUARD_PREFIX) :]
    identified = GUARD_ID_PATTERN.match(rest)
    if identified:
        return RuleKey(identified.group(1), "")
    body = rest[2:] if rest.startswith(": ") else rest
    key = cut(body.split(". ", 1)[0], limit=RULE_KEY_CHARS)
    return RuleKey(key, make_search_pattern(key))


def find_refusal_text(text: str, /) -> str | None:
    if COMMIT_PREFIX in text:
        return COMMIT_PREFIX + text.split(COMMIT_PREFIX, 1)[1]
    if GUARD_PREFIX in text:
        return GUARD_PREFIX + text.split(GUARD_PREFIX, 1)[1]
    return None


def make_where(path: Path, entry: dict, /) -> str:
    if "subagents" in path.parts:
        return f"transcript {path.parent.parent.name[:ID_CHARS]}, agent {path.stem.removeprefix('agent-')[:ID_CHARS]}"
    agent = entry.get("agentId")
    suffix = f", agent {str(agent)[:ID_CHARS]}" if agent else ""
    return f"transcript {path.stem[:ID_CHARS]}{suffix}"


def read_refusal_log(path: Path, cutoff: datetime, /) -> list[Refusal]:
    refusals: list[Refusal] = []
    if not path.is_file():
        return refusals
    for entry in read_entries(path):
        stamp = entry.get("time")
        if not isinstance(stamp, str) or not isinstance(entry.get("rule"), str):
            continue
        try:
            moment = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        if moment.timestamp() >= cutoff.timestamp():
            refusals.append(Refusal(entry["rule"], "", cut(str(entry.get("text", ""))), entry.get("role") == "sub-agent", False, "refusal log", moment.isoformat()))
    return refusals


def parse_time(stamp: str, /) -> float:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def merge_log_refusals(log: list[Refusal], scanned: list[Refusal], /) -> list[Refusal]:
    if not log:
        return scanned
    first = min(parse_time(refusal.time) for refusal in log)
    older = [refusal for refusal in scanned if not refusal.rule.startswith("commit rule") and parse_time(refusal.time) < first]
    commits = [refusal for refusal in scanned if refusal.rule.startswith("commit rule")]
    return [*log, *older, *commits]


def get_missing_sections(message: str, /) -> str:
    names = [match.group(1) for line in message.splitlines() if (match := SECTION_PATTERN.match(line))]
    return ", ".join(names) or "form"


def get_first_reason(text: str, /) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    reasons = [line for line in lines if line.startswith("- ")]
    return cut((reasons or lines or [""])[0], limit=100)


def scan_transcript(path: Path, cutoff: datetime, /) -> Scan:
    is_sub_path = "subagents" in path.parts
    calls: dict[str, tuple[str, str]] = {}
    refusals: list[dict] = []
    watches: list[dict] = []
    sendbacks: list[tuple[str, str, str]] = []
    stop_blocks: list[str] = []
    versions: dict[str, set[str]] = defaultdict(set)
    for entry in read_entries(path):
        if not is_in_window(entry, cutoff):
            continue
        is_sub = is_sub_path or entry.get("isSidechain") is True
        session = str(entry.get("sessionId") or path.stem)
        message = entry.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        attachment = entry.get("attachment")
        if isinstance(attachment, dict) and attachment.get("type") == "hook_blocking_error":
            blocking = attachment.get("blockingError")
            text = str(blocking.get("blockingError", "")) if isinstance(blocking, dict) else ""
            if attachment.get("hookName") == "SubagentStop" and SENDBACK_TEXT in text:
                sendbacks.append((str(entry.get("agentId") or path.stem), get_missing_sections(text), str(entry.get("timestamp", ""))[:10]))
            if attachment.get("hookName") == "Stop" and not is_sub:
                stop_blocks.append(get_first_reason(text))
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                name = str(block.get("name"))
                signature = make_signature(block.get("input"))
                calls[str(block.get("id"))] = (name, signature)
                for watch in list(watches):
                    if watch["name"] == name and SequenceMatcher(None, watch["signature"], signature).ratio() >= RETRY_MIN_SIMILARITY:
                        refusals[watch["index"]]["is_retried"] = True
                        watches.remove(watch)
                    else:
                        watch["left"] -= 1
                        if watch["left"] <= 0:
                            watches.remove(watch)
            if block.get("type") == "tool_result" and block.get("is_error") is True:
                text = get_text(block.get("content"))
                refusal_text = find_refusal_text(text)
                if refusal_text is None:
                    continue
                name, signature = calls.get(str(block.get("tool_use_id")), ("", ""))
                key = make_rule_key(refusal_text)
                refusals.append({"rule": key.rule, "search": key.search, "sample": cut(signature), "is_sub_agent": is_sub, "is_retried": False, "where": make_where(path, entry), "time": str(entry.get("timestamp", ""))})
                watches.append({"index": len(refusals) - 1, "name": name, "signature": signature, "left": RETRY_WINDOW_CALLS})
            if isinstance(block.get("text"), str) or isinstance(block.get("content"), str):
                raw = str(block.get("text") or block.get("content"))
                for sha in VERSION_PATTERN.findall(raw):
                    versions[session].add(sha)
    found = [Refusal(item["rule"], item["search"], item["sample"], item["is_sub_agent"], item["is_retried"], item["where"], item["time"]) for item in refusals]
    return Scan(found, sendbacks, stop_blocks, versions)


def is_project_edit(name: str, tool_input: dict, /) -> bool:
    if name in EDIT_TOOLS:
        path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        return bool(path) and not any(part in path for part in SCRATCH_PARTS)
    if name != "Bash":
        return False
    command = str(tool_input.get("command") or "")
    if not BASH_WRITE_PATTERN.search(command):
        return False
    return "/tmp/" not in command


def is_check_command(name: str, tool_input: dict, /) -> bool:
    if name != "Bash" or tool_input.get("run_in_background"):
        return False
    bare = HEREDOC_PATTERN.sub("\n", str(tool_input.get("command") or ""))
    return CHECK_PATTERN.search(bare) is not None


def scan_rhythm(path: Path, cutoff: datetime, /) -> Rhythm:
    is_sub = "subagents" in path.parts
    num_edits = num_checks = num_few = num_same_call = 0
    edits_since_check = 0
    for entry in read_entries(path):
        message = entry.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if entry.get("type") != "assistant" or not isinstance(content, list) or not is_in_window(entry, cutoff):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = str(block.get("name"))
            tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
            is_edit = is_project_edit(name, tool_input)
            is_check = is_check_command(name, tool_input)
            num_edits += is_edit
            edits_since_check += is_edit
            if is_check:
                num_checks += 1
                num_few += edits_since_check <= 1
                num_same_call += is_edit
                edits_since_check = 0
    return Rhythm(is_sub, num_edits, num_checks, num_few, num_same_call)


def format_rhythm(rhythms: list[Rhythm], /) -> list[str]:
    lines = []
    for label, is_sub in (("main session", False), ("sub-agent", True)):
        group = [rhythm for rhythm in rhythms if rhythm.is_sub_agent == is_sub]
        editing = [rhythm for rhythm in group if rhythm.num_edits]
        edits = sum(rhythm.num_edits for rhythm in group)
        checks = sum(rhythm.num_checks for rhythm in group)
        if not checks:
            lines.append(f"  {label}: {edits} edits, no checks, {len(editing)} editing of {len(group)}")
            continue
        few = sum(rhythm.num_checks_after_few_edits for rhythm in group)
        same = sum(rhythm.num_checks_with_edit_in_call for rhythm in group)
        many = len([rhythm for rhythm in editing if rhythm.num_checks >= RHYTHM_MANY_CHECKS])
        lines.append(f"  {label}: {edits} edits, {checks} checks, {edits / checks:.2f} edits per check, {100 * few // checks}% of checks after one or no edits, {100 * same // checks}% in the same call as an edit, {many} of {len(editing)} editing agents with {RHYTHM_MANY_CHECKS} or more checks")
    return lines


def find_transcripts(project_folder: Path, cutoff: datetime, /) -> list[Path]:
    if not project_folder.is_dir():
        return []
    cutoff_seconds = cutoff.timestamp()
    paths = [*project_folder.glob("*.jsonl"), *project_folder.glob("*/subagents/*.jsonl")]
    return sorted(path for path in paths if path.stat().st_mtime >= cutoff_seconds)


def read_report_notes(reports_folder: Path, cutoff: datetime, /) -> ReportNotes:
    problems: list[str] = []
    feedback: list[str] = []
    num_project_items = 0
    if not reports_folder.is_dir():
        return ReportNotes(problems, feedback, num_project_items)
    for path in sorted(reports_folder.glob("*.md")):
        date = DATE_PATTERN.match(path.name)
        if not date or datetime.fromisoformat(date.group(1)).replace(tzinfo=timezone.utc) < cutoff.replace(hour=0, minute=0, second=0, microsecond=0):
            continue
        section = ""
        for line in path.read_text(errors="replace").splitlines():
            if line.startswith("## "):
                section = line[3:].strip()
                continue
            if not line.startswith("- "):
                continue
            if section == "Problems":
                cause = CAUSE_PATTERN.search(line)
                if not cause or cause.group(1).strip().startswith("the agent itself"):
                    continue
                is_plugin = PLUGIN_PATTERN.search(line) is not None
                problems.extend([f"{path.name[:10]} {cut(line[2:])}"] if is_plugin else [])
                num_project_items += 0 if is_plugin else 1
            if section == "Feedback":
                is_plugin = PLUGIN_PATTERN.search(line) is not None
                feedback.extend([f"{path.name[:10]} {cut(line[2:])}"] if is_plugin else [])
                num_project_items += 0 if is_plugin else 1
    return ReportNotes(problems, feedback, num_project_items)


def read_installed_version(claude_dir: Path, /) -> str:
    try:
        installed = json.loads((claude_dir / "plugins" / "installed_plugins.json").read_text())
        return str(installed["plugins"]["harness@harness"][0]["version"])
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return "unknown"


def format_refusals(refusals: list[Refusal], /) -> list[str]:
    by_rule: dict[str, list[Refusal]] = defaultdict(list)
    for refusal in refusals:
        by_rule[refusal.rule].append(refusal)
    lines: list[str] = []
    for rule, group in sorted(by_rule.items(), key=lambda item: -len(item[1])):
        num_sub = sum(1 for refusal in group if refusal.is_sub_agent)
        lines.append(f"  {len(group)} x {rule}  (main {len(group) - num_sub}, sub-agent {num_sub})")
        search = next((refusal.search for refusal in group if refusal.search), "")
        if search:
            lines.append(f"      old format, search for: {search}")
        for refusal in group[:SAMPLES_PER_RULE]:
            lines.append(f"      e.g. {refusal.sample}  [{refusal.where}]")
    return lines[: MAX_LINES_PER_SECTION * (SAMPLES_PER_RULE + 2)]


def pluralize(count: int, word: str, /) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def format_friction(transcripts: list[Path], scans: list[Scan], /) -> list[str]:
    lines: list[str] = []
    for path, scan in zip(transcripts, scans):
        counts = Counter(refusal.rule for refusal in scan.refusals)
        for rule, count in counts.items():
            if count >= FRICTION_MIN_REFUSALS:
                lines.append(f"  {path.stem[:ID_CHARS]}: {count} x {rule} in one transcript")
    retried = Counter(refusal.rule for scan in scans for refusal in scan.refusals if refusal.is_retried)
    lines.extend(f"  {pluralize(count, 'refusal')} of {rule} followed by a near-identical retry" for rule, count in retried.most_common() if count >= FRICTION_MIN_REFUSALS)
    repeated = Counter((agent, missing) for scan in scans for agent, missing, _ in scan.sendbacks)
    lines.extend(
        f"  gate friction: agent {agent[:ID_CHARS]} was sent back {count} times for the same missing sections ({missing}); it never saw the report form or could not follow it"
        for (agent, missing), count in repeated.most_common()
        if count >= SENDBACK_FRICTION_MIN
    )
    return lines[:MAX_LINES_PER_SECTION]


def format_versions(scans: list[Scan], installed: str, /) -> list[str]:
    sessions: dict[str, set[str]] = defaultdict(set)
    for scan in scans:
        for session, shas in scan.versions.items():
            sessions[session] |= shas
    loaded = Counter(sha[:12] for shas in sessions.values() for sha in shas)
    lines = [f"  installed: {installed[:12]}"]
    if not loaded:
        lines.append("  loaded by sessions: unknown (no transcript names the plugin folder)")
    for sha, count in loaded.most_common(MAX_LINES_PER_SECTION):
        marker = "" if installed == "unknown" or installed.startswith(sha) else "  (not the installed one)"
        lines.append(f"  {count} session(s) loaded {sha}{marker}")
    return lines


def describe_source(log: list[Refusal], /) -> str:
    if not log:
        return "transcripts only (no refusal log in the window)"
    first = datetime.fromtimestamp(min(parse_time(refusal.time) for refusal in log)).strftime("%Y-%m-%d")
    return f"refusal log {LOG_NAME} from {first} (older guard refusals and commit-rule refusals from transcripts)"


def make_output(project_name: str, days: int, transcripts: list[Path], scans: list[Scan], notes: ReportNotes, installed: str, log: list[Refusal], rhythms: list[Rhythm], /) -> list[str]:
    refusals = merge_log_refusals(log, [refusal for scan in scans for refusal in scan.refusals])
    sendbacks = [sendback for scan in scans for sendback in scan.sendbacks]
    stops = Counter(text for scan in scans for text in scan.stop_blocks)
    if not (refusals or sendbacks or stops or notes.problems or notes.feedback or notes.num_project_items or any(rhythm.num_checks for rhythm in rhythms)):
        return [f"introspect: project {project_name}, last {days} days, {len(transcripts)} transcripts: nothing found"]
    lines = [f"introspect: project {project_name}, last {days} days, {len(transcripts)} transcripts"]
    lines.append(f"== guard and commit refusals: {len(refusals)}")
    lines.append(f"  source: {describe_source(log)}")
    lines.extend(format_refusals(refusals))
    lines.append(f"== report send-backs: {len(sendbacks)}")
    per_agent = Counter(agent for agent, _, _ in sendbacks)
    for agent, count in per_agent.most_common(MAX_LINES_PER_SECTION):
        days = sorted(day for name, _, day in sendbacks if name == agent)
        sections = next(missing for name, missing, _ in sendbacks if name == agent)
        lines.append(f"  agent {agent[:8]}: {count} x, missing {sections}, {days[0]} to {days[-1]}")
    lines.append(f"== stop-gate blocks of the main session: {sum(stops.values())}")
    lines.extend(f"  {count} x {text}" for text, count in stops.most_common(MAX_LINES_PER_SECTION))
    lines.append("== friction")
    lines.extend(format_friction(transcripts, scans))
    lines.append(f"== plugin problems from agent reports: {len(notes.problems)}")
    lines.extend(f"  {line}" for line in notes.problems[:MAX_LINES_PER_SECTION])
    lines.append(f"== plugin feedback from agent reports: {len(notes.feedback)}")
    lines.extend(f"  {line}" for line in notes.feedback[:MAX_LINES_PER_SECTION])
    lines.append(f"== project items (not shown): {notes.num_project_items}")
    lines.append("== check rhythm (edits and checks, aggregate)")
    lines.extend(format_rhythm(rhythms))
    lines.append("== plugin version")
    lines.extend(format_versions(scans, installed))
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Capped aggregates of where the harness plugin got in the way in one project.")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="the window in days")
    parser.add_argument("--project-dir", type=Path, default=Path.cwd(), help="the project folder; its name picks the state folder, its path the transcript folder")
    parser.add_argument("--claude-dir", type=Path, default=Path.home() / ".claude", help="the Claude Code folder")
    parser.add_argument("--state-dir", type=Path, default=Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "harness", help="the plugin state folder")
    arguments = parser.parse_args()
    cutoff = datetime.now(timezone.utc) - timedelta(days=arguments.days)
    project_dir = arguments.project_dir.resolve()
    transcripts = find_transcripts(arguments.claude_dir / "projects" / make_slug(project_dir), cutoff)
    scans = [scan_transcript(path, cutoff) for path in transcripts]
    rhythms = [scan_rhythm(path, cutoff) for path in transcripts]
    notes = read_report_notes(arguments.state_dir / project_dir.name / "reports", cutoff)
    log = read_refusal_log(arguments.state_dir / project_dir.name / LOG_NAME, cutoff)
    installed = read_installed_version(arguments.claude_dir)
    print("\n".join(make_output(project_dir.name, arguments.days, transcripts, scans, notes, installed, log, rhythms)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
