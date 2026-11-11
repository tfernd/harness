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
import sys
from pathlib import Path

from common import (
    ensure_scratch_folder,
    ensure_state_folder,
    find_project,
    get_scratch_folder,
    is_project_root,
)

SESSION_TEXT = "This project runs under the harness plugin. Load the `harness:orchestrator` skill before anything else."
HABITS_SKILL = Path("skills") / "tool-habits" / "SKILL.md"
HABITS_FALLBACK = "Use few tool turns; each one costs the owner time. Load the `harness:tool-habits` skill before shell work."
OWNERSHIP_TEXT = "This codebase is yours: what it is for and how it is built are your call, and you will keep building on it."
TOOLS_TEXT = "If Grep or Glob is not among your tools, use `rg` and `find` through Bash."
ZSH_TEXT = "The shell is zsh: quote every glob, and read exit codes from `$pipestatus`, not `$PIPESTATUS`."
FORM_TEXT = (
    "End with the `harness:report` report, each section under its exact ## heading, in this order: Answer, Not proven, then "
    "only if they have something to say Problems, Next time, Open and Feedback, then Verdict, which opens with done, partial or "
    "blocked. A hook sends back a report that breaks the form."
)


def get_setup_text(root: Path, /) -> str:

    lines = [TOOLS_TEXT]
    if os.path.basename(os.environ.get("SHELL") or "") == "zsh":
        lines.append(ZSH_TEXT)
    lines.append(f"Throwaway files go in `{get_scratch_folder(root)}/`, a subfolder per run, even where the environment names a scratchpad elsewhere.")

    return " ".join(lines)


def prepare_folders(root: Path, /) -> None:

    if is_project_root(root):
        ensure_state_folder(root)
        ensure_scratch_folder(root)


def get_habits_text() -> str:

    plugin = Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or Path(__file__).resolve().parent.parent)
    try:
        text = (plugin / HABITS_SKILL).read_text()
    except OSError:
        return HABITS_FALLBACK
    body = text.split("---", 2)[-1].strip()

    return body or HABITS_FALLBACK


def main() -> int:
    event = json.load(sys.stdin)
    root, _ = find_project(event.get("cwd") or os.getcwd())
    name = event.get("hook_event_name")
    text = ""
    habits = get_habits_text()
    if name == "SessionStart":
        prepare_folders(root)
        is_main = not event.get("agent_id")
        text = "\n".join(part for part in (SESSION_TEXT, OWNERSHIP_TEXT if is_main else "", habits, get_setup_text(root)) if part)
    elif name == "SubagentStart":
        text = "\n\n".join(part for part in (FORM_TEXT, habits, get_setup_text(root)) if part)
    if text:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": name, "additionalContext": text}}))

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"the harness context hook failed: {error!r}", file=sys.stderr)
        sys.exit(1)
