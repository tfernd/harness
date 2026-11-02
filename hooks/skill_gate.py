#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""PreToolUse hook on Bash, Edit, Write and NotebookEdit: refuses an edit of a file until the calling agent has loaded the skill
its kind of file asks for, and a commit or pull request until it has loaded `harness:git-commit`.

On Bash the files are what the command writes as far as its text shows: redirects, `tee`, `sed -i`, and in a Python heredoc that
writes, any quoted file name, since a script may hold its path in a variable. A path built at run time gets through. Running a
script asks for nothing.

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
from guard import get_git_subcommand, get_written_words, resolve
from shell import get_segments

EDIT_PATH_KEYS = ("file_path", "notebook_path")
# A preloaded skill is injected as a user message holding this tag.
COMMAND_TAG = re.compile(r"<command-name>/?([^<\s]+)</command-name>")
COMMIT_SKILL = "harness:git-commit"
# A heredoc: the line that opens it, its delimiter, its body.
HEREDOC = re.compile(r"^([^\n]*)<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n(.*?)\n\s*\2\b", re.S | re.M)
SCRIPT_WRITE = re.compile(r"\.write_text\(|\.write_bytes\(|\.write\(|\bopen\([^)\n]*['\"][wax]\+?b?['\"]")
QUOTED_FILE = re.compile(r"['\"]([^'\"\s]+\.[A-Za-z]\w*)['\"]")


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


def get_script_files(command: str, /) -> list[str]:
    """The file names in a Python heredoc that writes: any quoted name counts, since a script may hold its path in a variable."""

    names: list[str] = []
    for match in HEREDOC.finditer(command):
        if "python" in match.group(1) and SCRIPT_WRITE.search(match.group(3)):
            names += QUOTED_FILE.findall(match.group(3))

    return names


def get_bash_needs(command: str, cwd: str, /) -> tuple[list[str], bool]:
    """The files a shell command writes, as far as its text shows, and whether it makes a commit or a pull request."""

    files = get_script_files(command)
    is_commit = False
    for segment in get_segments(command):
        call = resolve(segment)
        arguments = [word.text for word in call.arguments]
        name = os.path.basename(call.name)
        is_commit = is_commit or (name == "git" and get_git_subcommand(arguments) == "commit") or (name == "gh" and arguments[:1] == ["pr"] and arguments[1:2] in (["create"], ["edit"]))
        files += get_written_words(segment, call, cwd)

    return files, is_commit


def get_file_skills(patterns: dict, name: str, root: Path, scratch: str, cwd: str, /) -> tuple[str, list[str]]:  # keys are data
    """A file's path from the project root and the skills it asks for; none under the scratch folder or outside the project."""

    absolute = os.path.realpath(os.path.join(cwd, os.path.expanduser(name)))
    is_scratch = scratch and (absolute == scratch or absolute.startswith(scratch + os.sep))
    if is_scratch or not absolute.startswith(str(root) + os.sep):
        return name, []
    relative = absolute[len(str(root)) + 1 :]

    return relative, get_required(patterns, relative)


def get_needs(event: dict, patterns: dict, root: Path, scratch: str, cwd: str, /) -> dict[str, str]:  # keys are data
    """Each skill the call asks for, with what it is about to do."""

    needs: dict[str, str] = {}
    if event.get("tool_name") == "Bash":
        files, is_commit = get_bash_needs((event.get("tool_input") or {}).get("command") or "", cwd)
        if is_commit:
            needs[COMMIT_SKILL] = "committing"
    else:
        given = get_edit_path(event)
        files = [given] if given else []
    for name in files:
        relative, skills = get_file_skills(patterns, name, root, scratch, cwd)
        for skill in skills:
            needs.setdefault(skill, f"editing {relative}")

    return needs


def main() -> int:
    event = json.load(sys.stdin)
    cwd = event.get("cwd") or os.getcwd()
    root, config = find_project(cwd)
    patterns = config.get("skill_gate")
    if root is None or not isinstance(patterns, dict) or not patterns:
        return 0
    needs = get_needs(event, patterns, root, get_scratch(root, config), cwd)
    path = get_transcript(event)
    if not needs or path is None:
        return 0
    loaded = get_loaded(path)
    missing = {skill: action for skill, action in needs.items() if normalize(skill) not in loaded}
    for skill, action in missing.items():
        print(f"Load the skill {skill} with the Skill tool before {action}, then repeat the call.", file=sys.stderr)

    return 2 if missing else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # a bug in the rule must not block every edit
        print(f"the harness skill gate failed and let the call run: {error!r}", file=sys.stderr)
        sys.exit(1)
