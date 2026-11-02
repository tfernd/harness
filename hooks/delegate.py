#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""PreToolUse hook on Bash, Write, Edit and NotebookEdit: in a project whose `.harness.json` has a `delegate` key, the main
session hands its edits and runs to agents. A call that carries `agent_id` came from a sub-agent and passes.

`delegate.write_allow` holds globs relative to the project root, matched with fnmatch (its `*` also matches `/`, so `docs/*` covers `docs/a/b.md`); a file outside them is refused,
apart from `harness-feedback/handled.md`. `delegate.bash_allow` adds prefixes to DEFAULT_BASH_ALLOW; each simple command of
a Bash call must start with one, whole word by whole word, so `git status && make x` is refused. A shell redirect into
a file is refused too, since it would be an edit. `$(cat <<'EOF' ...)`, the form of a commit message, reads no file: a
bare `cat` (the word `cat` alone, with no argument) is allowed.
"""

from __future__ import annotations

import fnmatch
import json
import os
import sys
from pathlib import Path

from common import HANDLED, find_project
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
# The redirect target that writes no file.
NULL_DEVICE = "/dev/null"
ADVICE = "the main session delegates edits and runs in this project (`harness:orchestrator`): give this to an agent."


def is_allowed_segment(segment: Segment, prefixes: list[list[str]], /) -> bool:
    """Whether a simple command starts with an allowed prefix, whole words, and writes no file through a redirect."""

    words = [word.text for word in segment.words]
    if any(target != NULL_DEVICE for target in segment.redirects):
        return False
    if words == ["cat"]:
        return True

    # `git -C dir status` runs the same command as `git status`.
    while words[:1] == ["git"] and words[1:2] in (["-C"], ["-c"]):
        words = ["git", *words[3:]]

    return any(words[: len(prefix)] == prefix for prefix in prefixes)


def check_bash(command: str, settings: dict, /) -> str:  # keys are data
    """The first simple command that is not allowed, or an empty string."""

    allowed = [*DEFAULT_BASH_ALLOW, *settings.get("bash_allow", ())]
    prefixes = [prefix.split() for prefix in allowed if prefix.split()]
    for segment in get_segments(command):
        if not is_allowed_segment(segment, prefixes):
            return " ".join(word.text for word in segment.words)[:80] or "a redirect"

    return ""


def is_allowed_path(path: str, root: Path, settings: dict, cwd: str, /) -> bool:  # keys are data
    """Whether a file lies in the project and matches `write_allow`, or is the handled file."""

    resolved = Path(os.path.realpath(os.path.join(cwd, path)))
    if root not in resolved.parents:
        return False
    relative = resolved.relative_to(root).as_posix()
    if relative == HANDLED:
        return True

    return any(fnmatch.fnmatch(relative, pattern) for pattern in settings.get("write_allow", ()))


def main() -> int:
    event = json.load(sys.stdin)
    if event.get("agent_id"):
        return 0
    cwd = event.get("cwd") or os.getcwd()
    root, config = find_project(cwd)
    if root is None or "delegate" not in config:
        return 0
    settings = config["delegate"] or {}
    tool_input = event.get("tool_input") or {}
    if event.get("tool_name") == "Bash":
        refused = check_bash(tool_input.get("command") or "", settings)
        if not refused:
            return 0
        message = f"`{refused}` is not on this project's list of main-session commands, or it redirects into a file"
    else:
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if is_allowed_path(path, root, settings, cwd):
            return 0
        message = f"{path} is not under this project's `delegate.write_allow`"
    print(f"Blocked by the harness delegate rule: {message}; {ADVICE}", file=sys.stderr)

    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # a bug in the rule must not block every call
        print(f"the harness delegate rule failed and let the call run: {error!r}", file=sys.stderr)
        sys.exit(1)
