#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""SessionStart and SubagentStart hook: in every project, tells a session what it owes.

Both get the `tool-habits` skill and the setup facts that cost past agents a refused call: which tools may be missing, the shell, and the scratch folder. SessionStart tells the main session to load `harness:orchestrator`. SubagentStart tells any agent
the report form, the last lessons handled for its role and the open problems a retro kept. SessionStart also
says when ten or more reports of the project are newer than the plugin data folder's `retro-marker` file (the `retro` skill
writes it). The text reaches the model as `additionalContext`.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from common import (
    FEEDBACK_FOLDER,
    FILE_EDGES,
    HANDLED,
    IGNORE_FILE,
    INBOX,
    OLD_FEEDBACK_FOLDER,
    OPEN_PROBLEMS,
    PLUGIN_PREFIX,
    SCRATCH_FOLDER,
    data_folder,
    ensure_harness_folder,
    ensure_ignored_folder,
    find_project,
    get_feedback_root,
    is_project_root,
)

SESSION_TEXT = "This project runs under the harness plugin. Load the `harness:orchestrator` skill before anything else."
HABITS_SKILL = Path("skills") / "tool-habits" / "SKILL.md"
HABITS_FALLBACK = "Use few tool turns; each one costs the owner time. Load the `harness:tool-habits` skill before shell work."
TOOLS_TEXT = "If Grep or Glob is not among your tools, use `rg` and `find` through Bash."
ZSH_TEXT = "The shell is zsh: quote every glob, and read exit codes from `$pipestatus`, not `$PIPESTATUS`."
# An agent may lack the Skill tool, so the headings come in the text itself.
FORM_TEXT = (
    "End with the `harness:report` report, each section under its exact ## heading, in this order: Answer, Not proven, then "
    "only if they have something to say Problems, Next time, Open and Feedback, then Verdict, which opens with done, partial or "
    "blocked. A hook sends back a report that breaks the form."
)
LESSONS_HEADING = (
    "Past feedback to this role. Each item was already acted on; its rule now lives in the file named. "
    "Read that file if it touches your task; do not redo the request:"
)
PROBLEMS_HEADING = (
    "Problems a retro found for your role that no rule fixes yet. Avoid them, "
    "or name one under Problems if you hit it:"
)
MAX_PROBLEMS = 2
# Characters of an inbox text kept in a lesson line.
MAX_LESSON_TEXT = 140
AUTO_PREFIX = "[auto]"
MAX_LESSONS = 5
# Characters of the lessons text, heading included.
MAX_LESSONS_CHARS = 600
RETRO_ROWS = 10
# Name the plugin versions before this layout gave the project folders.
OLD_SCRATCH = "scratch"
RETRO_MARKER = "retro-marker"
INBOX_LINE = re.compile(r"^- id=([0-9a-f]{8}) session=\S+ agent=(\S+) (?:time=\S+ )?(.+)$", re.M)
OPEN_LINE = re.compile(r"^- ([\w-]+): (.+)$", re.M)
RULE_LINE = re.compile(r"^([0-9a-f]{8}): rule written in[ \t]*(\S+)", re.M)
LEDGER_TIME = "%Y-%m-%dT%H:%M:%S%z"


def get_setup_text(config: dict, /) -> str:  # config keys
    """The facts of this machine and project that a first call would otherwise learn from a refusal."""

    guard = config.get("guard", {})
    lines = [TOOLS_TEXT]
    if os.path.basename(os.environ.get("SHELL") or "") == "zsh":
        lines.append(ZSH_TEXT)
    if guard.get("scratch"):
        lines.append(f"Throwaway files go in `{guard['scratch']}/`.")
    if guard.get("no_tmp"):
        lines.append(f"A write under `/tmp` runs, with a note: throwaway files go in `{guard.get('scratch') or SCRATCH_FOLDER}/`, even where the environment names a scratchpad under `/tmp`.")

    return " ".join(lines)


def prepare_folders(root: Path, /) -> list[str]:
    """Moves an old feedback folder into `__harness__/`, makes both folders self-ignoring, and returns the notes for the session.

    Nothing runs in a start folder that is no project root. An old `scratch/` folder is only mentioned, never touched.
    """

    if not is_project_root(root):
        return []

    notes: list[str] = []
    old_feedback = root / OLD_FEEDBACK_FOLDER
    new_feedback = root / FEEDBACK_FOLDER
    if (root / OLD_SCRATCH).is_dir() and not (root / SCRATCH_FOLDER / IGNORE_FILE).exists():
        notes.append(f"The old `{OLD_SCRATCH}/` folder is left alone; throwaway files go in `{SCRATCH_FOLDER}/` now.")
    ensure_harness_folder(root)
    ensure_ignored_folder(root / SCRATCH_FOLDER)
    if old_feedback.is_dir() and not new_feedback.exists():
        try:
            os.rename(old_feedback, new_feedback)
            notes.append(f"Moved `{OLD_FEEDBACK_FOLDER}/` to `{FEEDBACK_FOLDER}/`.")
        except OSError:
            pass

    return notes


def get_habits_text() -> str:
    """The body of the `tool-habits` skill, so every session and sub-agent starts with it; a short pointer when it cannot be read."""

    plugin = Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or Path(__file__).resolve().parent.parent)
    try:
        text = (plugin / HABITS_SKILL).read_text()
    except OSError:
        return HABITS_FALLBACK
    body = text.split("---", 2)[-1].strip()

    return body or HABITS_FALLBACK


def get_lessons(root: Path, agent_type: str, /) -> str:
    """The role's last handled lessons (no auto items, no vanished rule file), newest last, within the character limit; empty when there are none or a file fails."""

    role = agent_type.removeprefix(PLUGIN_PREFIX)
    feedback = get_feedback_root(root)
    try:
        inbox = (feedback / INBOX).read_text(errors="replace")
        handled = (feedback / HANDLED).read_text(errors="replace")
    except OSError:
        return ""
    files = {item_id: name.strip(FILE_EDGES) for item_id, name in RULE_LINE.findall(handled)}
    lines = [
        f"- (rule in {files[item_id]}) {text.strip()[:MAX_LESSON_TEXT]}"
        for item_id, owner, text in INBOX_LINE.findall(inbox)
        if owner == role and item_id in files and not text.lstrip().startswith(AUTO_PREFIX) and (root / files[item_id]).exists()
    ]
    lines = lines[-MAX_LESSONS:]
    while len(lines) > 1 and len(LESSONS_HEADING + "".join(f"\n{line}" for line in lines)) > MAX_LESSONS_CHARS:
        lines.pop(0)
    if not lines:
        return ""

    return (LESSONS_HEADING + "".join(f"\n{line}" for line in lines))[:MAX_LESSONS_CHARS]


def get_open_problems(root: Path, agent_type: str, /) -> str:
    """The first problems a retro kept for this role or for all, at most MAX_PROBLEMS; empty when there are none."""

    role = agent_type.removeprefix(PLUGIN_PREFIX)
    try:
        text = (get_feedback_root(root) / OPEN_PROBLEMS).read_text(errors="replace")
    except OSError:
        return ""
    problems = [problem.strip()[:MAX_LESSON_TEXT] for owner, problem in OPEN_LINE.findall(text) if owner in (role, "all")]
    lines = problems[:MAX_PROBLEMS]

    return PROBLEMS_HEADING + "".join(f"\n- {line}" for line in lines) if lines else ""


def get_retro_line(root: Path, /) -> str:
    """The line telling a retro is due when ten reports of the project are newer than the retro marker, else empty."""

    folder = data_folder()
    ledger = folder / "ledger.jsonl"
    if not ledger.is_file():
        return ""
    marker = folder / RETRO_MARKER
    try:
        since = marker.stat().st_mtime if marker.exists() else 0.0
        lines = ledger.read_text(errors="replace").splitlines()
    except OSError:
        return ""
    count = 0
    for line in lines:
        try:
            row = json.loads(line)
            is_new = row.get("project") == str(root) and datetime.strptime(row["time"], LEDGER_TIME).timestamp() > since
        except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
            continue
        count += is_new

    return f"{count} reports since the last retro: run harness:retro." if count >= RETRO_ROWS else ""


def main() -> int:
    event = json.load(sys.stdin)
    root, config = find_project(event.get("cwd") or os.getcwd())
    name = event.get("hook_event_name")
    text = ""
    habits = get_habits_text()
    if name == "SessionStart":
        notes = " ".join(prepare_folders(root))
        text = "\n".join(part for part in (SESSION_TEXT, habits, get_setup_text(config), notes, get_retro_line(root)) if part)
    elif name == "SubagentStart":
        agent_type = event.get("agent_type") or ""
        text = "\n\n".join(part for part in (FORM_TEXT, habits, get_setup_text(config), get_lessons(root, agent_type), get_open_problems(root, agent_type)) if part)
    if text:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": name, "additionalContext": text}}))

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # a bug in a context hook must not stop a session
        print(f"the harness context hook failed: {error!r}", file=sys.stderr)
        sys.exit(1)
