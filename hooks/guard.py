#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""PreToolUse hook on Bash, Write, Edit and NotebookEdit: refuses dangerous commands, fixes cheap mistakes in place and steers the rest, in every project, for sub-agents as well as the main session.

It judges commands, not text: `shell.py` reads the command as a shell does, so a heredoc's body, a quoted string or an
argument (`ls .venv/bin/python`) is never taken for a command, and what runs inside `$(...)`, backticks and `<(...)` is.
The strings of `sh -c` and `eval`, the commands of `find -exec` and the wrappers in rule 2 are read as commands too. A command word stands after
any `VAR=value` and prefixes such as `sudo -u root`, `env`, `timeout 60`, `xargs`.

Always on:
1. Deletes: `rm`, `rmdir`, `unlink`, `shred`, `find -delete`, `git clean`. `git rm` stays allowed. Allowed too: a plain `rm` or
   `rmdir` of literal paths strictly inside the `scratch` folder or the Claude scratchpad (`SCRATCHPAD`), where a `$NAME`
   counts as the literal an earlier plain `NAME=value` of the same command gave it. Moved to the trash instead (soft, see
   below): an `rm` or `rmdir` the top-level shell runs itself, with literal paths inside the project. Refused: a path
   under one of `OWNER_FOLDERS`, the project root, a path outside the project, and every delete the trash cannot take.
2. History: a git command that discards work or rewrites history (`GIT_DENIALS`): a push that rewrites or deletes remote
   history (`--force` and its variants, `--delete`, `--mirror`, `--prune`, `-f` or `-d` alone or in a cluster such as `-fu`,
   `+ref`, `:ref`), `reset --hard`, `checkout -f`, `-- <paths>`, `.` or an existing path, `switch -f` or `--discard-changes`,
   `checkout -B`, `switch -C` or `--force-create`, `restore` but `--staged` alone, `stash drop|clear`, `branch -D`,
   `-d --force`, `-f`, `--force` or `-M`, `tag -d`, `rebase`, `pull --rebase`, `commit --amend`, `filter-branch`,
   `filter-repo`, `reflog expire|delete`, `gc --prune`, `update-ref -d`, `read-tree --reset -u`, a forced `fetch` into a
   local ref, `worktree remove --force`. A long option counts by any prefix of 3 or more characters
   (`--ha`), as git takes one. The message names the command.
   Hidden: the same, or a package change, run where the command cannot be read: a variable or a substitution as the
   command word, a shell fed from stdin (`bash <<< ...`, `... | sh`), or `python -c` code calling os.system or subprocess;
   that text is read loosely, word by word. A shell or git alias is judged as the command it stands for. Seen through
   too: `watch`, `parallel`, `su -c`, `script -c`, and `ssh host cmd`, judged there only for git, packages and hiding.
3. Globs: an unquoted glob that matches no file from the folder the command runs in, which zsh refuses with "no matches
   found" (`ls *.nothing`); a glob that matches a file is what the author meant (`wc -l src/*.py`). A glob in a pattern
   position, an option that holds one (`--include=*.py`) or the pattern of `find -name`, `rg -g` or `grep --include`, which
   the shell would expand first, is quoted instead (soft, see below). Not judged, so allowed: everything when the user's shell is not zsh, and inside another
   shell's `-c` string, where a glob with no match stays literal; a path glob after a step that may write its files
   (`make && cat out/*`); a relative glob from an unknown folder; and a word with `$`, a backtick or a brace, whose expansion is not read. No glob: `$?`, `$*`, `${...}`, `$((...))`, the arguments of `[`, `[[`,
   `case` and `test`, and the value of `export NAME=...`.
4. Waiting (soft, see below): a `sleep` anywhere in a foreground call, loop or not, also in a `$(...)`, a `bash -c` string or a
   `find -exec`. A call with `run_in_background` may sleep: its exit wakes the agent, so the wait costs no turn.

On by default (the template's `guard` section), off where the owner file sets it off:
5. `ask_packages` (or its old name `deny_packages`): package changes (`uv add|remove|lock|sync|pip|tool`, `uv run pip`,
   `uv run --with`, `pip`, `pip3`, `python -m pip`, `python setup.py install`, and the changing subcommands of npm, pnpm,
   yarn, bun, cargo, go, gem, bundle, pipx, conda, mamba, poetry, pdm, apt, apt-get, dnf, yum and brew in
   `PACKAGE_CHANGES`) and tool runs that may fetch a package (`TOOL_RUNNERS`, `npm exec`, `bun x`, `pnpm dlx`, `yarn dlx`)
   ask the owner instead of running at once; a read-only one (list, show, outdated, why, audit) and a script run do not. Any other rule the same command breaks still refuses it.
6. `no_tmp` (soft): throwaway files under `/tmp`: a path a command writes there, or a Write or Edit whose path lies there.
7. `scratch` (soft): a write by the writing commands below that lands inside the project but outside that folder, and
   a `mv` of a project file out of its place. A write outside the project is not this rule's.
   Files change through the Edit and Write tools or a Python script; what Python code writes is not read.

Writing commands: redirects (`>`, `>>`, `&>`; not `2>&1`, `>&2` or `/dev/null` as a file), `tee`, `mkdir`, `touch`,
`cp`, `mv`, `ln`, `install`, `rsync` (the destination), `sed -i` and `perl -i` (the existing files), `curl -o` and `-O`,
`wget -O`, `-P` or its working directory, and `tar -C` when extracting or `-f` when creating. A relative path is taken
from the working directory the command reaches: the event's, moved by each `cd`, `pushd` or `popd` before it in the
same command (`cd X && ...`, `cd X; ...`). Paths are compared resolved, so a symlink or a `..` changes nothing. Where that
folder is not known (a `cd` with no target, `cd -`, a variable, a substitution, a glob, a missing folder, a `cd` inside a
`( )` group, a substitution, a pipeline or the background, `eval`, `source`), a relative written path is refused for the
rest of that command, until a `cd` to an absolute existing folder, when the `scratch` rule (7) is on; a shell variable in a path is not expanded.

Hard rules (1, 2, 3) exit 2, which blocks the call and hands the message on stderr to the agent. A call that breaks a hard
rule is refused with the hard messages only, and a delete in it with the delete message. Soft rules let the call run:
the guard exits 0 and prints an `additionalContext` note for the agent, with no `permissionDecision`, so the owner's
permission prompts still apply. Three change the call (`updatedInput` carries every other field of the input), in this
order. A glob in a pattern position is quoted in place (`get_glob_fix`). A delete for the trash is spliced, in the text,
into a call of the `harness_trash` function put in front (`TRASH_HELPER`), which moves each path into
`__harness__/trash/<tool_use_id>/` under its path from the project root (`get_trash_fix`). When either change cannot be
shown safe, the call is refused as a glob or a delete. A foreground `sleep`: when every `sleep` is a
direct command of the top-level command (not in a `while` or `until` loop, a subshell, a pipeline, a substitution, a wrapper such as
`timeout`, `sh -c`, `eval` or `find -exec`), the command gets `sleep() { :; }; ` in front, so nothing is cut or parsed; any other
`sleep` (a polling loop, a wrapper) leaves the command alone and sets `run_in_background`, since removing the sleep from a
polling loop would spin the CPU. Exit 0 with `permissionDecision: ask` asks the owner first; exit 1 (a bug in this guard or
a broken owner file) shows the error and lets the call run: the guard fails open, so a broken config drops every rule.
"""

from __future__ import annotations

import glob
import itertools
import json
import os
import re
import shlex
import sys
from collections.abc import Callable, Mapping, Set
from pathlib import Path
from typing import NamedTuple

from common import (
    ASSIGNMENT,
    JOINING_RUNNERS,
    REMOTE_RUNNERS,
    SHELL_VALUE_OPTIONS,
    SHELLS,
    TRASH_FOLDER,
    Command,
    ensure_harness_folder,
    find_project,
    get_git_index,
    get_git_subcommand,
    get_inner_segments,
    get_scratch,
    get_shell_string,
    is_cluster,
    is_project_root,
    resolve,
    skip_options,
)
from shell import GLOB_CHARACTERS, LEADING_WORDS, Segment, Word, get_segments

# The commands that delete.
DELETERS = frozenset({"rm", "rmdir", "unlink", "shred"})
SCRATCH_DELETERS = frozenset({"rm", "rmdir"})
# Commands that make no file unless they redirect, so a glob after them is judged by what exists now.
READ_ONLY_COMMANDS = frozenset("cat ls grep rg sed head tail wc echo printf cd pwd awk sort uniq cut tr true false which test stat du file date [ [[".split())
# The options of `uv run` that take a value in the next word.
UV_VALUE_OPTIONS = frozenset({"--with", "--with-requirements", "--with-editable", "--project", "--directory", "--python", "-p", "--group", "--extra", "--env-file"})
# The `uv` subcommands that change packages; asked of the owner when `ask_packages` is on, wherever they stand in the command.
UV_DENIED = frozenset({"add", "remove", "lock", "sync", "pip", "tool"})
# The `git push` options that rewrite or delete history on the remote; a plain push of a branch is allowed.
PUSH_DENIED = frozenset({"--force", "--force-with-lease", "--force-if-includes", "--mirror", "--delete", "--prune"})
# The short letters of a push option that force (`-f`) or delete (`-d`), alone or in a cluster.
PUSH_DENIED_LETTERS = frozenset("fd")
# The commands that create or copy files: their destination, or the paths named by their arguments.
CREATORS = frozenset({"tee", "mkdir", "touch"})
MOVERS = frozenset({"cp", "mv", "ln", "install", "rsync"})
# The movers whose -t names the destination folder (rsync's -t keeps times).
TARGET_MOVERS = frozenset({"cp", "mv", "ln", "install"})
IN_PLACE_EDITORS = frozenset({"sed", "perl"})
# The long option of tar that sets its mode, and the short letter it stands for.
TAR_LONG_MODES = {"--extract": "x", "--create": "c", "--append": "r", "--update": "u"}
# The folder of throwaway files; paths are compared after normalization, so `__scratch__/../../tmp` is `/tmp`.
TEMPORARY = "/tmp"
# The commands whose arguments are patterns they match themselves, not paths the shell expands.
PATTERN_COMMANDS = frozenset({"[", "[[", "case", "test"})
# The options whose value is a pattern the command matches itself, by command.
GLOB_PATTERN_OPTIONS = {
    "find": {"-name", "-iname", "-path", "-ipath", "-wholename", "-iwholename", "-lname", "-ilname", "-regex", "-iregex"},
    "rg": {"-g", "--glob", "--iglob"},
    "grep": {"--include", "--exclude", "--exclude-dir"},
}

# The characters of a word the guard does not expand, so what its glob matches is not known.
UNEXPANDED = "$`{"
# The builtins whose `NAME=value` arguments are assignments, which no shell expands as a path.
DECLARERS = frozenset({"export", "readonly", "declare", "typeset", "local"})
# The commands that move the working directory: `cd` and `pushd` to a folder, `popd` to a stacked one.
DIRECTORY_CHANGERS = frozenset({"cd", "pushd", "popd"})
# The commands that run their text in the current shell, so the folder they leave is not known statically.
IN_SHELL_RUNNERS = frozenset({"eval", "source", "."})
# The folders whose contents only the owner deletes, at any depth of the project.
OWNER_FOLDERS = frozenset({"node_modules", "dist", ".venv", ".git"})
# The options of `rm` whose meaning a move to the trash keeps, each with the letter it passes on: force, recursive, and
# verbose, whose lines a move does not print.
TRASH_OPTIONS = {"-f": "f", "-r": "r", "-R": "r", "-v": "", "--force": "f", "--recursive": "r", "--verbose": ""}
# The user id in the scratchpad's path; -1 on a system with none, where no path matches.
USER_ID = os.getuid() if hasattr(os, "getuid") else -1
# Claude Code's scratchpad of a session: a folder named `scratchpad` at any depth under `/tmp/claude-<uid>/`
# (`<project>/<session>/scratchpad`). A path strictly inside it is a throwaway file.
SCRATCHPAD = re.compile(rf"{re.escape(os.path.realpath(TEMPORARY))}/claude-{USER_ID}/(?:[^/]+/)*scratchpad/[^/]")
# A `$NAME` in a word, the one form whose value the guard may know.
VARIABLE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")
# The characters a word may hold written bare, with no quote, so its text is how it was written.
BARE_WORD = re.compile(r"[\w./@%+,:=~$-]+")
# Put before a command whose deletes go to the trash. `harness_trash NAME LETTERS SOURCE TARGET...` moves each source to
# its target where `rm` (LETTERS holding `f` and `r`) or `rmdir` would remove it, and fails with their message where
# they would fail: a missing path without `f`, a folder without `r`, a file or a full folder for `rmdir`.
TRASH_HELPER = (
    'harness_trash() { local name="$1" flags="$2" code=0 why; shift 2; while [ "$#" -ge 2 ]; do why=; '
    'if [ ! -e "$1" ] && [ ! -L "$1" ]; then case "$flags" in *f*) why=skip;; *) why="No such file or directory";; esac; '
    'elif [ -L "$1" ] || [ ! -d "$1" ]; then [ "$name" = rmdir ] && why="Not a directory"; '
    'elif [ "$name" = rmdir ]; then [ -z "$(command ls -A -- "$1")" ] || why="Directory not empty"; '
    'else case "$flags" in *r*) ;; *) why="Is a directory";; esac; fi; '
    'case "$why" in "") command mkdir -p -- "${2%/*}" && command mv -- "$1" "$2" || code=1;; skip) ;; '
    '*) printf "%s: cannot remove \'%s\': %s\\n" "$name" "$1" "$why" >&2; code=1;; esac; shift 2; done; return "$code"; }; '
)

# The one rule that asks the owner instead of refusing.
ASK_RULE = "packages"
# The rules judged in a command that runs on another machine (`ssh host cmd`), where local paths and globs mean nothing.
REMOTE_RULES = frozenset({"denied", "hidden", ASK_RULE})
MESSAGES = {
    "delete": "nothing is deleted without the owner's word. Your own throwaway files go in `__scratch__/`, where `rm` works; "
    "a tracked file that must go uses `git rm`.",
    "denied": "`{what}` rewrites history or discards uncommitted work, which is the owner's to run: leave it to them and say so "
    "in your report.",
    "hidden": "`{what}` runs where the guard cannot read the command (a variable as the command, a shell fed from stdin, a "
    "string built at run time, or Python's os.system or subprocess). Rewriting history or discarding work is the owner's to "
    "run and a package change is asked: write the command plainly as its own call.",
    ASK_RULE: "changing packages is the owner's to run, so they are asked first. `uvx`, `uv tool`, `npx`, `bunx` and `dlx` "
    "fetch a tool outside the lock: run the project's own as `uv run --frozen <tool>` or through a package.json script.",
    "glob": "this glob matches no file from {folder}, so zsh fails with 'no matches found'. cd to the right folder, or use "
    "`rg --files -g '{pattern}'` or `git ls-files`.",
    "pattern": "an unquoted glob in a pattern position (--include, -name, -g) was quoted so the tool gets the pattern, not zsh's "
    "expansion.",
    "trash": "rm and rmdir here move what they name into `{folder}/`, each under its path from the project root, instead of "
    "deleting it; the owner empties `__harness__/trash/`. A missing path still fails unless -f.",
    "temporary": "the guard lets this call pass, but a write under /tmp is not where throwaway files go. Throwaway files belong in the project's `__scratch__/` folder, never under /tmp.",
    "repo": "the guard lets this call pass, but project files change with the Write tool (new file) or Edit (change); a shell "
    "redirect, tee, sed -i, cp or mv belongs under `__scratch__/`.",
    "sleep": "`sleep` was removed from this command and the rest ran at once, so a result may be early. Waiting on a timer spends "
    "the owner's time and tells you nothing; wait on events (`harness:tool-habits`, Waiting): a job of yours with `run_in_background: true` "
    "notifies you on exit, and a condition runs as a background `timeout 600 sh -c 'until [ -f done ]; do sleep 5; done'`.",
}
# The refusal of a glob in a pattern position that the guard could not quote safely.
PATTERN_REFUSAL = (
    "this unquoted glob is a pattern for the command, which zsh would expand first, and the guard could not quote it safely. "
    "Quote it (`--include='*.py'`), or use `rg -g '*.py'`."
)
# The rules that let the call run with a note; every other rule refuses. `pattern` and `trash` change the call, and
# refuse it when the change cannot be shown safe.
SOFT_RULES = ("pattern", "trash", "temporary", "repo", "sleep")
# The soft rules whose note is all they add.
NOTED_RULES = ("temporary", "repo")
# The note for a `sleep` the guard could not remove: it moved the call to the background instead.
SLEEP_BACKGROUND_NOTE = (
    "this command waits with `sleep` (a polling loop, a wrapper or a nested string), so it now runs in the background and its exit "
    "wakes you: read the output then, not before. Waiting on a timer in the foreground spends the owner's time (`harness:tool-habits`, Waiting)."
)
# Put before a command whose every `sleep` is direct: the function shadows the program, so no text is parsed or cut.
SLEEP_SHADOW = "sleep() { :; }; "


class Policy(NamedTuple):
    """What the merged `guard` config turns on; the defaults below are the always-on rules."""

    root: str = ""
    scratch: str = ""  # the absolute folder the shell may write to; empty: the rule is off
    trash: str = ""  # the absolute folder deletes are moved into; empty where the root is no project root
    no_tmp: bool = False
    ask_packages: bool = False


def get_policy(cwd: str, /) -> Policy:
    """The rules of the project around a working directory."""

    root, config = find_project(cwd)
    guard = config.get("guard", {})

    return Policy(
        root=str(root),
        scratch=get_scratch(root, config),
        trash=str(root / TRASH_FOLDER) if is_project_root(root) else "",
        no_tmp=bool(guard.get("no_tmp")),
        ask_packages=bool(guard.get("ask_packages") or guard.get("deny_packages")),
    )


def is_delete(command: Command, /) -> bool:
    arguments = [word.text for word in command.arguments]
    name = os.path.basename(command.name)
    if name in DELETERS:
        return True
    if name == "find":
        return "-delete" in arguments

    is_dry_run = bool({"-n", "--dry-run"} & set(arguments))

    return name == "git" and get_git_subcommand(arguments) == "clean" and not is_dry_run


# ===========================================================================
# Package changes
# ===========================================================================

# The subcommands of each package manager that change packages; any other (list, show, outdated, why, run, test, x) is
# not asked.
PACKAGE_CHANGES = {
    "npm": frozenset({
        "install", "i", "in", "ins", "inst", "insta", "instal", "isnt", "isnta", "isntal", "isntall", "add", "ci", "clean-install",
        "ic", "install-clean", "isntall-clean", "uninstall", "unlink", "remove", "rm", "r", "un", "update", "up", "upgrade",
        "udpate", "link", "ln", "prune", "dedupe", "ddp", "rebuild", "rb", "install-test", "it", "install-ci-test", "cit",
        "exec", "x",
    }),
    "pnpm": frozenset({
        "add", "install", "i", "remove", "rm", "uninstall", "un", "update", "up", "upgrade", "link", "ln", "unlink", "prune",
        "dedupe", "rebuild", "rb", "import", "fetch", "install-test", "it", "dlx",
    }),
    "yarn": frozenset({"add", "install", "remove", "upgrade", "up", "upgrade-interactive", "dedupe", "link", "unlink", "import", "dlx"}),
    "bun": frozenset({"add", "a", "install", "i", "remove", "rm", "update", "upgrade", "link", "unlink", "x"}),
    "cargo": frozenset({"add", "remove", "rm", "install", "uninstall", "update"}),
    "go": frozenset({"get", "install"}),
    "gem": frozenset({"install", "uninstall", "update"}),
    "bundle": frozenset({"install", "add", "update", "remove"}),
    "pipx": frozenset({
        "install", "install-all", "uninstall", "uninstall-all", "upgrade", "upgrade-all", "upgrade-shared", "reinstall",
        "reinstall-all", "inject", "uninject", "run", "pin", "unpin",
    }),
    "conda": frozenset({"install", "remove", "uninstall", "update", "upgrade", "create"}),
    "mamba": frozenset({"install", "remove", "uninstall", "update", "upgrade", "create"}),
    "micromamba": frozenset({"install", "remove", "uninstall", "update", "upgrade", "create"}),
    "poetry": frozenset({"add", "remove", "install", "update", "lock", "sync"}),
    "pdm": frozenset({"add", "remove", "install", "update", "lock", "sync"}),
    "apt": frozenset({"install", "remove", "purge", "autoremove", "upgrade", "full-upgrade", "dist-upgrade", "reinstall", "build-dep"}),
    "apt-get": frozenset({"install", "remove", "purge", "autoremove", "upgrade", "dist-upgrade", "reinstall", "build-dep"}),
    "dnf": frozenset({"install", "remove", "erase", "upgrade", "update", "downgrade", "reinstall", "autoremove", "distro-sync"}),
    "yum": frozenset({"install", "remove", "erase", "upgrade", "update", "downgrade", "reinstall", "autoremove", "distro-sync"}),
    "brew": frozenset({"install", "uninstall", "remove", "rm", "upgrade", "reinstall", "link", "unlink", "tap", "untap"}),
}
# The options of a package manager that take a value in the next word, before its subcommand.
MANAGER_VALUE_OPTIONS = {
    "npm": frozenset({"--prefix", "-w", "--workspace"}),
    "pnpm": frozenset({"-C", "--dir", "-F", "--filter"}),
    "yarn": frozenset({"--cwd"}),
    "bun": frozenset({"--cwd"}),
    "cargo": frozenset({"-C", "--config", "-Z"}),
    "go": frozenset({"-C"}),
    "poetry": frozenset({"-C", "--directory", "-P", "--project"}),
    "pdm": frozenset({"-p", "--project"}),
    "apt": frozenset({"-o", "-t", "-c"}),
    "apt-get": frozenset({"-o", "-t", "-c"}),
    "dnf": frozenset({"-c", "--releasever"}),
    "yum": frozenset({"-c", "--releasever"}),
}
# The commands that run a tool, fetching it first when it is not installed, so every call of one is asked.
TOOL_RUNNERS = frozenset({"uvx", "npx", "bunx", "pnpx"})
# The runners that need no question when the tool is already in the project's `node_modules/.bin/`.
LOCAL_RUNNERS = frozenset({"npx", "bunx", "pnpx"})
# The manager subcommands that run a tool the same way: `npm exec`, `bun x`, `pnpm dlx`, `yarn dlx`.
MANAGER_RUNNERS = {"npm": frozenset({"exec", "x"}), "bun": frozenset({"x"}), "pnpm": frozenset({"dlx"}), "yarn": frozenset({"dlx"})}
# The options that name a package to fetch or a command to run, so the tool is not the one in the project.
FETCHING_OPTIONS = frozenset({"-p", "--package", "-c", "--call"})
# A tool name that can be a file name in `node_modules/.bin/`: no version, scope or path.
LOCAL_TOOL = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*")
# The managers that install when run with no subcommand, as `yarn` alone does, and the options that make such a run
# only print.
BARE_INSTALLERS = frozenset({"yarn", "bundle"})
INFORMATION_OPTIONS = frozenset({"-v", "-V", "--version", "-h", "--help"})
# The subcommands that change packages only with one of these words after them: `npm audit fix`, `conda env create`.
NESTED_CHANGES = {"audit": frozenset({"fix", "--fix"}), "env": frozenset({"create", "update", "remove"})}
# The `setup.py` commands that install the package they build.
SETUP_INSTALLS = frozenset({"install", "develop"})


def is_local_run(name: str, arguments: list[str], root: str, /) -> bool:
    """Whether a tool run (`npx tool`, `npm exec tool`, `pnpm dlx tool`) runs a binary already in `node_modules/.bin/` of `root`.

    The tool is the first word that is not an option; a pinned version (`tool@5`), a scope, a path, or an option that names a
    package to fetch (`FETCHING_OPTIONS`) makes it not local. An empty `root` is never local.
    """

    if name in MANAGER_RUNNERS:
        index = 0
        while index < len(arguments) and arguments[index].startswith("-"):
            index += 1
        if arguments[index:index + 1] and arguments[index] in MANAGER_RUNNERS[name]:
            arguments = arguments[index + 1 :]
        else:
            return False
    elif name not in LOCAL_RUNNERS:
        return False
    if not root or FETCHING_OPTIONS & set(arguments):
        return False
    positional = [argument for argument in arguments if argument != "--" and not argument.startswith("-")]

    return bool(positional) and bool(LOCAL_TOOL.fullmatch(positional[0])) and os.path.exists(os.path.join(root, "node_modules", ".bin", positional[0]))


def is_package_change(command: Command, root: str, /) -> bool:
    """Whether a command changes packages: `pip`, a tool runner (`TOOL_RUNNERS`) not found in `root`'s `node_modules/.bin/`,
    a changing `uv` call (`is_uv_change`), `python -m pip`, `python setup.py install`, or a changing subcommand of another
    manager (`PACKAGE_CHANGES`)."""

    arguments = [word.text for word in command.arguments]
    name = os.path.basename(command.name)
    if is_local_run(name, arguments, root):
        return False
    if name in ("pip", "pip3") or name in TOOL_RUNNERS:
        return True
    if name == "uv":
        return is_uv_change(command.arguments)
    if name in PACKAGE_CHANGES:
        return is_manager_change(name, arguments)

    return name.startswith("python") and (is_module_pip(arguments) or is_setup_install(arguments))


def is_uv_change(words: list[Word], /) -> bool:
    """Whether a `uv` call changes packages: a denied subcommand, `uv run pip`, `uv run -m pip`, or `uv run --with`."""

    arguments = [word.text for word in words]
    index = skip_options(words, 0, UV_VALUE_OPTIONS)
    if arguments[index:index + 1] == ["run"]:
        start = index + 1
        index = skip_options(words, start, UV_VALUE_OPTIONS)
        if any(argument.startswith("--with") for argument in arguments[start:index]):
            return True
        return arguments[index:index + 1] in (["pip"], ["pip3"]) or is_module_pip(arguments[index + 1 :])

    return index < len(arguments) and arguments[index] in UV_DENIED


def is_manager_change(name: str, arguments: list[str], /) -> bool:
    """Whether the arguments of a package manager change packages: a changing subcommand, a nested one, or a bare installer
    run with no subcommand and no option that only prints."""

    value_options = MANAGER_VALUE_OPTIONS.get(name, frozenset())
    index = 0
    while index < len(arguments) and arguments[index].startswith(("-", "+")):
        index += 2 if arguments[index] in value_options else 1
    if index >= len(arguments):
        return name in BARE_INSTALLERS and not INFORMATION_OPTIONS & set(arguments)
    subcommand = arguments[index]
    if subcommand in NESTED_CHANGES:
        return bool(NESTED_CHANGES[subcommand] & set(arguments[index + 1 :]))

    return subcommand in PACKAGE_CHANGES[name]


def is_setup_install(arguments: list[str], /) -> bool:
    """Whether the arguments of a Python interpreter run `setup.py install` or `setup.py develop`."""

    positional = get_positional(arguments)

    return bool(positional) and os.path.basename(positional[0]) == "setup.py" and bool(SETUP_INSTALLS & set(positional[1:]))


def is_module_pip(arguments: list[str], /) -> bool:
    """Whether the arguments of a Python interpreter run pip as a module (`-m pip`, `-mpip`)."""

    return any(
        argument == "-mpip" or (argument == "-m" and arguments[index + 1 : index + 2] == ["pip"])
        for index, argument in enumerate(arguments)
    )


# ===========================================================================
# Git commands that are the owner's to run
# ===========================================================================

# The shortest word, `--` and one letter, taken for a long option it begins, as git takes any unambiguous prefix
# (`--ha` for `--hard`); an ambiguous one git refuses itself.
MIN_PREFIX = 3
# The short options of each git subcommand that take a value, attached or in the next word, so the letters after one in a
# cluster are its value, not flags (`-bfix` names a branch `fix`).
GIT_VALUE_LETTERS = {"checkout": "bB", "switch": "cC", "restore": "s", "branch": "u", "tag": "mFu", "commit": "mFCct", "update-ref": "m", "fetch": "jo"}
# The subcommands refused whatever their options.
GIT_ALWAYS_DENIED = frozenset({"rebase", "filter-branch", "filter-repo"})
# The values of `pull --rebase` that turn rebasing off.
REBASE_OFF = frozenset({"false", "no", "0", "off"})


class GitArguments(NamedTuple):
    """The arguments of a git subcommand, sorted as its option parser reads them."""

    letters: str  # the short flags of every cluster, up to a letter that takes a value
    long_options: list[str]  # each long option as written, `=value` included
    operands: list[str]  # the other words before `--`, option values left out
    paths: list[str]  # the words after `--`


# A subcommand's check: the arguments and the folder it runs in (None: unknown), to the command named for its refusal or "".
GitCheck = Callable[[GitArguments, str | None], str]


def parse_git_arguments(arguments: list[str], value_letters: str, /) -> GitArguments:
    """The arguments of a subcommand sorted into flags, long options, operands and paths; `value_letters` take a value."""

    parsed = GitArguments("", [], [], [])
    letters = ""
    index = 0
    while index < len(arguments):
        word = arguments[index]
        index += 1
        if word == "--":
            return parsed._replace(letters=letters, paths=arguments[index:])
        if word.startswith("--"):
            parsed.long_options.append(word)
        elif word.startswith("-") and len(word) > 1:
            for position, letter in enumerate(word[1:], start=2):
                letters += letter
                if letter in value_letters:
                    index += 1 if position == len(word) else 0
                    break
        else:
            parsed.operands.append(word)

    return parsed._replace(letters=letters)


def is_long_prefix(word: str, option: str, /) -> bool:
    """Whether a word gives a long option in full or by a prefix of at least `MIN_PREFIX` characters, `=value` or not."""

    name = word.split("=", 1)[0]

    return len(name) >= MIN_PREFIX and option.startswith(name)


def has_flag(parsed: GitArguments, letter: str, *options: str) -> bool:
    """Whether a short flag (`letter`, "" for none) or one of the long options is given."""

    return (bool(letter) and letter in parsed.letters) or any(is_long_prefix(word, option) for word in parsed.long_options for option in options)


def get_checkout_denial(parsed: GitArguments, directory: str | None, /) -> str:
    """`checkout -f`, `-B`, or a checkout of paths: after `--`, `.`, or an operand naming an existing path from `directory`."""

    if has_flag(parsed, "f", "--force"):
        return "git checkout --force"
    if "B" in parsed.letters:
        return "git checkout -B"
    is_path = [operand == "." or (directory is not None and os.path.lexists(resolve_path(operand, directory))) for operand in parsed.operands]

    return "git checkout <paths>" if parsed.paths or any(is_path) else ""


def get_restore_denial(parsed: GitArguments, directory: str | None, /) -> str:
    """Any `restore` but one of the index alone (`--staged` without `--worktree`)."""

    is_staged_only = has_flag(parsed, "S", "--staged") and not has_flag(parsed, "W", "--worktree")

    return "" if is_staged_only else "git restore"


def get_branch_denial(parsed: GitArguments, directory: str | None, /) -> str:
    """`branch -D` or a delete that forces (`-d --force`); a forced create, reset, rename or copy (`-f`, `--force`, `-M`, `-C`)."""

    is_forced = has_flag(parsed, "f", "--force")
    if "D" in parsed.letters or (is_forced and has_flag(parsed, "d", "--delete")):
        return "git branch -D"

    return "git branch --force" if is_forced or "M" in parsed.letters or "C" in parsed.letters else ""


def get_switch_denial(parsed: GitArguments, directory: str | None, /) -> str:
    """`switch -f` or `--discard-changes`, or a create that resets an existing branch (`-C`, `--force-create`)."""

    if has_flag(parsed, "f", "--force", "--discard-changes"):
        return "git switch --discard-changes"

    return "git switch --force-create" if has_flag(parsed, "C", "--force-create") else ""


def get_read_tree_denial(parsed: GitArguments, directory: str | None, /) -> str:
    """`read-tree --reset -u`, which overwrites the working tree with the tree it reads."""

    return "git read-tree --reset -u" if has_flag(parsed, "", "--reset") and has_flag(parsed, "u") else ""


def get_pull_denial(parsed: GitArguments, directory: str | None, /) -> str:
    """`pull --rebase` (`-r`), unless its value turns rebasing off."""

    rebases = [word for word in parsed.long_options if is_long_prefix(word, "--rebase")]
    is_rebase = "r" in parsed.letters or any(word.partition("=")[2].lower() not in REBASE_OFF for word in rebases)

    return "git pull --rebase" if is_rebase else ""


def get_fetch_denial(parsed: GitArguments, directory: str | None, /) -> str:
    """A forced fetch (`-f` or a `+` refspec) into a local ref (`src:dst`, a `dst` outside `refs/remotes/`)."""

    is_forced = has_flag(parsed, "f", "--force") or any(operand.startswith("+") for operand in parsed.operands)
    targets = [operand.split(":", 1)[1] for operand in parsed.operands if ":" in operand]
    is_into_ref = any(target and not target.startswith("refs/remotes/") for target in targets)

    return "git fetch --force into a ref" if is_forced and is_into_ref else ""


def get_flag_denial(subcommand: str, letter: str, option: str, /) -> GitCheck:
    """A check that refuses a subcommand given one flag, as its short `letter` or its long `option`."""

    return lambda parsed, directory: f"git {subcommand} {option}" if has_flag(parsed, letter, option) else ""


def get_operand_denial(subcommand: str, operands: Set[str], /) -> GitCheck:
    """A check that refuses a subcommand whose first operand is one of `operands` (`stash drop`)."""

    return lambda parsed, directory: f"git {subcommand} {parsed.operands[0]}" if parsed.operands[:1] and parsed.operands[0] in operands else ""


# Each subcommand's check: the git command named for its refusal, "" when it neither discards work nor rewrites history.
GIT_DENIALS: dict[str, GitCheck] = {
    "reset": get_flag_denial("reset", "", "--hard"),
    "checkout": get_checkout_denial,
    "switch": get_switch_denial,
    "restore": get_restore_denial,
    "stash": get_operand_denial("stash", frozenset({"drop", "clear"})),
    "branch": get_branch_denial,
    "tag": get_flag_denial("tag", "d", "--delete"),
    "pull": get_pull_denial,
    "commit": get_flag_denial("commit", "", "--amend"),
    "reflog": get_operand_denial("reflog", frozenset({"expire", "delete"})),
    "gc": get_flag_denial("gc", "", "--prune"),
    "update-ref": get_flag_denial("update-ref", "d", "-d"),
    "read-tree": get_read_tree_denial,
    "fetch": get_fetch_denial,
    "worktree": lambda parsed, directory: "git worktree remove --force" if parsed.operands[:1] == ["remove"] and has_flag(parsed, "f", "--force") else "",
}


def is_history_rewrite(arguments: list[str], /) -> bool:
    """Whether the arguments of `git push` rewrite or delete history, a short option in a cluster (`-fu`) included."""

    for argument in arguments:
        if any(is_long_prefix(argument, option) for option in PUSH_DENIED) or argument.startswith(("+", ":")):
            return True
        if is_cluster(argument) and PUSH_DENIED_LETTERS & set(argument[1:]):
            return True

    return False


def get_git_denial(arguments: list[str], directory: str | None, /) -> str:
    """The git command named for its refusal when the arguments of git discard work or rewrite history, else "".

    `directory` is where it runs, None when unknown, where a checkout operand is not taken for a path.
    """

    index = get_git_index(arguments)
    subcommand = arguments[index] if index < len(arguments) else ""
    rest = arguments[index + 1 :]
    if subcommand == "push":
        return "git push --force" if is_history_rewrite(rest) else ""
    if subcommand in GIT_ALWAYS_DENIED:
        return f"git {subcommand}"
    check = GIT_DENIALS.get(subcommand)

    return check(parse_git_arguments(rest, GIT_VALUE_LETTERS.get(subcommand, "")), directory) if check else ""


def get_denied(command: Command, directory: str | None, /) -> str:
    """The git command named for its refusal when the command is one that is the owner's to run, else ""."""

    if os.path.basename(command.name) != "git":
        return ""

    return get_git_denial([word.text for word in command.arguments], directory)


# ===========================================================================
# Commands the guard cannot read
# ===========================================================================

# The words of a text read loosely, such as Python code: what quotes, brackets, commas and shell punctuation leave.
LOOSE_WORD = re.compile(r"[^\s;&|(){}<>'\"`,\[\]]+")
# What ends one command in such a text: `&&`, `||`, a newline, `;`, `|` or `&`.
LOOSE_SEPARATOR = re.compile(r"&&|\|\||[;\n|&]")
# The command names a loose reading looks for: git and every package manager; a `python` name counts too.
LOOSE_NAMES = frozenset({"git", "pip", "pip3", "uv", *TOOL_RUNNERS, *PACKAGE_CHANGES})
# A literal a text assigns: `NAME=value`, `NAME='value'` or `NAME="value"`.
LITERAL_ASSIGNMENT = re.compile(r"(?:^|(?<=[\s;&|(]))([A-Za-z_][A-Za-z0-9_]*)=(?:'([^']*)'|\"([^\"$`\\]*)\"|([^\s;&|()<>'\"`$\\]*))")
# The opening of a command substitution: `$(` but not `$((`, or a backtick.
SUBSTITUTION_START = re.compile(r"\$\((?!\()|`")
# A `${NAME}` in a text, which the parser reads as a bare `$` command word.
BRACED_PARAMETER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
# A `$NAME` or `${NAME}` in a text.
PARAMETER = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
# The Python calls that run a program or a shell command, up to their opening parenthesis.
PYTHON_RUNNERS = re.compile(r"\b(?:os\.(?:system|popen|exec\w*|spawn\w*)|subprocess\.\w+|pty\.spawn)\s*\(")
# The text a shell reads from stdin when the command gives it: the body of a heredoc opened on the shell's line, or a
# here-string, in single quotes, double quotes or bare.
SHELL_NAMES = "|".join(sorted(SHELLS))
SHELL_HEREDOC = re.compile(rf"\b(?:{SHELL_NAMES})\b[^\n]*?<<-?[ \t]*['\"]?(\w+)['\"]?[^\n]*\n(.*?)\n[ \t]*\1[ \t]*(?:\n|$)", re.S)
SHELL_HERESTRING = re.compile(rf"\b(?:{SHELL_NAMES})\b[^\n|;&]*?<<<[ \t]*(?:'([^']*)'|\"((?:[^\"\\]|\\.)*)\"|(\S+))")
# The names a command word built from an unknown variable is judged under; not `pip`, which every call of asks, nor a
# bare installer, which would take any word with options alone (`"$tool" --all`) for an install.
STAND_IN_NAMES = ("git", "python", "uv", *(name for name in PACKAGE_CHANGES if name not in BARE_INSTALLERS))


def get_owner_label(command: Command, directory: str | None, policy: Policy, /) -> str:
    """The command named for a refusal when it is the owner's to run: a denied git command, or a package change when asked."""

    denied = get_denied(command, directory)
    if denied:
        return denied
    is_asked = policy.ask_packages and is_package_change(command, policy.root)

    return " ".join([os.path.basename(command.name), *(word.text for word in command.arguments[:2])]) if is_asked else ""


def find_loose_command(text: str, policy: Policy, /) -> str:
    """The first owner's command (`get_owner_label`) in a text read loosely, word by word, as a program that runs it would."""

    for line in LOOSE_SEPARATOR.split(text):
        words = LOOSE_WORD.findall(line)
        for index, word in enumerate(words):
            name = os.path.basename(word)
            if name in LOOSE_NAMES or name.startswith("python"):
                label = get_owner_label(Command(name, [Word(following, False) for following in words[index + 1 :]]), None, policy)
                if label:
                    return label

    return ""


def get_assigned_values(text: str, /) -> dict[str, str]:  # keys are data
    """The literal each variable of a text is last assigned."""

    return {match.group(1): next(group for group in match.groups()[1:] if group is not None) for match in LITERAL_ASSIGNMENT.finditer(text)}


def is_stdin_shell(arguments: list[str], /) -> bool:
    """Whether a shell with no -c string reads its commands from stdin: no script operand, `-` as one, or `-s`."""

    index = 0
    while index < len(arguments) and arguments[index].startswith(("-", "+")) and arguments[index] not in ("-", "--"):
        if is_cluster(arguments[index]) and "s" in arguments[index][1:]:
            return True
        index += 2 if arguments[index] in SHELL_VALUE_OPTIONS else 1
    index += 1 if arguments[index : index + 1] == ["--"] else 0

    return index >= len(arguments) or arguments[index] == "-"


def get_enclosed(text: str, start: int, /) -> str:
    """The text from `start` up to the parenthesis that closes one opened just before it, or to the end."""

    depth = 1
    index = start
    while index < len(text) and depth:
        depth += {"(": 1, ")": -1}.get(text[index], 0)
        index += 1

    return text[start : index - 1 if depth == 0 else index]


def get_python_calls(code: str, /) -> list[str]:
    """The argument text of each call in Python code that runs a program (`PYTHON_RUNNERS`), up to its closing parenthesis."""

    return [get_enclosed(code, match.end()) for match in PYTHON_RUNNERS.finditer(code)]


def get_substitutions(text: str, /) -> list[str]:
    """The text of each command substitution in a text, `$(...)` (not arithmetic) or between backticks, nested ones too."""

    substitutions: list[str] = []
    for match in SUBSTITUTION_START.finditer(text):
        is_backtick = match.group(0) == "`"
        end = text.find("`", match.end()) if is_backtick else -1
        substitutions.append(text[match.end() : end if end >= 0 else len(text)] if is_backtick else get_enclosed(text, match.end()))

    return substitutions


def get_stdin_scripts(text: str, /) -> list[str]:
    """The scripts a command feeds a shell on stdin: each heredoc body opened on a shell's line, and each here-string."""

    bodies = [match.group(2) for match in SHELL_HEREDOC.finditer(text)]
    strings = [next(group for group in match.groups() if group is not None) for match in SHELL_HERESTRING.finditer(text)]

    return bodies + strings


def get_python_code(words: list[str], /) -> str:
    """The code a `python -c` among the words runs, "" when there is none."""

    for index, word in enumerate(words):
        if not os.path.basename(word).startswith("python"):
            continue
        rest = words[index + 1 :]
        position = 0
        while position < len(rest) and rest[position].startswith("-") and rest[position] != "-c":
            position += 1
        if rest[position : position + 1] == ["-c"] and position + 1 < len(rest):
            return rest[position + 1]

    return ""


def get_variable_command(command: Command, text: str, policy: Policy, /) -> str:
    """The owner's command (`get_owner_label`) a command word built from a variable or a substitution runs, "" when none.

    Variables the text assigns literals to are judged as their values, words split on spaces; a substitution, whose text
    the parser drops, is each substitution of the text followed by the arguments, read loosely with those literals put in
    (with no substitution, each literal a `${NAME}` holds); any other variable is judged under each name it could stand for.
    """

    values = get_assigned_values(text)
    words = [PARAMETER.sub(lambda match: values.get(match.group(1), match.group(0)), word) for word in (command.name, *(word.text for word in command.arguments))]
    if PARAMETER.search(words[0]):
        labels = (get_owner_label(Command(stand_in, command.arguments), None, policy) for stand_in in STAND_IN_NAMES)
        return next((label for label in labels if label), "")
    if "$" in words[0] or "`" in words[0]:
        filled = PARAMETER.sub(lambda match: values.get(match.group(1), match.group(0)), text)
        tail = " ".join(words[1:])
        heads = get_substitutions(filled) or [values[name] for name in BRACED_PARAMETER.findall(text) if name in values]
        return next(filter(None, (find_loose_command(f"{head} {tail}", policy) for head in heads)), "")
    resolved = " ".join(words).split()

    return get_owner_label(Command(resolved[0], [Word(word, False) for word in resolved[1:]]), None, policy) if resolved else ""


def get_hidden_command(command: Command, text: str, policy: Policy, /) -> str:
    """The owner's command (`get_owner_label`) a command runs where the guard cannot read it, "" when none.

    Hidden: a command word built from a variable or a substitution (`get_variable_command`); a shell that reads its
    commands from stdin, where a heredoc body or a here-string is read as commands and anything else (a pipe) is the whole
    text read loosely; or `python -c` code, where the arguments of its calls that run a program are read loosely.
    """

    name = os.path.basename(command.name)
    arguments = [word.text for word in command.arguments]
    if "$" in command.name or "`" in command.name:
        return get_variable_command(command, text, policy)
    if name in SHELLS and not get_shell_string(arguments) and is_stdin_shell(arguments):
        scripts = get_stdin_scripts(text)
        return next(filter(None, (find_script_command(script, policy) for script in scripts)), "") if scripts else find_loose_command(text, policy)
    calls = get_python_calls(get_python_code([command.name, *arguments]))

    return next(filter(None, (find_loose_command(call, policy) for call in calls)), "")


def find_script_command(script: str, policy: Policy, /) -> str:
    """The first owner's command (`get_owner_label`) a shell script runs, read as commands, its own hidden ones included."""

    findings = Findings([], [], [], [], [])
    find_breaches(get_segments(script), None, False, policy, findings, script)

    return next(iter(findings.denied + findings.hidden), "") or next(
        (label for segment in get_segments(script) if (label := get_owner_label(resolve(segment), None, policy))), ""
    )


def is_failing_glob(text: str, directory: str | None, may_have_written: bool, /) -> bool:
    """Whether a glob word matches no file from `directory` (None: not known), so zsh fails on it.

    `may_have_written` says an earlier step of the command may make the file, so what exists now proves nothing.
    """

    if may_have_written or any(character in text for character in UNEXPANDED) or (directory is None and not is_absolute(text)):
        return False

    return next(glob.iglob(resolve_path(text, directory or ""), recursive=True), None) is None


def get_pattern_globs(command: Command, /) -> list[str]:
    """The unquoted glob arguments in a pattern position, once per occurrence: an option that holds one (`--include=*.py`,
    which always fails in zsh), or the value of a pattern option (`find -name`, `rg -g`, `grep --include`)."""

    name = os.path.basename(command.name)
    if name in PATTERN_COMMANDS:
        return []
    pattern_options = GLOB_PATTERN_OPTIONS.get(name, set())
    patterns: list[str] = []
    for index, word in enumerate(command.arguments):
        is_pattern = index > 0 and command.arguments[index - 1].text in pattern_options
        if word.is_glob and (is_pattern or word.text.startswith("-")):
            patterns.append(word.text)

    return patterns


def get_failing_globs(command: Command, directory: str | None, may_have_written: bool, /) -> list[str]:
    """The unquoted glob arguments outside a pattern position that match no file, which zsh refuses."""

    name = os.path.basename(command.name)
    if name in PATTERN_COMMANDS:
        return []
    is_declarer = name in DECLARERS
    patterns = get_pattern_globs(command)
    failing: list[str] = []
    for word in command.arguments:
        is_judged = word.is_glob and not (is_declarer and ASSIGNMENT.match(word.text)) and word.text not in patterns
        if is_judged and is_failing_glob(word.text, directory, may_have_written):
            failing.append(word.text)

    return failing


def quote_glob(text: str, /) -> str:
    """The glob word in single quotes; an option's value is quoted, not its name (`--include='*.py'`)."""

    if text.startswith("-") and "=" in text:
        option, _, value = text.partition("=")
        return f"{option}='{value}'"

    return f"'{text}'"


def get_glob_fix(command: str, words: list[str], cwd: str | None, policy: Policy, /) -> str:
    """The command with each glob word in a pattern position quoted, or "" when that cannot be done safely.

    Safe: no word holds a quote, `$`, a backtick, a backslash or a leading `~`; each word stands alone in the text exactly
    as often as the command uses it, so no heredoc body or string is touched; and the guard's glob rules accept the result.
    """

    fixed = command
    for text in dict.fromkeys(words):
        if text.startswith("~") or any(character in text for character in "'\"$`\\"):
            return ""
        pattern = rf"(?<!\S){re.escape(text)}(?![^\s;|&)])"
        if len(re.findall(pattern, fixed)) != words.count(text):
            return ""
        fixed = re.sub(pattern, lambda _: quote_glob(text), fixed)
    breaches = find_command_breaches(fixed, cwd, policy, is_background=False)
    if fixed == command or "glob" in breaches or "pattern" in breaches:
        return ""

    return fixed


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


def is_temporary(path: str, policy: Policy, /) -> bool:
    return policy.no_tmp and is_under(path, os.path.realpath(TEMPORARY))


def is_repo_write(path: str, policy: Policy, /) -> bool:
    """Whether a path lies in the project outside its scratch folder, where the shell must not write."""

    return bool(policy.scratch) and is_under(path, policy.root) and not is_under(path, policy.scratch)


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
# Deletes
# ===========================================================================


class Scope(NamedTuple):
    """What the walk over a command's top level knows: the command's text, and the variables it has set to a literal so far."""

    text: str
    values: dict[str, str]  # each name a plain `NAME=value` bound once in the text, before this step, and its value


class TrashDelete(NamedTuple):
    """An `rm` or `rmdir` the guard may move to the trash: its words and what it names."""

    words: list[str]  # the segment's words from the command word on, as the reader gave them
    name: str  # `rm` or `rmdir`
    letters: str  # `-`, then `f` (force) and `r` (recursive) as the options give them
    paths: list[str]  # each operand's absolute path, its folder resolved and its last part kept, so a symlink is itself


def expand_variables(text: str, values: Mapping[str, str], /) -> str:
    """The word with each `$NAME` whose literal value is known replaced by it; any other `$` stays."""

    return VARIABLE.sub(lambda match: values.get(match.group(1), match.group(0)), text)


def is_literal(word: Word, text: str, /) -> bool:
    """Whether a word, its known variables expanded to `text`, names one fixed path: no glob, no other `$`, no backtick."""

    return bool(text) and not word.is_glob and "$" not in text and "`" not in text


def get_words_pattern(words: list[str], /) -> str:
    """A regex for one simple command with these words, each written bare, in single quotes or in double quotes.

    A word holding `$` is not matched in single quotes, where the `$` is a literal and no variable; a word no form can
    write gives a pattern that matches nothing.
    """

    spellings: list[str] = []
    for text in words:
        escaped = re.escape(text)
        forms = [escaped] if BARE_WORD.fullmatch(text) else []
        forms += [f"'{escaped}'"] if "$" not in text and "'" not in text else []
        forms += [f'"{escaped}"'] if not any(character in text for character in '"\\`') else []
        if not forms:
            return r"(?!)"
        spellings.append(f"(?:{'|'.join(forms)})")

    return r"(?:^|(?<=[\s;&|(){}`]))" + r"[ \t]+".join(spellings) + r"(?=$|[\s;&|)}<>`])"


def is_written_once(words: list[str], text: str, /) -> bool:
    """Whether a simple command with these words is written exactly once in the text, each word bare or quoted."""

    return len(re.findall(get_words_pattern(words), text)) == 1


def is_throwaway(path: str, policy: Policy, /) -> bool:
    """Whether a resolved path lies strictly inside the scratch folder or the Claude scratchpad, where `rm` works."""

    is_scratch = bool(policy.scratch) and path.startswith(policy.scratch + os.sep)

    return is_scratch or bool(SCRATCHPAD.match(path))


def is_scratch_delete(segment: Segment, command: Command, directory: str | None, scope: Scope | None, policy: Policy, /) -> bool:
    """Whether a plain `rm` or `rmdir` names only literal throwaway paths (`is_throwaway`), never the folder itself.

    A `$NAME` counts as the literal an earlier `NAME=value` gave it only when the command is written plainly enough to be
    found once in the text, which a `'$NAME'`, a literal dollar, is not.
    """

    if directory is None or os.path.basename(command.name) not in SCRATCH_DELETERS:
        return False
    values = scope.values if scope is not None else {}
    paths = [word for word in command.arguments if not word.text.startswith("-")]
    texts = [expand_variables(word.text, values) for word in paths]
    is_found = texts == [word.text for word in paths] or (scope is not None and is_written_once([word.text for word in segment.words], scope.text))
    inside = [is_literal(word, text) and is_throwaway(resolve_path(text, directory), policy) for word, text in zip(paths, texts)]

    return bool(paths) and is_found and all(inside)


def learn_values(segment: Segment, scope: Scope, /) -> None:
    """Records the literal each `NAME=value` of an assignment-only segment sets, and forgets a name set otherwise.

    A name is kept only when the command's text names it once outside `$NAME`, so a loop, a `read`, an `unset` or a second
    assignment of it leaves it unknown.
    """

    if not segment.words or not all(ASSIGNMENT.match(word.text) for word in segment.words):
        return
    for word in segment.words:
        name, _, value = word.text.partition("=")
        bare = name.removesuffix("+")
        uses = re.findall(rf"\b{bare}\b", re.sub(rf"\${bare}\b", "", scope.text))
        if bare == name and is_literal(word, value) and BARE_WORD.fullmatch(value) and len(uses) == 1:
            scope.values[name] = value
        else:
            scope.values.pop(bare, None)


def split_delete_arguments(name: str, arguments: list[Word], /) -> tuple[str, list[Word]] | None:
    """The letters of the options a move keeps (`-`, then `f` and `r`) and the operands of an `rm` or `rmdir`; None for any
    other option, whose meaning a move would drop (`-i`, `-d`, `--one-file-system`, every option of `rmdir`)."""

    letters = "-"
    operands: list[Word] = []
    is_operand = False
    for word in arguments:
        if is_operand or word.text == "-" or not word.text.startswith("-"):
            operands.append(word)
        elif word.text == "--":
            is_operand = True
        elif name == "rm" and word.text in TRASH_OPTIONS:
            letters += TRASH_OPTIONS[word.text]
        elif name == "rm" and is_cluster(word.text) and all(f"-{letter}" in TRASH_OPTIONS for letter in word.text[1:]):
            letters += "".join(TRASH_OPTIONS[f"-{letter}"] for letter in word.text[1:])
        else:
            return None

    return letters, operands


def get_operand_path(text: str, directory: str, /) -> str:
    """The absolute path an operand names, its folder resolved and its last part kept, so a symlink is itself.

    Empty for an operand that ends in `.` or `..`, which rm refuses, or in a `/` after a symlink, whose target rm would empty.
    """

    path = os.path.join(directory, os.path.expanduser(text))
    trimmed = path.rstrip("/")
    folder, last = os.path.split(trimmed)
    if last in ("", ".", "..") or (trimmed != path and os.path.islink(trimmed)):
        return ""

    return os.path.join(os.path.realpath(folder), last)


def is_trashable(path: str, policy: Policy, /) -> bool:
    """Whether the trash may take a path: inside the project, under none of `OWNER_FOLDERS`, and neither the trash, a
    path inside it, nor a folder that holds it, such as the project root."""

    if not policy.trash or not path or not is_under(path, policy.root):
        return False
    parts = set(os.path.relpath(path, policy.root).split(os.sep))

    return not parts & OWNER_FOLDERS and not is_under(path, policy.trash) and not is_under(policy.trash, path)


def has_overlap(paths: list[str], /) -> bool:
    """Whether a path is given twice, or lies inside another path of the list."""

    return any(is_under(first, second) or is_under(second, first) for first, second in itertools.combinations(paths, 2))


def get_trash_delete(segment: Segment, directory: str | None, scope: Scope | None, policy: Policy, /) -> TrashDelete | None:
    """The delete the guard may move to the trash, None when it may not.

    It may not: an `rm` or `rmdir` the top-level shell does not run itself (a prefix such as `sudo`, a path such as
    `/bin/rm`, a string run by another shell), an unknown folder, an option a move would drop, no operand, an operand
    that is no literal, or one the trash may not take (`is_trashable`). A path given twice is `get_trash_fix`'s to refuse.
    """

    words = segment.words
    start = next((index for index, word in enumerate(words) if word.text not in LEADING_WORDS), len(words))
    name = words[start].text if start < len(words) else ""
    split = split_delete_arguments(name, words[start + 1 :]) if name in SCRATCH_DELETERS else None
    if scope is None or directory is None or split is None or not split[1]:
        return None
    letters, operands = split
    texts = [expand_variables(word.text, scope.values) for word in operands]
    paths = [get_operand_path(text, directory) if is_literal(word, text) else "" for word, text in zip(operands, texts)]
    if not all(is_trashable(path, policy) for path in paths):
        return None

    return TrashDelete([word.text for word in words[start:]], name, letters, paths)


# ===========================================================================
# The rules
# ===========================================================================


class MissingGlob(NamedTuple):
    """A glob word that matches no file, and the folder it was matched from."""

    pattern: str
    folder: str


class Findings(NamedTuple):
    """What the rules found that a refusal or a change of the call needs, filled as the command is walked."""

    missing_globs: list[MissingGlob]
    pattern_globs: list[str]  # once per occurrence, so a change can check it found each one in the text
    trash_deletes: list[TrashDelete]
    denied: list[str]  # each git command refused as the owner's, named for the message
    hidden: list[str]  # each owner's command found where the guard cannot read it


def find_breaches(
    segments: list[Segment], cwd: str | None, judges_globs: bool, policy: Policy, findings: Findings, text: str, /, *, scope: Scope | None = None
) -> list[str]:
    """The rules some simple commands break, each once, in rule order.

    `cwd` is the folder they start in, None when that is not known; `judges_globs` says their shell is zsh, the one that
    fails on a glob with no match; `findings` collects what a refusal or a change of the call needs. `scope` is given for
    the commands the top-level shell runs itself, whose variables it reads and whose deletes may go to the trash; None for
    a string run by another shell, `eval` or `find -exec`. `text` is the whole command, read loosely where a command is
    hidden. A command `ssh` runs on another machine is judged only by `REMOTE_RULES`, from no known folder.
    """

    breaches: list[str] = []
    directory = cwd
    may_have_written = False
    for segment in segments:
        command = resolve(segment)
        globs = (judges_globs, may_have_written)
        breaches.extend(get_command_breaches(segment, command, directory, globs, scope, findings, policy, text))
        if scope is not None and not segment.in_group:
            learn_values(segment, scope)
        name = os.path.basename(command.name)
        inner_judges = judges_globs and not (name in SHELLS and name != "zsh") and name not in JOINING_RUNNERS
        is_remote = name in REMOTE_RUNNERS
        inner = find_breaches(get_inner_segments(command), None if is_remote else directory, inner_judges, policy, findings, text)
        breaches.extend(rule for rule in inner if not is_remote or rule in REMOTE_RULES)
        may_have_written = may_have_written or name not in READ_ONLY_COMMANDS or bool(get_written_words(segment, command, directory))
        directory = get_directory_after(command, segment.in_group, directory)

    return [rule for rule in MESSAGES if rule in breaches]


def find_command_breaches(command: str, cwd: str | None, policy: Policy, /, *, is_background: bool, findings: Findings | None = None) -> list[str]:
    """The rules a whole shell command breaks, soft ones included (`SOFT_RULES`), from the folder it starts in.

    `is_background` lets it sleep: a call that runs in the background raises no `sleep` breach.
    A `Findings` given as `findings` collects what a refusal or a change of the call needs.
    """

    is_zsh = os.path.basename(os.environ.get("SHELL") or "") == "zsh"
    collected = findings if findings is not None else Findings([], [], [], [], [])

    breaches = find_breaches(get_segments(command), cwd, is_zsh, policy, collected, command, scope=Scope(command, {}))

    return [rule for rule in breaches if rule != "sleep" or not is_background]


def get_command_breaches(
    segment: Segment, command: Command, directory: str | None, globs: tuple[bool, bool], scope: Scope | None, findings: Findings, policy: Policy, text: str, /
) -> list[str]:
    """The rules one simple command breaks, and what a refusal or a change needs of it, added to `findings`.

    `directory` is where it runs, None when unknown; `globs` says whether globs are judged and whether an earlier step may
    have written; `scope` is None for a string another shell runs; `text` is the whole command.
    """

    words = get_written_words(segment, command, directory)
    written = get_written_paths(words, directory)
    arguments = [word.text for word in command.arguments]
    moved = get_written_paths(get_moved_sources(os.path.basename(command.name), arguments), directory)
    is_unknown_write = bool(policy.scratch) and directory is None and not all(is_absolute(word) for word in words)
    is_deleting = is_delete(command) and not is_scratch_delete(segment, command, directory, scope, policy)
    trash = get_trash_delete(segment, directory, scope, policy) if is_deleting else None
    missing = get_failing_globs(command, directory, globs[1]) if globs[0] else []
    patterns = get_pattern_globs(command) if globs[0] else []
    findings.missing_globs.extend(MissingGlob(text, directory or "an unknown folder") for text in missing)
    findings.pattern_globs.extend(patterns)
    findings.trash_deletes.extend([trash] if trash is not None else [])
    denied = get_denied(command, directory)
    hidden = get_hidden_command(command, text, policy)
    findings.denied.extend([denied] if denied else [])
    findings.hidden.extend([hidden] if hidden else [])
    checks = [
        ("delete", is_deleting and trash is None),
        ("denied", bool(denied)),
        ("hidden", bool(hidden)),
        (ASK_RULE, policy.ask_packages and is_package_change(command, policy.root)),
        ("glob", bool(missing)),
        ("pattern", bool(patterns)),
        ("trash", trash is not None),
        ("temporary", any(is_temporary(path, policy) for path in written)),
        ("repo", is_unknown_write or any(is_repo_write(path, policy) for path in [*written, *moved])),
        ("sleep", os.path.basename(command.name) == "sleep"),
    ]

    return [rule for rule, is_breach in checks if is_breach]


def is_direct_sleep(segment: Segment, /) -> bool:
    """Whether a top-level segment runs the `sleep` function-shadowing can catch: its first word past `do`, `then` and the like.

    A segment in a polling loop, a subshell, a pipeline, a substitution or the background is not direct.
    """

    words = [word.text for word in segment.words]
    index = 0
    while index < len(words) and words[index] in LEADING_WORDS:
        index += 1

    return not segment.in_loop and not segment.in_group and words[index : index + 1] == ["sleep"]


def find_sleeps(segments: list[Segment], policy: Policy, /, *, is_top_level: bool = True) -> list[bool]:
    """Whether each `sleep` the segments run, nested strings included, is a direct command of the top-level command."""

    flags: list[bool] = []
    for segment in segments:
        command = resolve(segment, policy)
        if os.path.basename(command.name) == "sleep":
            flags.append(is_top_level and is_direct_sleep(segment))
        flags.extend(find_sleeps(get_inner_segments(command), policy, is_top_level=False))

    return flags


class SleepFix(NamedTuple):
    """A sleeping call's changed input and the note that says how it changed."""

    tool_input: dict  # keys are data
    note: str


def get_sleep_fix(command: str, tool_input: dict, policy: Policy, /) -> SleepFix:  # keys are data
    """The whole input of a foreground call that sleeps, changed so it does not wait, and the note that says how.

    Every `sleep` direct: the command gets `SLEEP_SHADOW` in front. Any other `sleep`: the call moves to the background.
    """

    flags = find_sleeps(get_segments(command), policy)
    if flags and all(flags):
        return SleepFix({**tool_input, "command": SLEEP_SHADOW + command}, MESSAGES["sleep"])

    return SleepFix({**tool_input, "run_in_background": True}, SLEEP_BACKGROUND_NOTE)


# ===========================================================================
# Changing the call
# ===========================================================================


class Rewrite(NamedTuple):
    """A call's input after the guard's changes, the notes that say what changed, and the rules no change could meet."""

    tool_input: dict  # keys are data
    notes: list[str]
    refused: list[str]


def get_trash_folder(call_id: str, policy: Policy, /) -> str:
    """This call's trash folder, `__harness__/trash/<tool_use_id>` in the project; "" with no usable id or no trash."""

    name = re.sub(r"[^A-Za-z0-9_-]", "", call_id)

    return os.path.join(policy.trash, name) if name and policy.trash else ""


def get_trash_words(delete: TrashDelete, folder: str, policy: Policy, /) -> list[str]:
    """The words of the `harness_trash` call that replaces a delete: its name and letters, then each path and its target."""

    pairs = [(path, os.path.join(folder, os.path.relpath(path, policy.root))) for path in delete.paths]

    return ["harness_trash", delete.name, delete.letters, *itertools.chain.from_iterable(pairs)]


def is_spliced_alone(command: str, spliced: str, replacements: Mapping[tuple[str, ...], list[str]], /) -> bool:
    """Whether the spliced command runs the original's simple commands, each spliced delete as its replacement and every
    other one word for word, with the same redirects and grouping."""

    expected = []
    for segment in get_segments(command):
        texts = [word.text for word in segment.words]
        start = next((index for index, text in enumerate(texts) if text not in LEADING_WORDS), len(texts))
        texts = texts[:start] + replacements.get(tuple(texts[start:]), texts[start:])
        expected.append((texts, segment.redirects, segment.in_loop, segment.in_group))
    found = [([word.text for word in segment.words], segment.redirects, segment.in_loop, segment.in_group) for segment in get_segments(spliced)]

    return found == expected


def get_trash_fix(command: str, deletes: list[TrashDelete], folder: str, policy: Policy, /) -> str:
    """The command with each delete spliced, in its text, into a call of `harness_trash`; "" when that is not safe.

    Not safe: a path given twice or inside another, a delete not found in the text, or a result that differs from the
    original anywhere but in the spliced deletes, as when the first match lies in a string or a heredoc body.
    """

    if has_overlap([path for delete in deletes for path in delete.paths]):
        return ""
    spliced = command
    replacements: dict[tuple[str, ...], list[str]] = {}
    for delete in deletes:
        match = re.search(get_words_pattern(delete.words), spliced)
        if match is None:
            return ""
        words = get_trash_words(delete, folder, policy)
        spliced = spliced[: match.start()] + shlex.join(words) + spliced[match.end() :]
        replacements[tuple(delete.words)] = words

    return spliced if is_spliced_alone(command, spliced, replacements) else ""


def get_rewrite(breaches: list[str], tool_input: dict, findings: Findings, cwd: str, call_id: str, policy: Policy, /) -> Rewrite:  # keys are data
    """The call changed for its soft rules, in order: globs in a pattern position quoted, deletes moved to the trash, then a
    `sleep` removed or the call sent to the background. A change that cannot be shown safe is named in `refused`."""

    original = tool_input.get("command") or ""
    command = original
    notes = [f"The harness guard let this run: {MESSAGES[rule]}" for rule in breaches if rule in NOTED_RULES]
    if "pattern" in breaches:
        command = get_glob_fix(command, findings.pattern_globs, cwd, policy)
        if not command:
            return Rewrite(tool_input, [], ["pattern"])
        notes.append(f"The harness guard changed this call: {MESSAGES['pattern']}")
    folder = get_trash_folder(call_id, policy) if "trash" in breaches else ""
    if "trash" in breaches:
        command = get_trash_fix(command, findings.trash_deletes, folder, policy) if folder else ""
        if not command:
            return Rewrite(tool_input, [], ["trash"])
        notes.append(f"The harness guard changed this call: {MESSAGES['trash'].format(folder=folder)}")
    changed = {**tool_input, "command": command} if command != original else dict(tool_input)
    if "sleep" in breaches:
        changed, note = get_sleep_fix(command, changed, policy)
        notes.append(f"The harness guard changed this call: {note}")
    if folder:
        ensure_harness_folder(Path(policy.root))
        changed = {**changed, "command": TRASH_HELPER + changed["command"]}

    return Rewrite(changed, notes, [])


def make_soft_output(rewrite: Rewrite, tool_input: dict, /) -> dict:  # keys are data
    """The PreToolUse output that lets the call run with its notes, and with its changed input when the guard changed it.

    Never carries a `permissionDecision`: the owner's permission prompts still apply to the call.
    """

    output: dict = {"hookEventName": "PreToolUse"}
    if rewrite.tool_input != tool_input:
        output["updatedInput"] = rewrite.tool_input
    output["additionalContext"] = "\n".join(rewrite.notes)

    return {"hookSpecificOutput": output}


def refuse(rules: list[str], findings: Findings, /) -> int:
    """Refuses the call with each rule's message, or asks the owner when the package rule is the only one; the exit code."""

    missing = findings.missing_globs[0] if findings.missing_globs else MissingGlob("*", "this folder")
    glob_text = MESSAGES["glob"].format(folder=missing.folder, pattern=missing.pattern)
    denied = MESSAGES["denied"].format(what=(findings.denied or ["this git command"])[0])
    hidden = MESSAGES["hidden"].format(what=(findings.hidden or ["this command"])[0])
    texts = {**MESSAGES, "glob": glob_text, "pattern": PATTERN_REFUSAL, "trash": MESSAGES["delete"], "denied": denied, "hidden": hidden}
    lines = list(dict.fromkeys(f"Blocked by the harness guard: {texts[rule]}" for rule in rules if rule != ASK_RULE))
    if not lines:
        decision = {"hookEventName": "PreToolUse", "permissionDecision": "ask", "permissionDecisionReason": f"The harness guard: {MESSAGES[ASK_RULE]}"}
        print(json.dumps({"hookSpecificOutput": decision}))
        return 0
    print("\n".join(lines), file=sys.stderr)

    return 2


def main() -> int:
    event = json.load(sys.stdin)
    tool_input = event.get("tool_input") or {}
    cwd = event.get("cwd") or os.getcwd()
    policy = get_policy(cwd)
    findings = Findings([], [], [], [], [])
    if event.get("tool_name") == "Bash":
        command = tool_input.get("command") or ""
        breaches = find_command_breaches(command, cwd, policy, is_background=tool_input.get("run_in_background") is True, findings=findings)
    else:
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        breaches = ["temporary"] if is_temporary(resolve_path(path, cwd), policy) else []
    hard = [rule for rule in breaches if rule not in SOFT_RULES]
    if not hard:
        rewrite = get_rewrite(breaches, tool_input, findings, cwd, str(event.get("tool_use_id") or ""), policy)
        if not rewrite.refused:
            if breaches:
                print(json.dumps(make_soft_output(rewrite, tool_input)))
            return 0
        hard = rewrite.refused
    # A delete the guard did not move stays refused, even beside a rule that only asks the owner.
    hard += [rule for rule in breaches if rule == "trash"]

    return refuse(hard, findings)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # fail open (exit 1 lets the call run): a bug in the guard must not block every call
        print(f"the harness guard failed and let the call run: {error!r}", file=sys.stderr)
        sys.exit(1)
