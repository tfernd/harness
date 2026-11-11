#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///

from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

from budget import get_agent_path
from common import EDIT_TOOLS, PLUGIN_PREFIX, find_project, get_scratch, is_state_folder, make_note_output, read_tail, resolve
from guard import Policy, get_git_subcommand, get_written_words, resolve_path
from shell import get_segments

EDIT_PATH_KEYS = ("file_path", "notebook_path")
COMMAND_TAG = re.compile(r"<command-name>/?([^<\s]+)</command-name>")
COMMIT_SKILL = "harness:git-commit"
MARKER = "Harness skill text: "
MARKER_TAG = re.compile(r"Harness skill text: ([\w:-]+)")
MAX_INJECTED = 9500
LOADED_TAIL_BYTES = 2097152
UNRESOLVED = "$`{}*?[(<>|&;!"
HEREDOC = re.compile(r"^([^\n]*)<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n(.*?)\n\s*\2\b", re.S | re.M)
SCRIPT_WRITE = re.compile(r"\.write_text\(|\.write_bytes\(|\.write\(|\bopen\([^)\n]*['\"][wax]\+?b?['\"]")
QUOTED_FILE = re.compile(r"['\"]([^'\"\s]+\.[A-Za-z]\w*)['\"]")


def get_edit_path(event: dict, /) -> str:

    tool_input = event.get("tool_input") or {}
    for key in EDIT_PATH_KEYS:
        if isinstance(tool_input.get(key), str):
            return tool_input[key]

    return ""


def normalize(skill: str, /) -> str:

    return skill.removeprefix(PLUGIN_PREFIX)


def get_required(patterns: dict, relative: str, /) -> list[str]:

    matched: dict[bool, list[str]] = {True: [], False: []}
    for pattern, skills in patterns.items():
        has_slash = "/" in pattern
        target = relative if has_slash else relative.rsplit("/", 1)[-1]
        if fnmatch.fnmatchcase(target, pattern):
            matched[has_slash].extend(skill for skill in skills if skill not in matched[has_slash])

    return matched[True] or matched[False]


def get_loaded(path: Path, /) -> set[str]:

    loaded: set[str] = set()
    for line in read_tail(path, LOADED_TAIL_BYTES).split(b"\n"):
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
        if MARKER.encode() in line:
            loaded.update(normalize(name) for name in MARKER_TAG.findall(line.decode(errors="replace")))

    return loaded


def get_transcript(event: dict, /) -> Path | None:

    if event.get("agent_id"):
        return get_agent_path(event)
    session = event.get("transcript_path") or ""

    return Path(session) if os.path.isfile(session) else None


def get_script_files(command: str, /) -> list[str]:

    names: list[str] = []
    for match in HEREDOC.finditer(command):
        if "python" in match.group(1) and SCRIPT_WRITE.search(match.group(3)):
            names += QUOTED_FILE.findall(match.group(3))

    return names


class BashNeeds(NamedTuple):

    files: list[str]
    is_commit: bool


def get_bash_needs(command: str, cwd: str, /) -> BashNeeds:

    files = get_script_files(command)
    is_commit = False
    for segment in get_segments(command):
        call = resolve(segment, Policy())
        arguments = [word.text for word in call.arguments]
        name = os.path.basename(call.name)
        is_commit = is_commit or (name == "git" and get_git_subcommand(arguments) == "commit") or (name == "gh" and arguments[:1] == ["pr"] and arguments[1:2] in (["create"], ["edit"]))
        files += get_written_words(segment, call, cwd)

    return BashNeeds(files, is_commit)


def get_project_relative(name: str, root: Path, cwd: str, /) -> str | None:

    if not name or any(character in name for character in UNRESOLVED):
        return None
    absolute = resolve_path(name, cwd)
    if not absolute.startswith(str(root) + os.sep):
        return None

    return absolute[len(str(root)) + 1 :]


def get_written_project_files(command: str, root: Path, cwd: str, /) -> list[str]:

    relatives: list[str] = []
    for name in get_bash_needs(command, cwd).files:
        relative = get_project_relative(name, root, cwd)
        if relative is not None and not is_state_folder(relative) and relative not in relatives:
            relatives.append(relative)

    return relatives


class FileSkills(NamedTuple):

    relative: str
    skills: list[str]


def get_file_skills(patterns: dict, name: str, root: Path, scratch: str, cwd: str, /) -> FileSkills:

    absolute = resolve_path(name, cwd)
    is_scratch = scratch and (absolute == scratch or absolute.startswith(scratch + os.sep))
    if is_scratch or not absolute.startswith(str(root) + os.sep):
        return FileSkills(name, [])
    relative = absolute[len(str(root)) + 1 :]

    return FileSkills(relative, get_required(patterns, relative))


def get_needs(event: dict, patterns: dict, root: Path, scratch: str, cwd: str, /) -> dict[str, str]:

    needs: dict[str, str] = {}
    if event.get("tool_name") == "Bash":
        files, is_commit = get_bash_needs((event.get("tool_input") or {}).get("command") or "", cwd)
        if is_commit:
            needs[COMMIT_SKILL] = "committing"
    elif event.get("tool_name") in EDIT_TOOLS:
        given = get_edit_path(event)
        files = [given] if given else []
    else:
        files = []
    for name in files:
        if not name or any(character in name for character in UNRESOLVED):
            continue
        relative, skills = get_file_skills(patterns, name, root, scratch, cwd)
        for skill in skills:
            needs.setdefault(skill, f"editing {relative}")

    return needs


def get_skill_text(skill: str, plugin: Path, /) -> str | None:

    name = normalize(skill)
    path = plugin / "skills" / name / "SKILL.md"
    if not skill.startswith(PLUGIN_PREFIX) or not re.fullmatch(r"[\w-]+", name) or not path.is_file():
        return None
    text = path.read_text()
    if text.startswith("---\n"):
        _, _, text = text[4:].partition("\n---\n")

    return text.strip()


def make_context(missing: dict[str, str], plugin: Path, /) -> str:

    pieces: list[str] = []
    notes: list[str] = []
    used = 0
    for skill, action in missing.items():
        text = get_skill_text(skill, plugin)
        piece = f"{MARKER}{skill}\n(Reference text, given because this call is {action}; nothing to answer.)\n\n{text}" if text else ""
        if piece and used + len(piece) <= MAX_INJECTED:
            pieces.append(piece)
            used += len(piece)
        else:
            notes.append(f"Harness skill note: {skill} applies to this call ({action}); its text was not given here, so read it with the Skill tool if you have one.")

    return "\n\n".join([*pieces, *notes])


def main() -> int:
    event = json.load(sys.stdin)
    cwd = event.get("cwd") or os.getcwd()
    root, config = find_project(cwd)
    patterns = config.get("skill_gate")
    if not isinstance(patterns, dict) or not patterns:
        return 0
    needs = get_needs(event, patterns, root, get_scratch(root, config), cwd)
    path = get_transcript(event)
    if not needs or path is None:
        return 0
    loaded = get_loaded(path)
    missing = {skill: action for skill, action in needs.items() if normalize(skill) not in loaded}
    if missing:
        plugin = Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or Path(__file__).resolve().parent.parent)
        print(json.dumps(make_note_output(make_context(missing, plugin))))

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"the harness skill gate failed and let the call run: {error!r}", file=sys.stderr)
        sys.exit(1)
