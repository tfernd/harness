#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///

from __future__ import annotations

import glob
import itertools
import json
import os
import re
import shlex
import sys
from collections.abc import Callable, Mapping, Set
from datetime import UTC, datetime, timedelta
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

DELETERS = frozenset({"rm", "rmdir", "unlink", "shred"})
SCRATCH_DELETERS = frozenset({"rm", "rmdir"})
READ_ONLY_COMMANDS = frozenset("cat ls grep rg sed head tail wc echo printf cd pwd awk sort uniq cut tr true false which test stat du file date [ [[".split())
UV_VALUE_OPTIONS = frozenset({"--with", "--with-requirements", "--with-editable", "--project", "--directory", "--exclude-newer", "--python", "-p", "--group", "--extra", "--env-file"})
UV_DENIED = frozenset({"add", "remove", "lock", "sync", "pip", "tool"})
PUSH_DENIED = frozenset({"--force", "--force-with-lease", "--force-if-includes", "--mirror", "--delete", "--prune"})
PUSH_DENIED_LETTERS = frozenset("fd")
CREATORS = frozenset({"tee", "mkdir", "touch"})
MOVERS = frozenset({"cp", "mv", "ln", "install", "rsync"})
TARGET_MOVERS = frozenset({"cp", "mv", "ln", "install"})
IN_PLACE_EDITORS = frozenset({"sed", "perl"})
TAR_LONG_MODES = {"--extract": "x", "--create": "c", "--append": "r", "--update": "u"}
TEMPORARY = "/tmp"
PATTERN_COMMANDS = frozenset({"[", "[[", "case", "test"})
GLOB_PATTERN_OPTIONS = {
    "find": {"-name", "-iname", "-path", "-ipath", "-wholename", "-iwholename", "-lname", "-ilname", "-regex", "-iregex"},
    "rg": {"-g", "--glob", "--iglob"},
    "grep": {"--include", "--exclude", "--exclude-dir"},
}

UNEXPANDED = "$`{"
DECLARERS = frozenset({"export", "readonly", "declare", "typeset", "local"})
DIRECTORY_CHANGERS = frozenset({"cd", "pushd", "popd"})
IN_SHELL_RUNNERS = frozenset({"eval", "source", "."})
OWNER_FOLDERS = frozenset({"node_modules", "dist", ".venv", ".git"})
TRASH_OPTIONS = {"-f": "f", "-r": "r", "-R": "r", "-v": "", "--force": "f", "--recursive": "r", "--verbose": ""}
USER_ID = os.getuid() if hasattr(os, "getuid") else -1
SCRATCHPAD = re.compile(rf"{re.escape(os.path.realpath(TEMPORARY))}/claude-{USER_ID}/(?:[^/]+/)*scratchpad/[^/]")
VARIABLE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")
BARE_WORD = re.compile(r"[\w./@%+,:=~$-]+")
TRASH_HELPER = (
    'harness_trash() { local name="$1" flags="$2" code=0 why; shift 2; while [ "$#" -ge 2 ]; do why=; '
    'if [ ! -e "$1" ] && [ ! -L "$1" ]; then case "$flags" in *f*) why=skip;; *) why="No such file or directory";; esac; '
    'elif [ -L "$1" ] || [ ! -d "$1" ]; then [ "$name" = rmdir ] && why="Not a directory"; '
    'elif [ "$name" = rmdir ]; then [ -z "$(command ls -A -- "$1")" ] || why="Directory not empty"; '
    'else case "$flags" in *r*) ;; *) why="Is a directory";; esac; fi; '
    'case "$why" in "") command mkdir -p -- "${2%/*}" && command mv -- "$1" "$2" || code=1;; skip) ;; '
    '*) printf "%s: cannot remove \'%s\': %s\\n" "$name" "$1" "$why" >&2; code=1;; esac; shift 2; done; return "$code"; }; '
)

ASK_RULE = "packages"
CLOUD_RULE = "cloud"
INSTALLER_RULE = "installer"
ASK_RULES = (ASK_RULE, CLOUD_RULE, INSTALLER_RULE)
REMOTE_RULES = frozenset({"denied", "hidden", *ASK_RULES})
MESSAGES = {
    "delete": "nothing is deleted without the owner's word. Your own throwaway files go in `__scratch__/`, where `rm` works; "
    "a tracked file that must go uses `git rm`.",
    "denied": "`{what}` rewrites history or discards uncommitted work, which is the owner's to run: leave it to them and say so "
    "in your report.",
    "hidden": "`{what}` runs where the guard cannot read the command (a variable as the command, a shell fed from stdin, a "
    "string built at run time, or Python's os.system or subprocess). Rewriting history or discarding work is the owner's to "
    "run and a package change is asked: write the command plainly as its own call.",
    ASK_RULE: "changing packages is the owner's to run, so they are asked first. `uvx`, `uv tool`, `npx`, `bunx` and `dlx` "
    "fetch a tool outside the lock: run the project's own as `uv run --frozen <tool>` or through a package.json script. "
    "`uvx`, `uv tool run`, `npx` and `bunx` run unasked with a release delay (`tool_delay_days`) added.",
    "delay": "this tool is fetched outside the lock, so the guard added a {days}-day release delay (no release newer than {days} days "
    "is fetched) and let it run. Put the delay flag first yourself, or run the project's own tool, to skip this note.",
    CLOUD_RULE: "`{what}` writes to an AWS account, and that cannot be undone from this session, so the owner is asked first: run it "
    "yourself, or have the owner approve it. Reads (`describe-`, `list-`, `get-`, `s3 ls`) run freely; see `harness:aws-cli`.",
    INSTALLER_RULE: "`{what}` runs code that nobody has read, so the owner is asked first: download it to a file in `__scratch__/`, read it, "
    "then run that file, or have the owner approve the pipe.",
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
PATTERN_REFUSAL = (
    "this unquoted glob is a pattern for the command, which zsh would expand first, and the guard could not quote it safely. "
    "Quote it (`--include='*.py'`), or use `rg -g '*.py'`."
)
SOFT_RULES = ("pattern", "trash", "temporary", "repo", "sleep", "delay")
NOTED_RULES = ("temporary", "repo")
SLEEP_BACKGROUND_NOTE = (
    "this command waits with `sleep` (a polling loop, a wrapper or a nested string), so it now runs in the background and its exit "
    "wakes you: read the output then, not before. Waiting on a timer in the foreground spends the owner's time (`harness:tool-habits`, Waiting)."
)
SLEEP_SHADOW = "sleep() { :; }; "


class Policy(NamedTuple):

    root: str = ""
    scratch: str = ""
    trash: str = ""
    no_tmp: bool = False
    ask_packages: bool = False
    ask_cloud: bool = False
    ask_installers: bool = False
    tool_delay_days: int = 0


def get_delay_days(value: object, /) -> int:

    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def get_policy(cwd: str, /) -> Policy:

    root, config = find_project(cwd)
    guard = config.get("guard", {})

    return Policy(
        root=str(root),
        scratch=get_scratch(root, config),
        trash=str(root / TRASH_FOLDER) if is_project_root(root) else "",
        no_tmp=bool(guard.get("no_tmp")),
        ask_packages=bool(guard.get("ask_packages") or guard.get("deny_packages")),
        ask_cloud=bool(guard.get("ask_cloud")),
        ask_installers=bool(guard.get("ask_installers")),
        tool_delay_days=get_delay_days(guard.get("tool_delay_days")),
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
TOOL_RUNNERS = frozenset({"uvx", "npx", "bunx", "pnpx"})
LOCAL_RUNNERS = frozenset({"npx", "bunx", "pnpx"})
MANAGER_RUNNERS = {"npm": frozenset({"exec", "x"}), "bun": frozenset({"x"}), "pnpm": frozenset({"dlx"}), "yarn": frozenset({"dlx"})}
FETCHING_OPTIONS = frozenset({"-p", "--package", "-c", "--call"})
DELAYED_RUNNERS = frozenset({"uvx", "npx", "bunx"})
SECONDS_PER_DAY = 86400
LOCAL_TOOL = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*")
BARE_INSTALLERS = frozenset({"yarn", "bundle"})
INFORMATION_OPTIONS = frozenset({"-v", "-V", "--version", "-h", "--help"})
NESTED_CHANGES = {"audit": frozenset({"fix", "--fix"}), "env": frozenset({"create", "update", "remove"})}
SETUP_INSTALLS = frozenset({"install", "develop"})


def is_local_run(name: str, arguments: list[str], root: str, /) -> bool:

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


class DelayRun(NamedTuple):

    lead: list[str]
    words: list[str]
    flag: str
    is_flagged: bool


def get_delay_flag(name: str, days: int, /) -> str:

    if name == "npx":
        return "--before=" + (datetime.now(UTC).date() - timedelta(days=days)).isoformat()
    if name == "bunx":
        return f"--minimum-release-age={days * SECONDS_PER_DAY}"

    return f"--exclude-newer={days} days"


def get_uv_run_options(command: Command, /) -> list[str]:

    arguments = [word.text for word in command.arguments]
    if os.path.basename(command.name) != "uv" or arguments[:1] != ["run"]:
        return []
    end = skip_options(command.arguments, 1, UV_VALUE_OPTIONS)

    return arguments[1:end]


def get_delay_lead(command: Command, /) -> list[str]:

    arguments = [word.text for word in command.arguments]
    name = os.path.basename(command.name)
    if any(option.startswith("--with") for option in get_uv_run_options(command)):
        return [command.name, "run"]
    if name in DELAYED_RUNNERS and arguments:
        return [command.name]
    if name == "uv" and arguments[:2] == ["tool", "run"] and arguments[2:]:
        return [command.name, "tool", "run"]

    return []


def get_delay_run(segment: Segment, command: Command, policy: Policy, /) -> DelayRun | None:

    lead = get_delay_lead(command)
    if not lead:
        return None
    texts = [word.text for word in segment.words]
    start = next((index for index, text in enumerate(texts) if text not in LEADING_WORDS), len(texts))
    words = texts[start:]
    position = next((index for index in range(len(words)) if words[index : index + len(lead)] == lead), -1)
    if position < 0:
        return None
    name = os.path.basename(command.name)
    flag = get_delay_flag(name if name != "uv" else "uvx", policy.tool_delay_days)
    option = flag.split("=")[0]
    following = get_uv_run_options(command) if lead[1:] == ["run"] else words[position + len(lead) : position + len(lead) + 1]
    is_flagged = any(text == option or text.startswith(option + "=") for text in following)

    return DelayRun(lead, words, flag, is_flagged)


def is_uv_change(words: list[Word], /) -> bool:

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

    positional = get_positional(arguments)

    return bool(positional) and os.path.basename(positional[0]) == "setup.py" and bool(SETUP_INSTALLS & set(positional[1:]))


def is_module_pip(arguments: list[str], /) -> bool:

    return any(
        argument == "-mpip" or (argument == "-m" and arguments[index + 1 : index + 2] == ["pip"])
        for index, argument in enumerate(arguments)
    )


AWS_VALUE_OPTIONS = frozenset({
    "--profile", "--region", "--output", "--endpoint-url", "--query", "--color", "--ca-bundle", "--cli-read-timeout",
    "--cli-connect-timeout", "--exclude", "--include",
})
AWS_READ_PREFIXES = ("describe-", "list-", "get-", "batch-get-", "head-", "lookup-", "search-")
AWS_READ_OPERATIONS = frozenset({"filter-log-events", "wait", "help"})
AWS_SERVICE_READS = {
    "s3": frozenset({"ls", "presign"}),
    "logs": frozenset({"tail"}),
    "configure": frozenset({"list", "get"}),
    "dynamodb": frozenset({"query", "scan"}),
    "cloudformation": frozenset({"validate-template"}),
    "resource-explorer-2": frozenset({"search"}),
}
AWS_TRANSFERS = frozenset({"cp", "sync"})
AWS_INFORMATION_OPTIONS = frozenset({"--version", "--help"})
INFRASTRUCTURE_WRITES = {
    "sam": frozenset({"deploy", "delete", "sync", "publish", "bootstrap"}),
    "cdk": frozenset({"deploy", "destroy", "bootstrap", "watch", "import"}),
}
S3_SCHEME = "s3://"
CLOUD_TOOLS = frozenset({"aws", *INFRASTRUCTURE_WRITES})
CLOUD_WRAPPERS = frozenset({"npx", "bunx", "pnpx", "uv", "uvx", "poetry", "pnpm", "npm", "yarn", "bun", "pipx"})
FETCHERS = frozenset({"curl", "wget", "fetch"})
CODE_READERS = frozenset({"node", "perl", "ruby"})
SUBSTITUTION_READERS = frozenset({"eval", "source", "."})
CODE_OPTION_LETTERS = frozenset("ceEmp")
SUBSTITUTION_WORD = "$"


def get_positionals(arguments: list[str], value_options: Set[str], /) -> list[str]:

    positionals: list[str] = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument.startswith("-") and argument != "-":
            index += 2 if argument in value_options else 1
        else:
            positionals.append(argument)
            index += 1

    return positionals


def is_aws_download(paths: list[str], /) -> bool:

    return len(paths) == 2 and paths[0].startswith(S3_SCHEME) and not paths[1].startswith(S3_SCHEME)


def is_aws_read(arguments: list[str], /) -> bool:

    positionals = get_positionals(arguments, AWS_VALUE_OPTIONS)
    if AWS_INFORMATION_OPTIONS & set(arguments) or not positionals:
        return True
    service = positionals[0]
    operation = positionals[1] if len(positionals) > 1 else ""
    if operation == "" and service == "configure":
        return False
    if operation == "" or "help" in positionals[:2] or (len(positionals) == 3 and positionals[2] == "help"):
        return True
    if service == "s3" and operation in AWS_TRANSFERS and is_aws_download(positionals[2:]):
        return True

    return operation in AWS_SERVICE_READS.get(service, frozenset()) or operation in AWS_READ_OPERATIONS or operation.startswith(AWS_READ_PREFIXES)


def get_cloud_label(command: Command, /) -> str:

    name = os.path.basename(command.name)
    arguments = [word.text for word in command.arguments]
    if name in CLOUD_WRAPPERS:
        wrapped = next((index for index, argument in enumerate(arguments) if os.path.basename(argument) in CLOUD_TOOLS), -1)
        return get_cloud_label(Command(arguments[wrapped], command.arguments[wrapped + 1 :])) if wrapped >= 0 else ""
    if name == "aws":
        return "" if is_aws_read(arguments) else " ".join(["aws", *get_positionals(arguments, AWS_VALUE_OPTIONS)[:2]])
    writes = INFRASTRUCTURE_WRITES.get(name, frozenset()) & set(arguments)

    return f"{name} {min(writes)}" if writes and "--help" not in arguments else ""


def reads_stdin_as_code(name: str, arguments: list[str], /) -> bool:

    if name in SHELLS:
        return is_stdin_shell(arguments)
    has_code_option = any(
        argument.startswith("-") and not argument.startswith("--") and CODE_OPTION_LETTERS & set(argument[1:]) for argument in arguments
    )
    positionals = [argument for argument in arguments if not argument.startswith("-")]

    return not has_code_option and not positionals


def is_code_runner(name: str, /) -> bool:

    return name in SHELLS or name in CODE_READERS or name.startswith("python")


def is_substitution_fed(name: str, arguments: list[str], /) -> bool:

    if not (is_code_runner(name) or name in SUBSTITUTION_READERS):
        return False
    operands = [argument for argument in arguments if not argument.startswith("-") or argument == "-"]

    return operands[:1] == [SUBSTITUTION_WORD]


def find_chain_fetcher(segments: list[Segment], index: int, /) -> str:

    position = index - 1
    while position >= 0 and segments[position].in_group:
        name = os.path.basename(resolve(segments[position]).name)
        if name in FETCHERS:
            return name
        position -= 1

    return ""


def find_installers(segments: list[Segment], /) -> list[str]:

    labels: list[str] = []
    for index, segment in enumerate(segments):
        command = resolve(segment)
        name = os.path.basename(command.name)
        arguments = [word.text for word in command.arguments]
        fetcher = find_chain_fetcher(segments, index)
        if fetcher and segment.in_group and is_code_runner(name) and reads_stdin_as_code(name, arguments):
            labels.append(f"{fetcher} ... | {name}")
        elif fetcher and is_substitution_fed(name, arguments):
            labels.append(f"{name} with the output of {fetcher}")

    return labels



MIN_PREFIX = 3
GIT_VALUE_LETTERS = {"checkout": "bB", "switch": "cC", "restore": "s", "branch": "u", "tag": "mFu", "commit": "mFCct", "update-ref": "m", "fetch": "jo"}
GIT_ALWAYS_DENIED = frozenset({"rebase", "filter-branch", "filter-repo"})
REBASE_OFF = frozenset({"false", "no", "0", "off"})


class GitArguments(NamedTuple):

    letters: str
    long_options: list[str]
    operands: list[str]
    paths: list[str]


GitCheck = Callable[[GitArguments, str | None], str]


def parse_git_arguments(arguments: list[str], value_letters: str, /) -> GitArguments:

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

    name = word.split("=", 1)[0]

    return len(name) >= MIN_PREFIX and option.startswith(name)


def has_flag(parsed: GitArguments, letter: str, *options: str) -> bool:

    return (bool(letter) and letter in parsed.letters) or any(is_long_prefix(word, option) for word in parsed.long_options for option in options)


def get_checkout_denial(parsed: GitArguments, directory: str | None, /) -> str:

    if has_flag(parsed, "f", "--force"):
        return "git checkout --force"
    if "B" in parsed.letters:
        return "git checkout -B"
    is_path = [operand == "." or (directory is not None and os.path.lexists(resolve_path(operand, directory))) for operand in parsed.operands]

    return "git checkout <paths>" if parsed.paths or any(is_path) else ""


def get_restore_denial(parsed: GitArguments, directory: str | None, /) -> str:

    is_staged_only = has_flag(parsed, "S", "--staged") and not has_flag(parsed, "W", "--worktree")

    return "" if is_staged_only else "git restore"


def get_branch_denial(parsed: GitArguments, directory: str | None, /) -> str:

    is_forced = has_flag(parsed, "f", "--force")
    if "D" in parsed.letters or (is_forced and has_flag(parsed, "d", "--delete")):
        return "git branch -D"

    return "git branch --force" if is_forced or "M" in parsed.letters or "C" in parsed.letters else ""


def get_switch_denial(parsed: GitArguments, directory: str | None, /) -> str:

    if has_flag(parsed, "f", "--force", "--discard-changes"):
        return "git switch --discard-changes"

    return "git switch --force-create" if has_flag(parsed, "C", "--force-create") else ""


def get_read_tree_denial(parsed: GitArguments, directory: str | None, /) -> str:

    return "git read-tree --reset -u" if has_flag(parsed, "", "--reset") and has_flag(parsed, "u") else ""


def get_pull_denial(parsed: GitArguments, directory: str | None, /) -> str:

    rebases = [word for word in parsed.long_options if is_long_prefix(word, "--rebase")]
    is_rebase = "r" in parsed.letters or any(word.partition("=")[2].lower() not in REBASE_OFF for word in rebases)

    return "git pull --rebase" if is_rebase else ""


def get_fetch_denial(parsed: GitArguments, directory: str | None, /) -> str:

    is_forced = has_flag(parsed, "f", "--force") or any(operand.startswith("+") for operand in parsed.operands)
    targets = [operand.split(":", 1)[1] for operand in parsed.operands if ":" in operand]
    is_into_ref = any(target and not target.startswith("refs/remotes/") for target in targets)

    return "git fetch --force into a ref" if is_forced and is_into_ref else ""


def get_flag_denial(subcommand: str, letter: str, option: str, /) -> GitCheck:

    return lambda parsed, directory: f"git {subcommand} {option}" if has_flag(parsed, letter, option) else ""


def get_operand_denial(subcommand: str, operands: Set[str], /) -> GitCheck:

    return lambda parsed, directory: f"git {subcommand} {parsed.operands[0]}" if parsed.operands[:1] and parsed.operands[0] in operands else ""


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

    for argument in arguments:
        if any(is_long_prefix(argument, option) for option in PUSH_DENIED) or argument.startswith(("+", ":")):
            return True
        if is_cluster(argument) and PUSH_DENIED_LETTERS & set(argument[1:]):
            return True

    return False


def get_git_denial(arguments: list[str], directory: str | None, /) -> str:

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

    if os.path.basename(command.name) != "git":
        return ""

    return get_git_denial([word.text for word in command.arguments], directory)



LOOSE_WORD = re.compile(r"[^\s;&|(){}<>'\"`,\[\]]+")
LOOSE_SEPARATOR = re.compile(r"&&|\|\||[;\n|&]")
LOOSE_NAMES = frozenset({"git", "pip", "pip3", "uv", *TOOL_RUNNERS, *PACKAGE_CHANGES})
LITERAL_ASSIGNMENT = re.compile(r"(?:^|(?<=[\s;&|(]))([A-Za-z_][A-Za-z0-9_]*)=(?:'([^']*)'|\"([^\"$`\\]*)\"|([^\s;&|()<>'\"`$\\]*))")
SUBSTITUTION_START = re.compile(r"\$\((?!\()|`")
BRACED_PARAMETER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
PARAMETER = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
PYTHON_RUNNERS = re.compile(r"\b(?:os\.(?:system|popen|exec\w*|spawn\w*)|subprocess\.\w+|pty\.spawn)\s*\(")
SHELL_NAMES = "|".join(sorted(SHELLS))
SHELL_HEREDOC = re.compile(rf"\b(?:{SHELL_NAMES})\b[^\n]*?<<-?[ \t]*['\"]?(\w+)['\"]?[^\n]*\n(.*?)\n[ \t]*\1[ \t]*(?:\n|$)", re.S)
SHELL_HERESTRING = re.compile(rf"\b(?:{SHELL_NAMES})\b[^\n|;&]*?<<<[ \t]*(?:'([^']*)'|\"((?:[^\"\\]|\\.)*)\"|(\S+))")
STAND_IN_NAMES = ("git", "python", "uv", *(name for name in PACKAGE_CHANGES if name not in BARE_INSTALLERS))


def get_owner_label(command: Command, directory: str | None, policy: Policy, /) -> str:

    denied = get_denied(command, directory)
    if denied:
        return denied
    is_asked = policy.ask_packages and is_package_change(command, policy.root)

    return " ".join([os.path.basename(command.name), *(word.text for word in command.arguments[:2])]) if is_asked else ""


def find_loose_command(text: str, policy: Policy, /) -> str:

    for line in LOOSE_SEPARATOR.split(text):
        words = LOOSE_WORD.findall(line)
        for index, word in enumerate(words):
            name = os.path.basename(word)
            if name in LOOSE_NAMES or name.startswith("python"):
                label = get_owner_label(Command(name, [Word(following, False) for following in words[index + 1 :]]), None, policy)
                if label:
                    return label

    return ""


def get_assigned_values(text: str, /) -> dict[str, str]:

    return {match.group(1): next(group for group in match.groups()[1:] if group is not None) for match in LITERAL_ASSIGNMENT.finditer(text)}


def is_stdin_shell(arguments: list[str], /) -> bool:

    index = 0
    while index < len(arguments) and arguments[index].startswith(("-", "+")) and arguments[index] not in ("-", "--"):
        if is_cluster(arguments[index]) and "s" in arguments[index][1:]:
            return True
        index += 2 if arguments[index] in SHELL_VALUE_OPTIONS else 1
    index += 1 if arguments[index : index + 1] == ["--"] else 0

    return index >= len(arguments) or arguments[index] == "-"


def get_enclosed(text: str, start: int, /) -> str:

    depth = 1
    index = start
    while index < len(text) and depth:
        depth += {"(": 1, ")": -1}.get(text[index], 0)
        index += 1

    return text[start : index - 1 if depth == 0 else index]


def get_python_calls(code: str, /) -> list[str]:

    return [get_enclosed(code, match.end()) for match in PYTHON_RUNNERS.finditer(code)]


def get_substitutions(text: str, /) -> list[str]:

    substitutions: list[str] = []
    for match in SUBSTITUTION_START.finditer(text):
        is_backtick = match.group(0) == "`"
        end = text.find("`", match.end()) if is_backtick else -1
        substitutions.append(text[match.end() : end if end >= 0 else len(text)] if is_backtick else get_enclosed(text, match.end()))

    return substitutions


def get_stdin_scripts(text: str, /) -> list[str]:

    bodies = [match.group(2) for match in SHELL_HEREDOC.finditer(text)]
    strings = [next(group for group in match.groups() if group is not None) for match in SHELL_HERESTRING.finditer(text)]

    return bodies + strings


def get_python_code(words: list[str], /) -> str:

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

    findings = Findings([], [], [], [], [], [], [], [])
    find_breaches(get_segments(script), None, False, policy, findings, script)

    return next(iter(findings.denied + findings.hidden), "") or next(
        (label for segment in get_segments(script) if (label := get_owner_label(resolve(segment), None, policy))), ""
    )


def is_failing_glob(text: str, directory: str | None, may_have_written: bool, /) -> bool:

    if may_have_written or any(character in text for character in UNEXPANDED) or (directory is None and not is_absolute(text)):
        return False

    return next(glob.iglob(resolve_path(text, directory or ""), recursive=True), None) is None


def get_pattern_globs(command: Command, /) -> list[str]:

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

    if text.startswith("-") and "=" in text:
        option, _, value = text.partition("=")
        return f"{option}='{value}'"

    return f"'{text}'"


def get_glob_fix(command: str, words: list[str], cwd: str | None, policy: Policy, /) -> str:

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




def resolve_path(path: str, cwd: str, /) -> str:

    return os.path.realpath(os.path.join(cwd, os.path.expanduser(path)))


def is_absolute(word: str, /) -> bool:

    return word.startswith(("/", "~"))


def expand_path(path: str, cwd: str, /) -> list[str]:

    absolute = resolve_path(path, cwd)
    matches = glob.glob(absolute) if any(character in absolute for character in GLOB_CHARACTERS) else []

    return matches or [absolute]


def is_under(path: str, folder: str, /) -> bool:

    return path == folder or path.startswith(folder + os.sep)


def is_temporary(path: str, policy: Policy, /) -> bool:
    return policy.no_tmp and is_under(path, os.path.realpath(TEMPORARY))


def is_repo_write(path: str, policy: Policy, /) -> bool:

    return bool(policy.scratch) and is_under(path, policy.root) and not is_under(path, policy.scratch)


def get_positional(arguments: list[str], /) -> list[str]:

    return [argument for argument in arguments if not argument.startswith("-")]


def get_option_values(arguments: list[str], letter: str, long_name: str, /) -> list[str]:

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

    return any(argument == long_name or (is_cluster(argument) and letter in argument) for argument in arguments)


def has_in_place(arguments: list[str], /) -> bool:

    return any(argument.startswith("--in-place") or (is_cluster(argument) and "i" in argument) for argument in arguments)


def get_in_place_files(arguments: list[str], cwd: str | None, /) -> list[str]:

    positional = get_positional(arguments)
    if cwd is None:
        return positional

    return [argument for argument in positional if any(os.path.exists(path) for path in expand_path(argument, cwd))]


def get_destination(name: str, arguments: list[str], /) -> list[str]:

    targets = get_option_values(arguments, "t", "--target-directory") if name in TARGET_MOVERS else []
    if targets:
        return targets
    positional = get_positional(arguments)

    return positional[-1:] if len(positional) >= 2 else []


def get_moved_sources(name: str, arguments: list[str], /) -> list[str]:

    if name != "mv":
        return []
    destination = get_destination(name, arguments)
    sources = [argument for argument in get_positional(arguments) if argument not in destination]

    return sources


def get_curl_outputs(arguments: list[str], /) -> list[str]:

    outputs = get_option_values(arguments, "o", "--output")
    if has_option(arguments, "O", "--remote-name"):
        outputs.append(".")

    return outputs


def get_wget_outputs(arguments: list[str], /) -> list[str]:

    outputs = get_option_values(arguments, "O", "--output-document")
    if outputs:
        return outputs

    return get_option_values(arguments, "P", "--directory-prefix") or ["."]


def get_tar_outputs(arguments: list[str], /) -> list[str]:

    letters = "".join(argument[1:] for argument in arguments if is_cluster(argument))
    letters += "".join(TAR_LONG_MODES.get(argument, "") for argument in arguments)
    if arguments and not arguments[0].startswith("-"):
        letters += arguments[0]
    if "x" in letters:
        return get_option_values(arguments, "C", "--directory") or ["."]
    if any(mode in letters for mode in "cru"):
        return get_option_values(arguments, "f", "--file")

    return []


def get_named_paths(name: str, arguments: list[str], cwd: str | None, /) -> list[str]:

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

    arguments = [word.text for word in command.arguments]
    named = get_named_paths(os.path.basename(command.name), arguments, cwd)

    return segment.redirects + named


def get_written_paths(words: list[str], cwd: str | None, /) -> list[str]:

    return [path for word in words if cwd is not None or is_absolute(word) for path in expand_path(word, cwd or "")]




def get_cd_target(command: Command, directory: str | None, /) -> str | None:

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

    if command.name in IN_SHELL_RUNNERS:
        return None
    if command.name in DIRECTORY_CHANGERS:
        return None if is_grouped else get_cd_target(command, directory)

    return directory




class Scope(NamedTuple):

    text: str
    values: dict[str, str]


class TrashDelete(NamedTuple):

    words: list[str]
    name: str
    letters: str
    paths: list[str]


def expand_variables(text: str, values: Mapping[str, str], /) -> str:

    return VARIABLE.sub(lambda match: values.get(match.group(1), match.group(0)), text)


def is_literal(word: Word, text: str, /) -> bool:

    return bool(text) and not word.is_glob and "$" not in text and "`" not in text


def get_words_pattern(words: list[str], /) -> str:

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

    return len(re.findall(get_words_pattern(words), text)) == 1


def is_throwaway(path: str, policy: Policy, /) -> bool:

    is_scratch = bool(policy.scratch) and path.startswith(policy.scratch + os.sep)

    return is_scratch or bool(SCRATCHPAD.match(path))


def is_scratch_delete(segment: Segment, command: Command, directory: str | None, scope: Scope | None, policy: Policy, /) -> bool:

    if directory is None or os.path.basename(command.name) not in SCRATCH_DELETERS:
        return False
    values = scope.values if scope is not None else {}
    paths = [word for word in command.arguments if not word.text.startswith("-")]
    texts = [expand_variables(word.text, values) for word in paths]
    is_found = texts == [word.text for word in paths] or (scope is not None and is_written_once([word.text for word in segment.words], scope.text))
    inside = [is_literal(word, text) and is_throwaway(resolve_path(text, directory), policy) for word, text in zip(paths, texts)]

    return bool(paths) and is_found and all(inside)


def learn_values(segment: Segment, scope: Scope, /) -> None:

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

    path = os.path.join(directory, os.path.expanduser(text))
    trimmed = path.rstrip("/")
    folder, last = os.path.split(trimmed)
    if last in ("", ".", "..") or (trimmed != path and os.path.islink(trimmed)):
        return ""

    return os.path.join(os.path.realpath(folder), last)


def is_trashable(path: str, policy: Policy, /) -> bool:

    if not policy.trash or not path or not is_under(path, policy.root):
        return False
    parts = set(os.path.relpath(path, policy.root).split(os.sep))

    return not parts & OWNER_FOLDERS and not is_under(path, policy.trash) and not is_under(policy.trash, path)


def has_overlap(paths: list[str], /) -> bool:

    return any(is_under(first, second) or is_under(second, first) for first, second in itertools.combinations(paths, 2))


def get_trash_delete(segment: Segment, directory: str | None, scope: Scope | None, policy: Policy, /) -> TrashDelete | None:

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




class MissingGlob(NamedTuple):

    pattern: str
    folder: str


class Findings(NamedTuple):

    missing_globs: list[MissingGlob]
    pattern_globs: list[str]
    trash_deletes: list[TrashDelete]
    denied: list[str]
    hidden: list[str]
    cloud: list[str]
    installer: list[str]
    delayed: list[DelayRun]


def find_breaches(
    segments: list[Segment], cwd: str | None, judges_globs: bool, policy: Policy, findings: Findings, text: str, /, *, scope: Scope | None = None
) -> list[str]:

    breaches: list[str] = []
    installers = find_installers(segments) if policy.ask_installers else []
    findings.installer.extend(installers)
    breaches.extend([INSTALLER_RULE] if installers else [])
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

    is_zsh = os.path.basename(os.environ.get("SHELL") or "") == "zsh"
    collected = findings if findings is not None else Findings([], [], [], [], [], [], [], [])

    breaches = find_breaches(get_segments(command), cwd, is_zsh, policy, collected, command, scope=Scope(command, {}))

    return [rule for rule in breaches if rule != "sleep" or not is_background]


def get_command_breaches(
    segment: Segment, command: Command, directory: str | None, globs: tuple[bool, bool], scope: Scope | None, findings: Findings, policy: Policy, text: str, /
) -> list[str]:

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
    cloud = get_cloud_label(command) if policy.ask_cloud else ""
    findings.cloud.extend([cloud] if cloud else [])
    findings.denied.extend([denied] if denied else [])
    findings.hidden.extend([hidden] if hidden else [])
    is_asked = policy.ask_packages and is_package_change(command, policy.root)
    delay = get_delay_run(segment, command, policy) if is_asked and policy.tool_delay_days else None
    findings.delayed.extend([delay] if delay is not None and not delay.is_flagged else [])
    checks = [
        ("delete", is_deleting and trash is None),
        ("denied", bool(denied)),
        ("hidden", bool(hidden)),
        (ASK_RULE, is_asked and delay is None),
        ("delay", delay is not None and not delay.is_flagged),
        (CLOUD_RULE, bool(cloud)),
        ("glob", bool(missing)),
        ("pattern", bool(patterns)),
        ("trash", trash is not None),
        ("temporary", any(is_temporary(path, policy) for path in written)),
        ("repo", is_unknown_write or any(is_repo_write(path, policy) for path in [*written, *moved])),
        ("sleep", os.path.basename(command.name) == "sleep"),
    ]

    return [rule for rule, is_breach in checks if is_breach]


def is_direct_sleep(segment: Segment, /) -> bool:

    words = [word.text for word in segment.words]
    index = 0
    while index < len(words) and words[index] in LEADING_WORDS:
        index += 1

    return not segment.in_loop and not segment.in_group and words[index : index + 1] == ["sleep"]


def find_sleeps(segments: list[Segment], policy: Policy, /, *, is_top_level: bool = True) -> list[bool]:

    flags: list[bool] = []
    for segment in segments:
        command = resolve(segment, policy)
        if os.path.basename(command.name) == "sleep":
            flags.append(is_top_level and is_direct_sleep(segment))
        flags.extend(find_sleeps(get_inner_segments(command), policy, is_top_level=False))

    return flags


class SleepFix(NamedTuple):

    tool_input: dict
    note: str


def get_sleep_fix(command: str, tool_input: dict, policy: Policy, /) -> SleepFix:

    flags = find_sleeps(get_segments(command), policy)
    if flags and all(flags):
        return SleepFix({**tool_input, "command": SLEEP_SHADOW + command}, MESSAGES["sleep"])

    return SleepFix({**tool_input, "run_in_background": True}, SLEEP_BACKGROUND_NOTE)




class Rewrite(NamedTuple):

    tool_input: dict
    notes: list[str]
    refused: list[str]


def get_trash_folder(call_id: str, policy: Policy, /) -> str:

    name = re.sub(r"[^A-Za-z0-9_-]", "", call_id)

    return os.path.join(policy.trash, name) if name and policy.trash else ""


def get_trash_words(delete: TrashDelete, folder: str, policy: Policy, /) -> list[str]:

    pairs = [(path, os.path.join(folder, os.path.relpath(path, policy.root))) for path in delete.paths]

    return ["harness_trash", delete.name, delete.letters, *itertools.chain.from_iterable(pairs)]


def is_spliced_alone(command: str, spliced: str, replacements: Mapping[tuple[str, ...], list[str]], /) -> bool:

    expected = []
    for segment in get_segments(command):
        texts = [word.text for word in segment.words]
        start = next((index for index, text in enumerate(texts) if text not in LEADING_WORDS), len(texts))
        texts = texts[:start] + replacements.get(tuple(texts[start:]), texts[start:])
        expected.append((texts, segment.redirects, segment.in_loop, segment.in_group))
    found = [([word.text for word in segment.words], segment.redirects, segment.in_loop, segment.in_group) for segment in get_segments(spliced)]

    return found == expected


def get_trash_fix(command: str, deletes: list[TrashDelete], folder: str, policy: Policy, /) -> str:

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


def get_delay_fix(command: str, runs: list[DelayRun], /) -> str:

    spliced = command
    replacements: dict[tuple[str, ...], list[str]] = {}
    for run in runs:
        matches = list(re.finditer(get_words_pattern(run.lead), spliced))
        if len(matches) != 1:
            return ""
        spliced = spliced[: matches[0].end()] + " " + shlex.join([run.flag]) + spliced[matches[0].end() :]
        position = next(index for index in range(len(run.words)) if run.words[index : index + len(run.lead)] == run.lead) + len(run.lead)
        replacements[tuple(run.words)] = [*run.words[:position], run.flag, *run.words[position:]]

    return spliced if is_spliced_alone(command, spliced, replacements) else ""


def get_rewrite(breaches: list[str], tool_input: dict, findings: Findings, cwd: str, call_id: str, policy: Policy, /) -> Rewrite:

    original = tool_input.get("command") or ""
    command = original
    notes = [f"The harness guard let this run: {MESSAGES[rule]}" for rule in breaches if rule in NOTED_RULES]
    if "pattern" in breaches:
        command = get_glob_fix(command, findings.pattern_globs, cwd, policy)
        if not command:
            return Rewrite(tool_input, [], ["pattern"])
        notes.append(f"The harness guard changed this call: {MESSAGES['pattern']}")
    if "delay" in breaches:
        command = get_delay_fix(command, findings.delayed)
        if not command:
            return Rewrite(tool_input, [], [ASK_RULE])
        notes.append(f"The harness guard changed this call: {MESSAGES['delay'].format(days=policy.tool_delay_days)}")
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


def make_soft_output(rewrite: Rewrite, tool_input: dict, /) -> dict:

    output: dict = {"hookEventName": "PreToolUse"}
    if rewrite.tool_input != tool_input:
        output["updatedInput"] = rewrite.tool_input
    output["additionalContext"] = "\n".join(rewrite.notes)

    return {"hookSpecificOutput": output}


def refuse(rules: list[str], findings: Findings, /) -> int:

    missing = findings.missing_globs[0] if findings.missing_globs else MissingGlob("*", "this folder")
    glob_text = MESSAGES["glob"].format(folder=missing.folder, pattern=missing.pattern)
    denied = MESSAGES["denied"].format(what=(findings.denied or ["this git command"])[0])
    hidden = MESSAGES["hidden"].format(what=(findings.hidden or ["this command"])[0])
    cloud = MESSAGES[CLOUD_RULE].format(what=(findings.cloud or ["this command"])[0])
    installer = MESSAGES[INSTALLER_RULE].format(what=(findings.installer or ["this command"])[0])
    texts = {**MESSAGES, "glob": glob_text, "pattern": PATTERN_REFUSAL, "trash": MESSAGES["delete"], "denied": denied, "hidden": hidden, CLOUD_RULE: cloud, INSTALLER_RULE: installer}
    lines = list(dict.fromkeys(f"Blocked by the harness guard: {texts[rule]}" for rule in rules if rule not in ASK_RULES))
    if not lines:
        reason = " ".join(f"The harness guard: {texts[rule]}" for rule in ASK_RULES if rule in rules)
        decision = {"hookEventName": "PreToolUse", "permissionDecision": "ask", "permissionDecisionReason": reason}
        print(json.dumps({"hookSpecificOutput": decision}))
        return 0
    print("\n".join(lines), file=sys.stderr)

    return 2


def main() -> int:
    event = json.load(sys.stdin)
    tool_input = event.get("tool_input") or {}
    cwd = event.get("cwd") or os.getcwd()
    policy = get_policy(cwd)
    findings = Findings([], [], [], [], [], [], [], [])
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
    hard += [rule for rule in breaches if rule == "trash"]

    return refuse(hard, findings)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"the harness guard failed and let the call run: {error!r}", file=sys.stderr)
        sys.exit(1)
