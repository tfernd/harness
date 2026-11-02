#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""PreToolUse hook on Bash: in a project with `.harness.json`, a commit message follows `harness:git-commit`.

The message comes from `-m`, `-F` or a heredoc in the same command. A subject is `type(scope): summary` with no trailing period,
then a blank line and `* ` bullets, then an optional footer. A pull request's `--body` is checked for AI attribution only.
Git's own subjects (merge, revert, fixup) pass. A commit that opens the editor or reuses a message cannot be read, so it passes.
`guard.commit_style: false` in `.harness.json` turns the rule off.
"""

from __future__ import annotations

import json
import os
import re
import sys

from common import find_project
from guard import get_git_subcommand
from shell import get_segments

SUBJECT = re.compile(r"(feat|fix|perf|refactor|test|docs|style|build|ci|chore|revert)(\([^()\s]+\))?!?: \S")
GIT_SUBJECT = re.compile(r"(fixup!|squash!|amend!|Merge |Revert \")")
BULLET = "* "
FOOTER = re.compile(r"(BREAKING CHANGE|[A-Z][A-Za-z-]+): \S")
AI_NAME = r"(claude|anthropic|copilot|chatgpt|gpt-|openai|gemini|cursor|codex|\bAI\b)"
AI_ATTRIBUTION = re.compile(rf"co-authored-by:[^\n]*{AI_NAME}|generated (with|by)[^\n]*{AI_NAME}|\U0001f916", re.I)
# A command's heredoc: its body, whichever quotes its delimiter has.
HEREDOC = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n(.*?)\n\s*\1\b", re.S)


def get_option_value(words: list[str], long_name: str, letter: str, /) -> list[str]:
    """Every value of an option in its long form, its short form, or the end of a short cluster such as `-am`."""

    values: list[str] = []
    for index, word in enumerate(words):
        following = words[index + 1] if index + 1 < len(words) else ""
        if word == long_name or (word.startswith("-") and not word.startswith("--") and word.endswith(letter)):
            values.append(following)
        elif word.startswith(f"{long_name}="):
            values.append(word.split("=", 1)[1])

    return values


def read_message(values: list[str], command: str, /) -> str | None:
    """The text of option values, joined as git joins them; a substitution's text is read from the command's heredoc, else None."""

    # A variable or a substitution: the text is not in the words.
    if any("$" in value or value == "-" for value in values):
        # An earlier heredoc in the same command, such as an edit script, is not the message.
        heredoc = HEREDOC.search(command, max(command.rfind("commit"), command.rfind("create"), 0))
        return heredoc.group(2) if heredoc else None

    return "\n\n".join(values)


def get_commit_message(words: list[str], command: str, cwd: str, /) -> str | None:
    """The message a `git commit` would use, None when it cannot be read from the command."""

    messages = get_option_value(words, "--message", "m")
    files = get_option_value(words, "--file", "F")
    if messages:
        return read_message(messages, command)
    if not files:
        return None
    if files[0] == "-":
        return read_message(files, command)
    try:
        with open(os.path.join(cwd, files[0]), errors="replace") as file:
            return file.read()
    except OSError:
        return None


def check_attribution(message: str, /) -> list[str]:
    return ["it carries AI attribution; commits and pull requests name no AI tool as author"] if AI_ATTRIBUTION.search(message) else []


def check_body(lines: list[str], /) -> list[str]:
    """A blank line after the subject, at least one bullet, and only bullets, their indented continuations and a footer."""

    if lines and lines[0].strip():
        return ["the subject needs a blank line after it"]
    body = [line for line in lines if line.strip()]
    if not any(line.startswith(BULLET) for line in body):
        return [f"the body needs `{BULLET}` bullets saying what was done and why"]
    stray = [line for line in body if not line.startswith((BULLET, " ", "\t")) and not FOOTER.match(line)]

    return [f"this body line is no bullet: {stray[0][:60]}"] if stray else []


def check_message(message: str, /) -> list[str]:
    """Why a commit message breaks the form."""

    lines = message.strip().splitlines()
    subject = lines[0] if lines else ""
    problems = check_attribution(message)
    if GIT_SUBJECT.match(subject):
        return problems
    if not SUBJECT.match(subject):
        problems.append(f"the subject is not `type(scope): summary`: {subject[:60]}")
    if subject.rstrip().endswith("."):
        problems.append("the subject ends in a period")

    return problems + check_body(lines[1:])


def find_problems(command: str, cwd: str, /) -> list[str]:
    """What each commit or pull request in a shell command breaks."""

    problems: list[str] = []
    for segment in get_segments(command):
        words = [word.text for word in segment.words]
        name = os.path.basename(words[0]) if words else ""
        if name == "git" and get_git_subcommand(words[1:]) == "commit":
            message = get_commit_message(words, command, cwd)
            problems += check_message(message) if message is not None else check_attribution(command)
        elif name == "gh" and words[1:3] == ["pr", "create"]:
            body = read_message(get_option_value(words, "--body", "b"), command)
            problems += check_attribution(body) if body else []

    return problems


def main() -> int:
    event = json.load(sys.stdin)
    cwd = event.get("cwd") or os.getcwd()
    root, config = find_project(cwd)
    if root is None or config.get("guard", {}).get("commit_style") is False:
        return 0
    problems = find_problems((event.get("tool_input") or {}).get("command") or "", cwd)
    if not problems:
        return 0
    print(f"Blocked by the harness commit rule (`harness:git-commit`): {'; '.join(problems)}", file=sys.stderr)

    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # a bug in the rule must not block every call
        print(f"the harness commit rule failed and let the call run: {error!r}", file=sys.stderr)
        sys.exit(1)
