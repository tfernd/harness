#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///

from __future__ import annotations

import ast
import fnmatch
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from collections.abc import Set
from typing import NamedTuple

from common import find_project, get_git_index, get_inner_segments, resolve
from guard import get_directory_after, get_written_paths, get_written_words, is_long_prefix
from shell import Segment, get_segments

SUBJECT = re.compile(r"(feat|fix|perf|refactor|test|docs|style|build|ci|chore|revert)(\([^()\s]+\))?!?: \S")
GIT_SUBJECT = re.compile(r"(fixup!|squash!|amend!|Merge |Revert \")")
BULLETS = ("* ", "- ")
FOOTER = re.compile(r"(BREAKING CHANGE|[A-Z][A-Za-z-]+): \S")
AI_NAME = r"(claude|anthropic|copilot|chatgpt|\bgpt|openai|gemini|cursor|codex|\bAI\b|\bopus\b|\bsonnet\b|\bhaiku\b|\bfable\b|\bllms?\b)"
AI_ATTRIBUTION = re.compile(
    rf"\b(co-authored-by|assisted-by|generated-by|signed-off-by)[ \t]*:\s*[^\n]*{AI_NAME}"
    rf"|^[^\w\n]*(generated[ \t]+(with|by)|made[ \t]+with)[ \t]*[\[(*_\"'`]*{AI_NAME}"
    r"|\U0001f916",
    re.I | re.M,
)
AI_NAMED = re.compile(AI_NAME, re.I)
ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿­᠎"), None)
LOOKALIKES = str.maketrans(dict(zip(
    "АВСЕНІЈКМОРЅТХаеіјорсуѕхΑΒΕΖΗΙΚΜΝΟΡΤΥΧαο",
    "ABCEHIJKMOPSTXaeijopcysxABEZHIKMNOPTYXao",
    strict=True,
)))
TRAILER_EQUALS = re.compile(r"^([A-Za-z][A-Za-z-]*)[ \t]*=")
CALL = re.compile(r"\b(git\b[^\n]*?\b(commit|tag|merge)|gh\s+pr\s+(create|edit|comment)|gh\s+api)\b")
CALL_END = re.compile(r"\n|;|&&|\|\|")
HEREDOC = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n(.*?)\n\s*\1\b", re.S)
SHELL_VALUE_START = re.compile(r"[\"']|(?:^|(?<=[\s;&|(]))[A-Za-z_][A-Za-z0-9_]*=")
ATTRIBUTION_ONLY = frozenset({"tag", "merge", "commit-tree"})
IDENTITY_KEYS = frozenset({"user.name", "user.email", "author.name", "author.email", "committer.name", "committer.email"})


GIT_SECONDS = 3
MAX_TEST_FILES = 100
TEST_FILE_NAMES = ("test_*.py", "*_test.py", "*_test.go", "*.test.*", "*.spec.*", "*.rs")
TEST_FOLDERS = frozenset({"tests", "test"})
PYTHON_TEST = re.compile(r"^[ \t]*(?:async[ \t]+)?def[ \t]+test_", re.M)
SCRIPT_TEST = re.compile(r"\b(?:it|test)\(")
GO_TEST = re.compile(r"^func[ \t]+(?:\([^)]*\)[ \t]*)?Test\w*[ \t]*\(", re.M)
RUST_TEST = re.compile(r"^[ \t]*#\[(?:[\w:]+::)?test\]", re.M)
SCRIPT_SUFFIXES = frozenset({".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"})
TESTS_REMOVED = re.compile(r"^[ \t]*[*-][ \t]+Tests removed:[ \t]*\S", re.M)
STAGING_COMMANDS = frozenset({"add", "rm", "mv"})




class OptionSpec(NamedTuple):

    short: dict[str, str]
    values: frozenset[str]
    names: frozenset[str]


class ParsedOptions(NamedTuple):

    values: dict[str, list[str]]
    flags: set[str]
    operands: list[str]


class Call(NamedTuple):

    words: list[str]
    directory: str | None
    written: list[str]


COMMIT_OPTIONS = OptionSpec(
    {"m": "--message", "F": "--file", "C": "--reuse-message", "c": "--reedit-message", "t": "--template", "a": "--all", "i": "--include", "o": "--only"},
    frozenset({"--message", "--file", "--reuse-message", "--reedit-message", "--template", "--trailer", "--author", "--date", "--cleanup", "--fixup", "--squash", "--pathspec-from-file"}),
    frozenset({
        "--message", "--file", "--reuse-message", "--reedit-message", "--template", "--trailer", "--author", "--date", "--cleanup", "--fixup",
        "--squash", "--pathspec-from-file", "--all", "--include", "--only", "--amend", "--no-edit", "--edit", "--patch", "--interactive",
        "--allow-empty", "--allow-empty-message", "--no-verify", "--verify", "--signoff", "--no-signoff", "--quiet", "--verbose",
        "--dry-run", "--status", "--no-status", "--reset-author", "--short", "--branch", "--porcelain", "--long", "--null", "--gpg-sign",
        "--no-gpg-sign", "--untracked-files", "--no-post-rewrite", "--pathspec-file-nul",
    }),
)
MESSAGE_OPTIONS = OptionSpec(
    {"m": "--message", "F": "--file", "u": "--local-user", "s": "--strategy", "X": "--strategy-option", "p": "--parent"},
    frozenset({"--message", "--file", "--local-user", "--strategy", "--strategy-option", "--parent"}),
    frozenset({"--message", "--file", "--local-user", "--strategy", "--strategy-option", "--parent"}),
)
PULL_REQUEST_OPTIONS = OptionSpec(
    {"t": "--title", "b": "--body", "F": "--body-file"},
    frozenset({"--title", "--body", "--body-file"}),
    frozenset(),
)

API_OPTIONS = OptionSpec(
    {"f": "--raw-field", "F": "--field", "H": "--header", "X": "--method", "q": "--jq", "t": "--template", "p": "--preview"},
    frozenset({"--raw-field", "--field", "--header", "--method", "--jq", "--template", "--preview", "--hostname", "--cache", "--input"}),
    frozenset(),
)


def get_long_option(name: str, names: Set[str], /) -> str:

    if name in names:
        return name
    matches = [option for option in names if is_long_prefix(name, option)]

    return matches[0] if len(matches) == 1 else ""


def parse_options(arguments: list[str], spec: OptionSpec, /) -> ParsedOptions:

    parsed = ParsedOptions({}, set(), [])
    index = 0
    while index < len(arguments):
        word = arguments[index]
        index += 1
        if word == "--":
            parsed.operands.extend(arguments[index:])
            break
        if word.startswith("--"):
            name, equals, value = word.partition("=")
            option = get_long_option(name, spec.names) or name
            if option in spec.values and not equals and index < len(arguments):
                value = arguments[index]
                index += 1
            if option in spec.values:
                parsed.values.setdefault(option, []).append(value)
            else:
                parsed.flags.add(option)
        elif word.startswith("-") and len(word) > 1:
            index = read_cluster(word, arguments, index, spec, parsed)
        else:
            parsed.operands.append(word)

    return parsed


def read_cluster(word: str, arguments: list[str], index: int, spec: OptionSpec, parsed: ParsedOptions, /) -> int:

    for position, letter in enumerate(word[1:], start=2):
        option = spec.short.get(letter, f"-{letter}")
        if option not in spec.values:
            parsed.flags.add(option)
            continue
        attached = word[position:]
        value = attached or (arguments[index] if index < len(arguments) else "")
        parsed.values.setdefault(option, []).append(value)
        return index if attached else index + 1

    return index


def get_tail_start(command: str, /) -> int:

    call = CALL.search(command)

    return call.start() if call else 0


def get_text_up_to_call(command: str, /) -> str:

    start = get_tail_start(command)
    end = CALL_END.search(command, start)

    return command[: end.start()] if end else command


def read_message(values: list[str], command: str, /) -> str | None:

    if any("$" in value or "`" in value or value == "-" for value in values):
        heredoc = HEREDOC.search(command, get_tail_start(command))
        return heredoc.group(2) if heredoc else None

    return "\n\n".join(values)


def get_file_path(name: str, call: Call, /) -> str | None:

    if os.path.isabs(name):
        return name

    return os.path.join(call.directory, name) if call.directory is not None else None


def read_file(name: str, call: Call, command: str, /) -> tuple[str | None, str]:

    if name == "-":
        text = read_message(["-"], command)
        return text, "" if text is not None else "`-F -` reads stdin, which the command does not show"
    path = get_file_path(name, call)
    if path is None:
        return None, f"`{name}` is relative to a folder the command moves to unseen"
    if os.path.realpath(path) in call.written:
        return None, f"`{name}` is written by the same command"
    try:
        with open(path, errors="replace") as file:
            return file.read(), ""
    except OSError:
        return None, f"`{name}` does not exist yet"


def get_commit_message(parsed: ParsedOptions, call: Call, command: str, /) -> tuple[str | None, str]:

    messages = parsed.values.get("--message", [])
    files = parsed.values.get("--file", [])
    if messages:
        text = read_message(messages, command)
        return text, "" if text is not None else "a variable or a substitution with no heredoc"
    if files:
        return read_file(files[0], call, command)
    if parsed.values.get("--reuse-message") or parsed.values.get("--reedit-message"):
        return None, "`-C` or `-c` reuses another commit's message"
    if parsed.values.get("--fixup") or parsed.values.get("--squash"):
        return "fixup! the commit it fixes", ""

    return None, "with no `-m` or `-F`, git opens an editor"


def get_calls(segments: list[Segment], directory: str | None, written: list[str], calls: list[Call], /) -> str | None:

    for segment in segments:
        command = resolve(segment)
        name = os.path.basename(command.name)
        if name in ("git", "gh"):
            calls.append(Call([command.name, *(word.text for word in command.arguments)], directory, list(written)))
        written.extend(os.path.realpath(path) for path in get_written_paths(get_written_words(segment, command, directory), directory))
        get_calls(get_inner_segments(command), directory, written, calls)
        directory = get_directory_after(command, segment.in_group, directory)

    return directory


def find_calls(command: str, cwd: str, /) -> list[Call]:

    calls: list[Call] = []
    get_calls(get_segments(command), cwd, [], calls)

    return calls


def get_git_directory(words: list[str], directory: str | None, /) -> str | None:

    for index, word in enumerate(words[1 : get_git_index(words[1:]) + 1], start=1):
        if word == "-C" and index + 1 < len(words):
            target = words[index + 1]
            directory = target if os.path.isabs(target) else (os.path.join(directory, target) if directory is not None else None)

    return directory




def normalize(text: str, /) -> str:

    return unicodedata.normalize("NFKC", text).translate(ZERO_WIDTH).translate(LOOKALIKES)


def check_attribution(message: str, /) -> list[str]:
    return ["it carries AI attribution; commits and pull requests name no AI tool as author"] if AI_ATTRIBUTION.search(normalize(message)) else []


def check_shell_text(text: str, /) -> list[str]:

    return check_attribution(SHELL_VALUE_START.sub("\n", text))


def check_identity(values: list[str], /) -> list[str]:

    named = [value for value in values if AI_NAMED.search(normalize(value))]

    return [f"it names an AI tool as author ({named[0][:60]}); a commit names a person"] if named else []


def get_identities(global_options: list[str], /) -> list[str]:

    pairs = [global_options[index + 1] for index, word in enumerate(global_options[:-1]) if word == "-c"]

    return [value for key, _, value in (pair.partition("=") for pair in pairs) if key.lower() in IDENTITY_KEYS]


def get_trailers(values: list[str], /) -> str:

    return "\n".join(TRAILER_EQUALS.sub(r"\1: ", value) for value in values)


def check_texts(values: list[str], files: list[str], call: Call, command: str, /) -> list[str]:

    texts = [read_message(values, command)] if values else []
    texts += [read_file(name, call, command)[0] for name in files]
    readable = [text for text in texts if text is not None]
    problems = [problem for text in readable for problem in check_attribution(text)]
    if len(readable) < len(texts):
        problems += check_shell_text(get_text_up_to_call(command))

    return problems




def check_body(lines: list[str], /) -> list[str]:

    if lines and lines[0].strip():
        return ["the subject needs a blank line after it"]
    body = [line for line in lines if line.strip()]
    if not any(line.startswith(BULLETS) for line in body):
        return ["the body needs `* ` bullets saying what was done and why"]
    stray = [line for line in body if not line.startswith((*BULLETS, " ", "\t")) and not FOOTER.match(line)]

    return [f"this body line is no bullet: {stray[0][:60]}"] if stray else []


def check_message(message: str, /) -> list[str]:

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


def check_commit(arguments: list[str], call: Call, command: str, /) -> list[str]:

    parsed = parse_options(arguments, COMMIT_OPTIONS)
    message, why = get_commit_message(parsed, call, command)
    if message is not None:
        problems = check_message(message)
    else:
        problems = [
            f"the message cannot be read from the command ({why}): write it to a file in an earlier call and pass it with "
            "`-F <file>`, or give it in a quoted heredoc"
        ]
        problems += check_shell_text(get_text_up_to_call(command))
    problems += check_attribution(get_trailers(parsed.values.get("--trailer", [])))

    return problems + check_identity(parsed.values.get("--author", []))


def check_pull_request(arguments: list[str], call: Call, command: str, /) -> list[str]:

    if arguments[:1] != ["pr"] or arguments[1:2] not in (["create"], ["edit"], ["comment"]):
        return []
    parsed = parse_options(arguments[2:], PULL_REQUEST_OPTIONS)
    values = parsed.values.get("--title", []) + parsed.values.get("--body", [])

    return check_texts(values, parsed.values.get("--body-file", []), call, command)


def check_api(arguments: list[str], call: Call, command: str, /) -> list[str]:

    parsed = parse_options(arguments, API_OPTIONS)
    raw = [value.partition("=")[2] for value in parsed.values.get("--raw-field", [])]
    typed = [value.partition("=")[2] for value in parsed.values.get("--field", [])]
    values = raw + [value for value in typed if not value.startswith("@")]
    files = [value[1:] for value in typed if value.startswith("@")]

    return check_texts(values, files, call, command)


def find_call_problems(call: Call, command: str, /) -> list[str]:

    arguments = call.words[1:]
    if os.path.basename(call.words[0]) == "gh" and arguments[:1] == ["api"]:
        return check_api(arguments[1:], call, command)
    if os.path.basename(call.words[0]) == "gh":
        return check_pull_request(arguments, call, command)
    index = get_git_index(arguments)
    subcommand = arguments[index] if index < len(arguments) else ""
    located = call._replace(directory=get_git_directory(call.words, call.directory))
    problems = check_identity(get_identities(arguments[:index]))
    if subcommand == "commit":
        problems += check_commit(arguments[index + 1 :], located, command)
    elif subcommand in ATTRIBUTION_ONLY:
        parsed = parse_options(arguments[index + 1 :], MESSAGE_OPTIONS)
        problems += check_texts(parsed.values.get("--message", []), parsed.values.get("--file", []), located, command)

    return problems


def find_problems(command: str, cwd: str, /) -> list[str]:

    problems = [problem for call in find_calls(command, cwd) for problem in find_call_problems(call, command)]

    return list(dict.fromkeys(problems))




class FileCount(NamedTuple):

    path: str
    before: int
    after: int
    is_deleted: bool


def is_test_file(path: str, /) -> bool:

    *folders, name = path.split("/")

    return any(fnmatch.fnmatch(name, pattern) for pattern in TEST_FILE_NAMES) or any(folder in TEST_FOLDERS for folder in folders)


def is_empty_body(body: list[ast.stmt], /) -> bool:

    return all(isinstance(statement, ast.Pass) or (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant) and (statement.value.value is Ellipsis or isinstance(statement.value.value, str))) for statement in body)


def is_skipped(function: ast.FunctionDef | ast.AsyncFunctionDef, /) -> bool:

    for decorator in function.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = target.attr if isinstance(target, ast.Attribute) else (target.id if isinstance(target, ast.Name) else "")
        if name == "skip":
            return True

    return False


def count_python_tests(text: str, /) -> int:

    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return len(PYTHON_TEST.findall(text))
    functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]

    return sum(1 for function in functions if function.name.startswith("test_") and not is_empty_body(function.body) and not is_skipped(function))


def count_tests(path: str, text: str, /) -> int:

    suffix = os.path.splitext(path)[1]
    match suffix:
        case ".py":
            return count_python_tests(text)
        case ".go":
            return len(GO_TEST.findall(text))
        case ".rs":
            return len(RUST_TEST.findall(text))

    return len(SCRIPT_TEST.findall(text)) if suffix in SCRIPT_SUFFIXES else 0


def run_git(arguments: list[str], cwd: str, deadline: float, /) -> str | None:

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    try:
        run = subprocess.run(["git", *arguments], cwd=cwd, capture_output=True, timeout=remaining)
    except (OSError, subprocess.TimeoutExpired):
        return None

    return run.stdout.decode(errors="replace") if run.returncode == 0 else None


def get_changed_paths(output: str, /) -> list[tuple[str | None, str | None]]:

    tokens = output.split("\0")
    changes: list[tuple[str | None, str | None]] = []
    index = 0
    while index + 1 < len(tokens) and tokens[index]:
        status = tokens[index][0]
        if status in "RC" and index + 2 < len(tokens):
            changes.append((tokens[index + 1], tokens[index + 2]))
            index += 3
            continue
        path = tokens[index + 1]
        changes.append((None if status == "A" else path, None if status == "D" else path))
        index += 2

    return changes


def get_file_counts(directory: str, is_all: bool, paths: list[str], /) -> list[FileCount] | None:

    deadline = time.monotonic() + GIT_SECONDS
    from_tree = is_all or bool(paths)
    top = run_git(["rev-parse", "--show-toplevel", "HEAD"], directory, deadline)
    names = run_git(["diff", *(["HEAD"] if from_tree else ["--cached"]), "--name-status", "-M", "-z", *(["--", *paths] if paths else [])], directory, deadline)
    if top is None or names is None:
        return None
    changes = [(old, new) for old, new in get_changed_paths(names) if (old and is_test_file(old)) or (new and is_test_file(new))]
    if len(changes) > MAX_TEST_FILES:
        return None
    counts: list[FileCount] = []
    for old, new in changes:
        before = after = 0
        if old and is_test_file(old):
            text = run_git(["show", f"HEAD:{old}"], directory, deadline)
            if text is None:
                return None
            before = count_tests(old, text)
        if new and is_test_file(new):
            text = read_new_file(top.splitlines()[0], directory, new, from_tree, deadline)
            if text is None:
                return None
            after = count_tests(new, text)
        counts.append(FileCount(new or old or "", before, after, new is None))

    return counts


def read_new_file(top: str, directory: str, path: str, from_tree: bool, deadline: float, /) -> str | None:

    if not from_tree:
        return run_git(["show", f":{path}"], directory, deadline)
    try:
        with open(os.path.join(top, path), errors="replace") as file:
            return file.read()
    except OSError:
        return None


def describe_drops(counts: list[FileCount], /) -> str:

    if sum(count.after for count in counts) >= sum(count.before for count in counts):
        return ""
    dropped = [f"{count.path}{' (deleted)' if count.is_deleted else ''} {count.before} -> {count.after}" for count in counts if count.after < count.before]

    return (
        f"this commit drops tests: {'; '.join(dropped)}. Restore them, or add a body bullet "
        "`* Tests removed: <why>` saying why they go"
    )


def find_test_drops(command: str, cwd: str, /) -> list[str]:

    problems: list[str] = []
    is_staged_here = False
    for call in find_calls(command, cwd):
        arguments = call.words[1:]
        index = get_git_index(arguments)
        subcommand = arguments[index] if index < len(arguments) else ""
        if os.path.basename(call.words[0]) != "git" or subcommand not in (*STAGING_COMMANDS, "commit"):
            continue
        if subcommand in STAGING_COMMANDS:
            is_staged_here = True
            continue
        parsed = parse_options(arguments[index + 1 :], COMMIT_OPTIONS)
        directory = get_git_directory(call.words, call.directory)
        message = get_commit_message(parsed, call._replace(directory=directory), command)[0]
        if directory is None or TESTS_REMOVED.search(message if message is not None else get_text_up_to_call(command)):
            continue
        is_all = "--all" in parsed.flags or is_staged_here
        counts = get_file_counts(directory, is_all, parsed.operands)
        problem = describe_drops(counts) if counts else ""
        if problem:
            problems.append(problem)

    return list(dict.fromkeys(problems))


def main() -> int:
    event = json.load(sys.stdin)
    cwd = event.get("cwd") or os.getcwd()
    root, config = find_project(cwd)
    command = (event.get("tool_input") or {}).get("command") or ""
    problems: list[str] = []
    if config.get("guard", {}).get("commit_style") is not False:
        problems += find_problems(command, cwd)
    if config.get("tests_kept", {}).get("enabled") is not False and "commit" in command:
        problems += find_test_drops(command, cwd)
    if not problems:
        return 0
    print(f"Blocked by the harness commit rule (`harness:git-commit`): {'; '.join(problems)}", file=sys.stderr)

    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"the harness commit rule failed and let the call run: {error!r}", file=sys.stderr)
        sys.exit(1)
