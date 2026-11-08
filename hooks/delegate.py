#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///

from __future__ import annotations

import fcntl
import fnmatch
import json
import os
import sys
from pathlib import Path

from common import EDIT_TOOLS, EDITS_KIND, HANDLED, HARNESS_FOLDER, SCRATCH_FOLDER, data_folder, find_project, is_project_root, make_note_output
from shell import Segment, get_segments

DEFAULT_BASH_ALLOW = (
    "git status",
    "git log",
    "git diff",
    "git show",
    "git add",
    "git commit",
    "gh",
    "ls",
    "rg",
    "head",
    "wc",
)
NULL_DEVICE = "/dev/null"
DEFAULT_MAX_EDITS = 3
DEFAULT_EDIT_ALLOW = (f"{HARNESS_FOLDER}/*", f"{SCRATCH_FOLDER}/*")
ADVICE = "the main session delegates edits and runs in this project (`harness:orchestrator`): give the next one to an agent."


def is_allowed_segment(segment: Segment, prefixes: list[list[str]], /) -> bool:

    words = [word.text for word in segment.words]
    if any(target != NULL_DEVICE for target in segment.redirects):
        return False
    if words == ["cat"]:
        return True

    while words[:1] == ["git"] and words[1:2] in (["-C"], ["-c"]):
        words = ["git", *words[3:]]

    return any(words[: len(prefix)] == prefix for prefix in prefixes)


def check_bash(command: str, settings: dict, /) -> str:

    allowed = [*DEFAULT_BASH_ALLOW, *settings.get("bash_allow", ())]
    prefixes = [prefix.split() for prefix in allowed if prefix.split()]
    for segment in get_segments(command):
        if not is_allowed_segment(segment, prefixes):
            return " ".join(word.text for word in segment.words)[:80] or "a redirect"

    return ""


def is_allowed_path(path: str, root: Path, settings: dict, cwd: str, /) -> bool:

    resolved = Path(os.path.realpath(os.path.join(cwd, path)))
    if root not in resolved.parents:
        return False
    relative = resolved.relative_to(root).as_posix()
    if relative == HANDLED:
        return True

    return any(fnmatch.fnmatch(relative, pattern) for pattern in settings.get("write_allow", ()))


def is_counted_edit(path: str, root: Path, allow: list[str], cwd: str, /) -> bool:

    resolved = Path(os.path.realpath(os.path.join(cwd, path)))
    if root not in resolved.parents:
        return False
    relative = resolved.relative_to(root).as_posix()

    return not any(fnmatch.fnmatch(relative, pattern) for pattern in allow)


def record_edit(session: str, edited: str, maximum: int, root: Path, allow: list[str], cwd: str, /) -> int:

    folder = data_folder() / "turns"
    folder.mkdir(exist_ok=True)
    with open(folder / f"{session}.{EDITS_KIND}", "a+") as file:
        fcntl.flock(file, fcntl.LOCK_EX)
        file.seek(0)
        count = sum(bool(line) and is_counted_edit(line, root, allow, cwd) for line in file.read().splitlines())
        if count < maximum:
            file.write(" ".join(edited.split()) + "\n")

    return count


def check_main_edits(event: dict, root: Path, config: dict, cwd: str, /) -> tuple[str, str]:

    settings = config.get("main_edits") or {}
    maximum = settings.get("max", DEFAULT_MAX_EDITS)
    allow = settings.get("allow", list(DEFAULT_EDIT_ALLOW))
    tool_input = event.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if event.get("tool_name") not in EDIT_TOOLS or not path or not isinstance(path, str) or not isinstance(maximum, int) or maximum <= 0:
        return "", ""
    if not is_project_root(root) or not is_counted_edit(path, root, allow, cwd):
        return "", ""

    count = record_edit(event.get("session_id") or "unknown", path, maximum, root, allow, cwd)
    if count >= maximum:
        refusal = (
            f"Blocked by the harness main_edits rule: this turn's main session has made {count} edits outside "
            f"{', '.join(allow)} and the cap is {maximum}. Hand the change to a `harness:worker` agent with a brief "
            f"(`harness:orchestrator`). Edits under {', '.join(allow)} do not count. A repo raises the cap with "
            f'`"main_edits": {{"max": N}}` in the owner file.'
        )
        return refusal, ""

    note = f"The harness main_edits rule let this edit run: edit {count + 1} of {maximum} this turn; past it, changes go to a `harness:worker` agent (`harness:orchestrator`)."

    return "", note


def check_delegate(event: dict, root: Path, config: dict, cwd: str, /) -> str:

    if "delegate" not in config:
        return ""
    settings = config["delegate"] or {}
    tool_input = event.get("tool_input") or {}
    if event.get("tool_name") == "Bash":
        offending = check_bash(tool_input.get("command") or "", settings)
        if not offending:
            return ""
        message = f"`{offending}` is not on this project's list of main-session commands, or it redirects into a file"
    else:
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if is_allowed_path(path, root, settings, cwd):
            return ""
        message = f"{path} is not under this project's `delegate.write_allow`"

    return f"The harness delegate rule let this call run, but {message}; {ADVICE}"


def main() -> int:
    event = json.load(sys.stdin)
    if event.get("agent_id"):
        return 0
    cwd = event.get("cwd") or os.getcwd()
    root, config = find_project(cwd)
    refusal, edit_note = check_main_edits(event, root, config, cwd)
    if refusal:
        print(refusal, file=sys.stderr)
        return 2
    notes = [note for note in (check_delegate(event, root, config, cwd), edit_note) if note]
    if notes:
        print(json.dumps(make_note_output(" ".join(notes))))

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"the harness delegate rule failed and let the call run: {error!r}", file=sys.stderr)
        sys.exit(1)
