#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""PreToolUse hook on Bash, Write, Edit and NotebookEdit: in a project whose `.harness.json` has a `delegate` key, the main
session hands its edits and runs to agents. The call always runs; one that breaks the rule gets a note in
`additionalContext`. A call that carries `agent_id` came from a sub-agent and passes unchecked.

`delegate.write_allow` holds globs relative to the project root, matched with fnmatch (its `*` also matches `/`, so `docs/*` covers `docs/a/b.md`); a file outside them is noted,
apart from `harness-feedback/handled.md`. `delegate.bash_allow` adds prefixes to DEFAULT_BASH_ALLOW; each simple command of
a Bash call should start with one, whole word by whole word, so `git status && make x` is noted. A shell redirect into
a file is noted too, since it would be an edit. `$(cat <<'EOF' ...)`, the form of a commit message, reads no file: a
bare `cat` (the word `cat` alone, with no argument) is allowed.

The `main_edits` section is separate and on in every project: the main session's Edit, Write or NotebookEdit calls on files
outside `main_edits.allow` (globs relative to the project root) are counted in the turn's calls file, and the call after
`main_edits.max` of them is refused (exit 2); `max` 0 turns it off. Edits made through Bash (a redirect, `sed -i`) are out of
its scope: nothing counts them.
"""

from __future__ import annotations

import fnmatch
import json
import os
import sys
from pathlib import Path

from common import EDIT_TOOLS, HANDLED, data_folder, find_project, make_note_output
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
DEFAULT_MAX_EDITS = 3
DEFAULT_EDIT_ALLOW = ("harness-feedback/*", "scratch/*")
ADVICE = "the main session delegates edits and runs in this project (`harness:orchestrator`): give the next one to an agent."


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


def is_counted_edit(path: str, root: Path, allow: list[str], cwd: str, /) -> bool:
    """Whether an edit of `path` counts toward the cap: it matches no `allow` glob, relative to the project root."""

    resolved = Path(os.path.realpath(os.path.join(cwd, path)))
    if root not in resolved.parents:
        return True
    relative = resolved.relative_to(root).as_posix()

    return not any(fnmatch.fnmatch(relative, pattern) for pattern in allow)


def get_edit_count(session: str, root: Path, allow: list[str], cwd: str, /) -> int:
    """How many counted edits this session's calls file holds since the owner's last prompt."""

    path = data_folder() / "turns" / f"{session}.calls"
    if not path.is_file():
        return 0
    count = 0
    for line in path.read_text().splitlines():
        name, _, edited = line.partition("\t")
        if name in EDIT_TOOLS and edited and is_counted_edit(edited, root, allow, cwd):
            count += 1

    return count


def check_main_edits(event: dict, root: Path, config: dict, cwd: str, /) -> tuple[str, str]:  # keys are data
    """The refusal and the note for a main-session edit under `main_edits`; both are empty when the rule does not apply."""

    settings = config.get("main_edits") or {}
    maximum = settings.get("max", DEFAULT_MAX_EDITS)
    allow = settings.get("allow", list(DEFAULT_EDIT_ALLOW))
    tool_input = event.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if event.get("tool_name") not in EDIT_TOOLS or not path or not isinstance(maximum, int) or maximum <= 0:
        return "", ""
    if not is_counted_edit(path, root, allow, cwd):
        return "", ""

    count = get_edit_count(event.get("session_id") or "unknown", root, allow, cwd)
    if count >= maximum:
        refusal = (
            f"Blocked by the harness main_edits rule: this turn's main session has made {count} edits outside "
            f"{', '.join(allow)} and the cap is {maximum}. Hand the change to a `harness:worker` agent with a brief "
            f"(`harness:orchestrator`). Edits under {', '.join(allow)} do not count. A repo raises the cap with "
            f'`"main_edits": {{"max": N}}` in its `.harness.json`.'
        )
        return refusal, ""

    note = f"The harness main_edits rule let this edit run: edit {count + 1} of {maximum} this turn; past it, changes go to a `harness:worker` agent (`harness:orchestrator`)."

    return "", note


def check_delegate(event: dict, root: Path, config: dict, cwd: str, /) -> str:  # keys are data
    """The note of the `delegate` rule for a call that breaks it, or an empty string."""

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
    except Exception as error:  # a bug in the rule must not block every call
        print(f"the harness delegate rule failed and let the call run: {error!r}", file=sys.stderr)
        sys.exit(1)
