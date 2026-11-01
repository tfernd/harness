#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""PreToolUse hook on Bash, Write, Edit and NotebookEdit: refuses dangerous commands, in every project, for sub-agents as well as the main session.

It judges commands, not text: `shell.py` reads the command as a shell does, so a heredoc's body, a quoted string or an
argument (`ls .venv/bin/python`) is never taken for a command, and what runs inside `$(...)`, backticks and `<(...)` is.
The strings of `sh -c` and `eval` and the commands of `find -exec` are read as commands too. A command word stands after
any `VAR=value` and prefixes such as `sudo -u root`, `env`, `timeout 60`, `xargs`.

Always on:
1. Deletes: `rm`, `rmdir`, `unlink`, `shred`, `find -delete`, `git clean`. `git rm` stays allowed.
2. History: a push that rewrites or deletes remote history (`--force` and its variants, `--delete`, `--mirror`, `--prune`, `-f` or `-d`
   alone or in a cluster such as `-fu`, `+ref`, `:ref`) and `git reset --hard`.
3. Globs: an unquoted glob that fails or changes the command: one that matches no file from the folder the command runs
   in, which zsh refuses with "no matches found" (`ls *.nothing`), one in an option (`--include=*.py`), and the pattern of
   `find -name`, `rg -g` or `grep --include`, which the shell would expand first. A glob that matches a file is what the
   author meant (`wc -l src/*.py`). Not judged, so allowed: a relative glob from an unknown folder, and a word with `$`, a
   backtick or a brace, whose expansion is not read. No glob: `$?`, `$*`, `${...}`, `$((...))`, the arguments of `[`, `[[`,
   `case` and `test`, and the value of `export NAME=...`.
4. Polling: a `sleep` inside a `while` or `until` loop, also in a `$(...)` or a `bash -c` string inside one. A command
   that waits runs in the background. A `for` loop, a loop without a sleep and a sleep outside any loop are not refused.

On when the project's `.harness.json` asks, under its `guard` key:
5. `deny_packages`: package changes (`uv add|remove|lock|sync|pip`, `uv run pip`, `pip`, `pip3`, `python -m pip`).
6. `no_tmp`: throwaway files under `/tmp`: a path a command writes there, or a Write or Edit whose path lies there.
7. `scratch`: a write by the writing commands below that lands inside the project but outside that folder is refused, and
   so is `mv` of a project file out of its place. A write outside the project is not this rule's.
   Files change through the Edit and Write tools or a Python script; what Python code writes is not read.
8. `lock`: `uv run python`, `uv run pytest` or the venv's python outside a call wrapped by one of the `commands` (the
   wrapper words that set the lock, a queue for a GPU, say). Allowed: `free_env` (the whole `NAME=value` word) before the command, the `free_scripts`, and any script or `-m` module starting with a
   `free_prefixes` entry. `message` is the refusal.

Writing commands: redirects (`>`, `>>`, `&>`; not `2>&1`, `>&2` or `/dev/null` as a file), `tee`, `mkdir`, `touch`,
`cp`, `mv`, `ln`, `install`, `rsync` (the destination), `sed -i` and `perl -i` (the existing files), `curl -o` and `-O`,
`wget -O`, `-P` or its working directory, and `tar -C` when extracting or `-f` when creating. A relative path is taken
from the working directory the command reaches: the event's, moved by each `cd`, `pushd` or `popd` before it in the
same command (`cd X && ...`, `cd X; ...`). Paths are compared resolved, so a symlink or a `..` changes nothing. Where that
folder is not known (a `cd` with no target, `cd -`, a variable, a substitution, a glob, a missing folder, a `cd` inside a
`( )` group, a substitution, a pipeline or the background, `eval`, `source`), a relative written path is refused for the
rest of that command, until a `cd` to an absolute existing folder, when the `scratch` rule (7) is on; a shell variable in a path is not expanded.

Exit 2 blocks the call and hands the message on stderr to the agent; exit 0 lets it run; exit 1 (a bug in this guard or
a broken `.harness.json`) shows the error and lets the call run: the guard fails open, so a broken config drops every rule.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys
from typing import NamedTuple

from common import find_project, get_scratch
from shell import GLOB_CHARACTERS, Segment, Word, get_segments

# The words after which the next word is the command, with no option of their own: wrappers (`command`, `exec`, `nohup`,
# `time`, `builtin`, `noglob`) and shell keywords or punctuation (`then`, `do`, `else`, `elif`, `if`, `while`, `until`, `!`, `{`, `}`).
PREFIXES = {
    "command",
    "exec",
    "nohup",
    "time",
    "builtin",
    "noglob",
    "then",
    "do",
    "else",
    "elif",
    "if",
    "while",
    "until",
    "!",
    "{",
    "}",
}
# The prefixes with options, each with the options that take a value in the next word.
OPTION_PREFIXES = {
    "sudo": {"-u", "-g", "-h", "-p", "-C", "-r", "-t", "-T", "-U", "-D", "-R", "--user", "--group", "--host", "--prompt", "--chdir", "--chroot"},
    "doas": {"-u", "-C"},
    "env": {"-u", "-C", "--unset", "--chdir"},
    "timeout": {"-k", "-s", "--kill-after", "--signal"},
    "nice": {"-n", "--adjustment"},
    "xargs": {"-n", "-I", "-L", "-P", "-d", "-s", "-E", "-a"},
    "stdbuf": {"-i", "-o", "-e"},
    "ionice": {"-c", "-n"},
    "setsid": set(),
}
# The commands that delete, and the shells whose -c string is a command.
DELETERS = {"rm", "rmdir", "unlink", "shred"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
# The options of a shell that take a value in the next word, before its -c string.
SHELL_VALUE_OPTIONS = {"-o", "+o", "-O", "+O", "--rcfile", "--init-file"}
# The options of find that run the words after them, up to a `;` or a `+`.
FIND_RUNNERS = {"-exec", "-execdir", "-ok", "-okdir"}
FIND_RUNNER_ENDS = {";", "+"}
PYTHONS = {"python", "python3", "pytest"}
# The options of `uv run` that take a value in the next word.
UV_VALUE_OPTIONS = {"--with", "--project", "--directory", "--python", "-p", "--group", "--extra", "--env-file"}
# The `uv` subcommands that change packages; refused when `deny_packages` is on, wherever they stand in the command.
UV_DENIED = {"add", "remove", "lock", "sync", "pip"}
# The `git push` options that rewrite or delete history on the remote; a plain push of a branch is allowed.
PUSH_DENIED = {"--force", "--force-with-lease", "--force-if-includes", "--mirror", "--delete", "--prune"}
# The short letters of a push option that force (`-f`) or delete (`-d`), alone or in a cluster.
PUSH_DENIED_LETTERS = set("fd")
# The options of git before its subcommand that take a value in the next word.
GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--attr-source"}
# The commands that create or copy files: their destination, or the paths named by their arguments.
CREATORS = {"tee", "mkdir", "touch"}
MOVERS = {"cp", "mv", "ln", "install", "rsync"}
# The movers whose -t names the destination folder (rsync's -t keeps times).
TARGET_MOVERS = {"cp", "mv", "ln", "install"}
IN_PLACE_EDITORS = {"sed", "perl"}
# The long option of tar that sets its mode, and the short letter it stands for.
TAR_LONG_MODES = {"--extract": "x", "--create": "c", "--append": "r", "--update": "u"}
# The folder of throwaway files; paths are compared after normalization, so `scratch/../../tmp` is `/tmp`.
TEMPORARY = "/tmp"
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")
# The commands whose arguments are patterns they match themselves, not paths the shell expands.
PATTERN_COMMANDS = {"[", "[[", "case", "test"}
# The options whose value is a pattern the command matches itself, by command.
GLOB_PATTERN_OPTIONS = {
    "find": {"-name", "-iname", "-path", "-ipath", "-wholename", "-iwholename", "-lname", "-ilname", "-regex", "-iregex"},
    "rg": {"-g", "--glob", "--iglob"},
    "grep": {"--include", "--exclude", "--exclude-dir"},
}
# The characters of a word the guard does not expand, so what its glob matches is not known.
UNEXPANDED = "$`{"
# The builtins whose `NAME=value` arguments are assignments, which no shell expands as a path.
DECLARERS = {"export", "readonly", "declare", "typeset", "local"}
# The commands that move the working directory: `cd` and `pushd` to a folder, `popd` to a stacked one.
DIRECTORY_CHANGERS = {"cd", "pushd", "popd"}
# The commands that run their text in the current shell, so the folder they leave is not known statically.
IN_SHELL_RUNNERS = {"eval", "source", "."}

MESSAGES = {
    "delete": "nothing is deleted without the owner's word. Write a new file name, or truncate a log with `: > file`. A "
    "tracked file that must go uses `git rm`; anything else goes to the owner.",
    "denied": "this rewrites history or changes packages, which is the owner's to run.",
    "lock": "this project's Python runs under its lock.",
    "glob": "this unquoted glob matches no file, so zsh fails with 'no matches found', or it is a pattern for the command "
    "that the shell would expand first. Quote it (`--include='*.py'`), or use the Grep tool or `rg -g '*.py'`.",
    "temporary": "throwaway files go in the project's scratch folder, never under /tmp.",
    "repo": "project files change through the Edit and Write tools or a Python script. A shell redirect, tee, sed -i, "
    "cp, mv, curl or tar may write only under the scratch folder. A relative path is taken from the working directory "
    "after any cd in the same command; use absolute paths when in doubt.",
    "poll": "a `sleep` inside a `while` or `until` loop polls for a result. Run the command in the background and wait "
    "for its notification instead.",
}


class Policy(NamedTuple):
    """What the project's `.harness.json` turns on; the defaults are the rules of a project without one."""

    root: str = ""
    scratch: str = ""  # the absolute folder the shell may write to; empty: the rule is off
    no_tmp: bool = False
    deny_packages: bool = False
    lock_commands: frozenset[str] = frozenset()
    free_env: str = ""
    free_scripts: frozenset[str] = frozenset()
    free_prefixes: tuple[str, ...] = ()  # a script path or module name starting with one needs no lock
    lock_message: str = ""


POLICY = Policy()


def get_policy(cwd: str, /) -> Policy:
    """The rules of the project around a working directory."""

    root, config = find_project(cwd)
    if root is None:
        return Policy()
    guard = config.get("guard", {})
    lock = guard.get("lock", {})

    return Policy(
        root=str(root),
        scratch=get_scratch(root, config),
        no_tmp=bool(guard.get("no_tmp")),
        deny_packages=bool(guard.get("deny_packages")),
        lock_commands=frozenset(lock.get("commands", ())),
        free_env=lock.get("free_env", ""),
        free_scripts=frozenset(lock.get("free_scripts", ())),
        free_prefixes=tuple(lock.get("free_prefixes", ())),
        lock_message=lock.get("message", ""),
    )


class Command(NamedTuple):
    """A simple command resolved past its prefixes: the command word, its arguments, and how it runs."""

    name: str
    arguments: list[Word]
    is_locked: bool
    is_free: bool


def skip_options(words: list[Word], index: int, value_options: set[str], /) -> int:
    """The index of the first word from `index` that is not an option or an option's value."""

    while index < len(words) and words[index].text.startswith("-"):
        index += 2 if words[index].text in value_options else 1

    return index


def resolve(segment: Segment, /) -> Command:
    """The command a segment runs, past assignments, prefixes and the lock commands."""

    words = segment.words
    index, is_locked, is_free = 0, False, False
    while index < len(words):
        word = words[index].text
        if ASSIGNMENT.match(word):
            is_free = is_free or word == POLICY.free_env
            index += 1
        elif word in PREFIXES:
            index += 1
        elif word in OPTION_PREFIXES:
            index = skip_options(words, index + 1, OPTION_PREFIXES[word])
            if word == "timeout":
                index += 1  # skip its duration, the first non-option word
        elif word.removeprefix("./") in POLICY.lock_commands:
            is_locked = True
            index = skip_options(words, index + 1, set())
        else:
            break
    if index >= len(words):
        return Command("", [], is_locked, is_free)

    return Command(words[index].text, words[index + 1 :], is_locked, is_free)


def get_interpreter_arguments(command: Command, /) -> list[str] | None:
    """The arguments a call passes to a Python interpreter (`uv run [options] python`, the venv's python), else None."""

    arguments = [word.text for word in command.arguments]
    if os.path.basename(command.name) == "uv" and arguments[:1] == ["run"]:
        index = skip_options(command.arguments, 1, UV_VALUE_OPTIONS)
        is_python = index < len(arguments) and arguments[index] in PYTHONS

        return arguments[index + 1 :] if is_python else None
    if command.name.endswith(tuple(f".venv/bin/{python}" for python in PYTHONS)):
        return arguments

    return None


def is_python_run(command: Command, /) -> bool:
    """Whether a command runs the project's Python, other than a script that needs no lock."""

    rest = get_interpreter_arguments(command)
    if rest is None:
        return False
    script = next((argument for argument in rest if not argument.startswith("-")), "")

    script = script.removeprefix("./")

    return script not in POLICY.free_scripts and not script.startswith(POLICY.free_prefixes)


def get_git_subcommand(arguments: list[str], /) -> str:
    """The subcommand of a git call, past its global options."""

    index = 0
    while index < len(arguments) and arguments[index].startswith("-"):
        index += 2 if arguments[index] in GIT_VALUE_OPTIONS else 1

    return arguments[index] if index < len(arguments) else ""


def is_delete(command: Command, /) -> bool:
    arguments = [word.text for word in command.arguments]
    name = os.path.basename(command.name)
    if name in DELETERS:
        return True
    if name == "find":
        return "-delete" in arguments

    return name == "git" and get_git_subcommand(arguments) == "clean"


def is_package_change(command: Command, /) -> bool:
    """Whether a command changes packages: `pip`, a denied `uv` subcommand, `uv run pip` or `python -m pip`."""

    arguments = [word.text for word in command.arguments]
    name = os.path.basename(command.name)
    if name in ("pip", "pip3"):
        return True
    if name == "uv":
        index = skip_options(command.arguments, 0, UV_VALUE_OPTIONS)
        if arguments[index:index + 1] == ["run"]:
            index = skip_options(command.arguments, index + 1, UV_VALUE_OPTIONS)
            return arguments[index:index + 1] in (["pip"], ["pip3"]) or is_module_pip(arguments[index + 1 :])
        return index < len(arguments) and arguments[index] in UV_DENIED

    return name.startswith("python") and is_module_pip(arguments)


def is_module_pip(arguments: list[str], /) -> bool:
    """Whether the arguments of a Python interpreter run pip as a module (`-m pip`, `-mpip`)."""

    return any(
        argument == "-mpip" or (argument == "-m" and arguments[index + 1 : index + 2] == ["pip"])
        for index, argument in enumerate(arguments)
    )


def is_history_rewrite(arguments: list[str], /) -> bool:
    """Whether the arguments of `git push` rewrite or delete history, a short option in a cluster (`-fu`) included."""

    for argument in arguments:
        if argument.split("=")[0] in PUSH_DENIED or argument.startswith(("+", ":")):
            return True
        if is_cluster(argument) and PUSH_DENIED_LETTERS & set(argument[1:]):
            return True

    return False


def is_denied(command: Command, /) -> bool:
    """Whether the command is the owner's to run: a forced push, `git reset --hard`, or a package change if denied."""

    arguments = [word.text for word in command.arguments]
    if os.path.basename(command.name) == "git":
        subcommand = get_git_subcommand(arguments)
        if subcommand == "push":
            return is_history_rewrite(arguments)
        return subcommand == "reset" and "--hard" in arguments

    return POLICY.deny_packages and is_package_change(command)


def is_failing_glob(text: str, directory: str | None, /) -> bool:
    """Whether a glob word fails in zsh: an option, or a path that matches no file from `directory` (None: not known)."""

    if text.startswith("-"):
        return True
    if any(character in text for character in UNEXPANDED) or (directory is None and not is_absolute(text)):
        return False

    return next(glob.iglob(resolve_path(text, directory or ""), recursive=True), None) is None


def has_failing_glob(command: Command, directory: str | None, /) -> bool:
    """Whether an argument holds an unquoted glob that fails or is a pattern for the command, which then must be quoted."""

    name = os.path.basename(command.name)
    if name in PATTERN_COMMANDS:
        return False
    is_declarer = name in DECLARERS
    pattern_options = GLOB_PATTERN_OPTIONS.get(name, set())
    for index, word in enumerate(command.arguments):
        is_judged = word.is_glob and not (is_declarer and ASSIGNMENT.match(word.text))
        is_pattern = index > 0 and command.arguments[index - 1].text in pattern_options
        if is_judged and (is_pattern or is_failing_glob(word.text, directory)):
            return True

    return False


# ===========================================================================
# Paths a command writes
# ===========================================================================


def resolve_path(path: str, cwd: str, /) -> str:
    """The absolute, resolved path a shell word names; a relative one is taken from the working directory."""

    return os.path.realpath(os.path.join(cwd, os.path.expanduser(path)))


def is_absolute(word: str, /) -> bool:
    """Whether a shell word names its path without the working directory: an absolute path or a `~` path."""

    return word.startswith(("/", "~"))


def expand_path(path: str, cwd: str, /) -> list[str]:
    """The paths a word names: the matches of its glob pattern, or the path itself when nothing matches."""

    absolute = resolve_path(path, cwd)
    matches = glob.glob(absolute) if any(character in absolute for character in GLOB_CHARACTERS) else []

    return matches or [absolute]


def is_under(path: str, folder: str, /) -> bool:
    """Whether a path is the folder or lies inside it."""

    return path == folder or path.startswith(folder + os.sep)


def is_temporary(path: str, /) -> bool:
    return POLICY.no_tmp and is_under(path, os.path.realpath(TEMPORARY))


def is_repo_write(path: str, /) -> bool:
    """Whether a path lies in the project outside its scratch folder, where the shell must not write."""

    return bool(POLICY.scratch) and is_under(path, POLICY.root) and not is_under(path, POLICY.scratch)


def is_cluster(argument: str, /) -> bool:
    """Whether an argument is a cluster of short options, such as `-xf`."""

    return argument.startswith("-") and not argument.startswith("--")


def get_positional(arguments: list[str], /) -> list[str]:
    """The arguments that are not options."""

    return [argument for argument in arguments if not argument.startswith("-")]


def get_option_values(arguments: list[str], letter: str, long_name: str, /) -> list[str]:
    """The values of an option, given as `--long value`, `--long=value`, or `-Xvalue` and `-X value` in a cluster."""

    values: list[str] = []
    for index, argument in enumerate(arguments):
        following = arguments[index + 1] if index + 1 < len(arguments) else ""
        if argument == long_name:
            values.append(following)
        elif argument.startswith(f"{long_name}="):
            values.append(argument.split("=", 1)[1])
        elif is_cluster(argument) and letter in argument:
            rest = argument[argument.index(letter) + 1 :]
            values.append(rest or following)

    return [value for value in values if value]


def has_option(arguments: list[str], letter: str, long_name: str, /) -> bool:
    """Whether a flag is given, as its long name or as its letter in a cluster."""

    return any(argument == long_name or (is_cluster(argument) and letter in argument) for argument in arguments)


def has_in_place(arguments: list[str], /) -> bool:
    """Whether a sed or perl call edits its files in place: `-i`, `-pi`, `-i.bak` or `--in-place`."""

    return any(argument.startswith("--in-place") or (is_cluster(argument) and "i" in argument) for argument in arguments)


def get_in_place_files(arguments: list[str], cwd: str | None, /) -> list[str]:
    """The arguments of an in-place edit that name existing files; with `cwd` None every argument counts."""

    positional = get_positional(arguments)
    if cwd is None:
        return positional

    return [argument for argument in positional if any(os.path.exists(path) for path in expand_path(argument, cwd))]


def get_destination(name: str, arguments: list[str], /) -> list[str]:
    """The destination of a copy or move: its `-t` folder, or its last positional argument when there are two or more."""

    targets = get_option_values(arguments, "t", "--target-directory") if name in TARGET_MOVERS else []
    if targets:
        return targets
    positional = get_positional(arguments)

    return positional[-1:] if len(positional) >= 2 else []


def get_moved_sources(name: str, arguments: list[str], /) -> list[str]:
    """The paths a `mv` takes away from their place: its positional arguments other than the destination."""

    if name != "mv":
        return []
    destination = get_destination(name, arguments)
    sources = [argument for argument in get_positional(arguments) if argument not in destination]

    return sources


def get_curl_outputs(arguments: list[str], /) -> list[str]:
    """The files curl writes: its `-o` value, and the working directory for `-O`."""

    outputs = get_option_values(arguments, "o", "--output")
    if has_option(arguments, "O", "--remote-name"):
        outputs.append(".")

    return outputs


def get_wget_outputs(arguments: list[str], /) -> list[str]:
    """The files wget writes: its `-O` value; without one, its `-P` folder, or the working directory."""

    outputs = get_option_values(arguments, "O", "--output-document")
    if outputs:
        return outputs

    return get_option_values(arguments, "P", "--directory-prefix") or ["."]


def get_tar_outputs(arguments: list[str], /) -> list[str]:
    """The paths tar writes: `-C` (or the working directory) when it extracts, `-f` when it creates an archive."""

    letters = "".join(argument[1:] for argument in arguments if is_cluster(argument))
    letters += "".join(TAR_LONG_MODES.get(argument, "") for argument in arguments)
    if arguments and not arguments[0].startswith("-"):
        letters += arguments[0]  # the old style without a dash: `tar xf archive`
    if "x" in letters:
        return get_option_values(arguments, "C", "--directory") or ["."]
    if any(mode in letters for mode in "cru"):
        return get_option_values(arguments, "f", "--file")

    return []


def get_named_paths(name: str, arguments: list[str], cwd: str | None, /) -> list[str]:
    """The arguments a writing command names as the paths it writes; `-` (stdout) is not a path."""

    named: list[str] = []
    if name in CREATORS:
        named = get_positional(arguments)
    elif name in MOVERS:
        named = get_destination(name, arguments)
    elif name in IN_PLACE_EDITORS and has_in_place(arguments):
        named = get_in_place_files(arguments, cwd)
    elif name == "curl":
        named = get_curl_outputs(arguments)
    elif name == "wget":
        named = get_wget_outputs(arguments)
    elif name == "tar":
        named = get_tar_outputs(arguments)

    return [argument for argument in named if argument != "-"]


def get_written_words(segment: Segment, command: Command, cwd: str | None, /) -> list[str]:
    """The shell words a simple command writes to: its redirect targets and the paths its arguments name."""

    arguments = [word.text for word in command.arguments]
    named = get_named_paths(os.path.basename(command.name), arguments, cwd)

    return segment.redirects + named


def get_written_paths(words: list[str], cwd: str | None, /) -> list[str]:
    """The absolute paths the written words name; with `cwd` None a relative word has no path and is left out."""

    return [path for word in words if cwd is not None or is_absolute(word) for path in expand_path(word, cwd or "")]


# ===========================================================================
# The working directory
# ===========================================================================


def get_cd_target(command: Command, directory: str | None, /) -> str | None:
    """The absolute folder a `cd`, `pushd` or `popd` moves to, or None when the guard cannot know it.

    Unknown: no argument, `-`, a stacked `+N`, a variable, a substitution, a glob, a folder that does not exist, or a
    relative path from an unknown `directory`.
    """

    targets = [word for word in command.arguments if not word.text.startswith("-")]
    if not targets:
        return None
    target = targets[0]
    is_static = not (target.is_glob or "$" in target.text or target.text.startswith("+"))
    if not is_static or (directory is None and not is_absolute(target.text)):
        return None
    path = resolve_path(target.text, "" if directory is None else directory)

    return path if os.path.isdir(path) else None


def get_directory_after(command: Command, is_grouped: bool, directory: str | None, /) -> str | None:
    """The working directory after a command: a `cd`, `pushd` or `popd` moves it, one inside a subshell or an `eval` or
    `source` leaves it unknown (None), and any other command keeps it."""

    if command.name in IN_SHELL_RUNNERS:
        return None
    if command.name in DIRECTORY_CHANGERS:
        return None if is_grouped else get_cd_target(command, directory)

    return directory


# ===========================================================================
# The rules
# ===========================================================================


def find_breaches(segments: list[Segment], cwd: str | None, is_locked: bool, is_free: bool, in_loop: bool, /) -> list[str]:
    """The rules some simple commands break, each once, in rule order.

    `in_loop` says they run in a loop; `cwd` is the folder they start in, None when that is not known.
    """

    breaches: list[str] = []
    directory = cwd
    for segment in segments:
        command = resolve(segment)
        locked, free = is_locked or command.is_locked, is_free or command.is_free
        is_looping = in_loop or segment.in_loop
        breaches.extend(get_command_breaches(segment, command, directory, locked or free, is_looping))
        if command.name == "export" and any(word.text == POLICY.free_env for word in command.arguments):
            is_free = True
        breaches.extend(find_breaches(get_inner_segments(command), directory, locked, free, is_looping))
        directory = get_directory_after(command, segment.in_group, directory)

    return [rule for rule in MESSAGES if rule in breaches]


def find_command_breaches(command: str, cwd: str | None, /) -> list[str]:
    """The rules a whole shell command breaks, from the folder it starts in."""

    return find_breaches(get_segments(command), cwd, False, False, False)


def get_command_breaches(
    segment: Segment, command: Command, directory: str | None, is_lock_free: bool, is_looping: bool, /
) -> list[str]:
    """The rules one simple command breaks.

    `is_lock_free` says the lock or its `free_env` covers it; `directory` is where it runs, None when unknown.
    """

    words = get_written_words(segment, command, directory)
    written = get_written_paths(words, directory)
    arguments = [word.text for word in command.arguments]
    moved = get_written_paths(get_moved_sources(os.path.basename(command.name), arguments), directory)
    is_unknown_write = bool(POLICY.scratch) and directory is None and not all(is_absolute(word) for word in words)
    checks = [
        ("delete", is_delete(command)),
        ("denied", is_denied(command)),
        ("lock", bool(POLICY.lock_commands) and is_python_run(command) and not is_lock_free),
        ("glob", has_failing_glob(command, directory)),
        ("temporary", any(is_temporary(path) for path in written)),
        ("repo", is_unknown_write or any(is_repo_write(path) for path in [*written, *moved])),
        ("poll", os.path.basename(command.name) == "sleep" and is_looping),
    ]

    return [rule for rule, is_breach in checks if is_breach]


def get_shell_string(arguments: list[str], /) -> str:
    """The string a shell runs with -c, in any cluster (`-lc`, `-ec`), or nothing when it runs a script."""

    has_string_option = False
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in SHELL_VALUE_OPTIONS:
            index += 2
            continue
        if not argument.startswith(("-", "+")) or argument in ("-", "--"):
            break
        has_string_option = has_string_option or (is_cluster(argument) and "c" in argument)
        index += 1

    return arguments[index] if has_string_option and index < len(arguments) else ""


def get_find_runs(arguments: list[Word], /) -> list[Segment]:
    """The commands a find runs: the words after each `-exec`, `-execdir`, `-ok` or `-okdir`, up to a `;` or a `+`."""

    segments: list[Segment] = []
    start = -1
    for index, word in enumerate(arguments):
        if start < 0 and word.text in FIND_RUNNERS:
            start = index + 1
        elif start >= 0 and word.text in FIND_RUNNER_ENDS:
            segments.append(Segment(arguments[start:index], [], False, True))
            start = -1
    if start >= 0:
        segments.append(Segment(arguments[start:], [], False, True))

    return segments


def get_inner_segments(command: Command, /) -> list[Segment]:
    """The commands a command runs from its arguments: a shell's -c string, an `eval`'s words, a find's -exec."""

    name = os.path.basename(command.name)
    arguments = [word.text for word in command.arguments]
    if name in SHELLS:
        return get_segments(get_shell_string(arguments))
    if name == "eval":
        return get_segments(" ".join(arguments))
    if name == "find":
        return get_find_runs(command.arguments)

    return []


def main() -> int:
    global POLICY
    event = json.load(sys.stdin)
    tool_input = event.get("tool_input") or {}
    cwd = event.get("cwd") or os.getcwd()
    POLICY = get_policy(cwd)
    if event.get("tool_name") == "Bash":
        breaches = find_command_breaches(tool_input.get("command") or "", cwd)
    else:
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        breaches = ["temporary"] if is_temporary(resolve_path(path, cwd)) else []
    if not breaches:
        return 0
    messages = {**MESSAGES, "lock": POLICY.lock_message or MESSAGES["lock"]}
    lines = [f"Blocked by the harness guard: {messages[rule]}" for rule in breaches]
    print("\n".join(lines), file=sys.stderr)

    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # fail open (exit 1 lets the call run): a bug in the guard must not block every call
        print(f"the harness guard failed and let the call run: {error!r}", file=sys.stderr)
        sys.exit(1)
