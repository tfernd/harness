#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""PreToolUse hook on Edit, Write and NotebookEdit: refuses an edit of a file until the calling agent has loaded the skill
its kind of file asks for.

The `skill_gate` key of `.harness.json` maps a glob to a list of skill names; without the key the hook does nothing. A
pattern without `/` matches the file name at any depth, one with `/` the path relative to the project root. A pattern with
`/` beats one without; of the patterns of the winning kind, every skill of every match is required. A skill counts as
loaded when the agent's own transcript holds a Skill tool call naming it, with or without the `harness:` prefix, or a
`<command-name>` line, which is how a skill preloaded through an agent's `skills:` frontmatter appears in a sub-agent's
transcript. Files under `guard.scratch`, files no pattern matches and paths outside the project pass. Exit 2 blocks and
names the skill; any error or missing transcript lets the call run.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
from pathlib import Path

from budget import get_agent_path
from common import PLUGIN_PREFIX, find_project, get_scratch

EDIT_PATH_KEYS = ("file_path", "notebook_path")
# A preloaded skill is injected as a user message holding this tag.
COMMAND_TAG = re.compile(r"<command-name>/?([^<\s]+)</command-name>")


def get_edit_path(event: dict, /) -> str:  # keys are data
    """The file an Edit, Write or NotebookEdit call targets, empty when it names none."""

    tool_input = event.get("tool_input") or {}
    for key in EDIT_PATH_KEYS:
        if isinstance(tool_input.get(key), str):
            return tool_input[key]

    return ""


def normalize(skill: str, /) -> str:
    """A skill name without the plugin prefix, so `harness:code-python` and `code-python` compare equal."""

    return skill.removeprefix(PLUGIN_PREFIX)


def get_required(patterns: dict, relative: str, /) -> list[str]:  # keys are data
    """The skills the file asks for: the union over the matching patterns with `/`, else over those without."""

    matched: dict[bool, list[str]] = {True: [], False: []}
    for pattern, skills in patterns.items():
        has_slash = "/" in pattern
        target = relative if has_slash else relative.rsplit("/", 1)[-1]
        if fnmatch.fnmatchcase(target, pattern):
            matched[has_slash].extend(skill for skill in skills if skill not in matched[has_slash])

    return matched[True] or matched[False]


def get_loaded(path: Path, /) -> set[str]:
    """The normalized names of the skills a transcript shows as loaded: Skill calls and preloaded `<command-name>` tags."""

    loaded: set[str] = set()
    for line in path.read_bytes().split(b"\n"):
        if b'"Skill"' in line:
            try:
                blocks = json.loads(line)["message"]["content"]
            except (ValueError, KeyError, TypeError):
                continue
            for block in blocks if isinstance(blocks, list) else ():
                if isinstance(block, dict) and block.get("name") == "Skill":
                    skill = (block.get("input") or {}).get("skill")
                    if isinstance(skill, str):
                        loaded.add(normalize(skill))
        elif b"<command-name>" in line:
            loaded.update(normalize(name) for name in COMMAND_TAG.findall(line.decode(errors="replace")))

    return loaded


def get_transcript(event: dict, /) -> Path | None:  # keys are data
    """The calling agent's own transcript: the sub-agent's file for a sub-agent call, the session's for the main session."""

    if event.get("agent_id"):
        return get_agent_path(event)
    session = event.get("transcript_path") or ""

    return Path(session) if os.path.isfile(session) else None


def main() -> int:
    event = json.load(sys.stdin)
    root, config = find_project(event.get("cwd") or os.getcwd())
    patterns = config.get("skill_gate")
    given = get_edit_path(event)
    if root is None or not isinstance(patterns, dict) or not given:
        return 0
    absolute = os.path.realpath(os.path.join(event.get("cwd") or os.getcwd(), os.path.expanduser(given)))
    scratch = get_scratch(root, config)
    if scratch and (absolute == scratch or absolute.startswith(scratch + os.sep)):
        return 0
    if not absolute.startswith(str(root) + os.sep):
        return 0
    relative = absolute[len(str(root)) + 1 :]
    required = get_required(patterns, relative)
    path = get_transcript(event)
    if not required or path is None:
        return 0
    loaded = get_loaded(path)
    missing = [skill for skill in required if normalize(skill) not in loaded]
    for skill in missing:
        print(f"Load the skill {skill} with the Skill tool before editing {relative}, then repeat the edit.", file=sys.stderr)

    return 2 if missing else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # a bug in the rule must not block every edit
        print(f"the harness skill gate failed and let the call run: {error!r}", file=sys.stderr)
        sys.exit(1)
