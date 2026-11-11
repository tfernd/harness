#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///

from __future__ import annotations

import glob
import json
import os
import re
import shlex
import sys
from collections.abc import Callable, Mapping, Set
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

from common import (
    ASSIGNMENT,
    JOINING_RUNNERS,
    REMOTE_RUNNERS,
    SHELL_VALUE_OPTIONS,
    SHELLS,
    Command,
    find_project,
    get_git_index,
    get_git_subcommand,
    get_inner_segments,
    get_scratch,
    get_shell_string,
    is_cluster,
    resolve,
    skip_options,
)
from shell import GLOB_CHARACTERS, LEADING_WORDS, Segment, Word, get_segments

DELETERS = frozenset({"rm", "rmdir", "unlink", "shred", "truncate"})
CLEAN_TARGETS = frozenset({"clean", "distclean"})
MAKERS = frozenset({"make", "gmake"})
INFORMATION_OPTIONS = ("--help", "--version")
DRY_RUN_OPTIONS = ("--dry-run", "--just-print", "--recon")
DRY_RUN_LETTER = "n"
DRY_RUN_VALUE_LETTERS = {"git": "e", "make": "CfIjloW"}
MAX_SUBSTITUTIONS = 8
MAX_ENCLOSED_CHARACTERS = 1000
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
BARE_WORD = re.compile(r"[\w./@%+,:=~$-]+")

PIPEFAIL_RULE = "pipefail"
PIPEFAIL_PREFIX = "set -o pipefail; "
PIPEFAIL_WORD = "pipefail"
PIPEFAIL_CHECKS = {
    "pytest": frozenset(),
    "make": frozenset(),
    "tsc": frozenset(),
    "ruff": frozenset(),
    "mypy": frozenset(),
    "pyright": frozenset(),
    "npm": frozenset({"test", "run"}),
    "pnpm": frozenset({"test", "run"}),
    "yarn": frozenset({"test", "run"}),
    "cargo": frozenset({"test", "build", "check"}),
    "go": frozenset({"test", "build", "vet"}),
    "terraform": frozenset({"validate", "plan"}),
    "dbt": frozenset({"build", "test", "run"}),
    "gradle": frozenset({"test"}),
    "mvn": frozenset({"test"}),
}
PIPEFAIL_PYTHON_NAMES = frozenset({"python", "python3"})
PIPEFAIL_TEST_FOLDER = "tests/"
PIPEFAIL_KEPT_OPTION = "-m"
EARLY_GREP_OPTION = r"(?![^;&|\n]*?\s(?:-[A-Za-z]*[qlLm]|--quiet|--silent|--max-count|--files-with-matches|--files-without-match))"
PIPEFAIL_READERS = rf"tail|grep{EARLY_GREP_OPTION}"
PIPE_INTO_READER = re.compile(
    rf"(?:[ \t]+(?:\d*>&\d+|&?\d*>>?[ \t]*[^\s;&|()<>]+))*[ \t]*\|&?[ \t]*(?:[A-Za-z_]\w*=\S*[ \t]+)*(?:\S*/)?(?:{PIPEFAIL_READERS})(?=$|[\s;&|)])"
)
KILL_VALUE_LETTERS = {"pkill": frozenset("uUgGPstF"), "killall": frozenset("suyo")}
KILL_INFORMATION = frozenset({"V", "h"})
KILL_INFORMATION_OPTIONS = frozenset({"--help", "--version"})
ASK_RULE = "packages"
CLOUD_RULE = "cloud"
INSTALLER_RULE = "installer"
ASK_RULES = (ASK_RULE, CLOUD_RULE, INSTALLER_RULE)
DBT_RULE = "dbt"
SNOW_RULE = "snow"
AGENT_RULE = "agent"
AGENT_DELETE_RULE = "agent_delete"
REMOTE_RULES = frozenset({"denied", "hidden", "delete", AGENT_DELETE_RULE, *ASK_RULES})
MESSAGES = {
    "delete": "Agents delete nothing. If this must go, give the owner the command in the chat and say why it is needed; the owner runs it. "
    "Throwaway files stay in `__scratch__/`, which is never cleaned: a fresh run takes a new folder.",
    AGENT_DELETE_RULE: "Sub-agents delete nothing. Leave the file; throwaway files stay in `__scratch__/`, and a fresh run takes a new folder.",
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
    DBT_RULE: "`{what}` runs dbt against a target that is not a dev one, and a shared warehouse is the owner's to change: run it "
    "with `--target dev`, or ask the owner for their word in this job. The owner gives it by listing the target under "
    "`guard.dbt_dev_targets`, or by setting `guard.block_dbt_targets` to false, in `~/.config/harness/config.json`. `dbt parse`, "
    "`compile`, `ls`, `debug`, `deps` and `docs generate` run on any target; see `harness:code-sql`.",
    SNOW_RULE: "`{what}`: a write to Snowflake, or any use of a production connection, is the owner's to run or approve. Do not "
    "rephrase it. Put the SQL in a file in `__scratch__/`, name the exact `snow` command and what it changes, and say so in your "
    "report. The owner runs it, or sets `guard.block_snow` to false in `~/.config/harness/config.json`. Reads (`select`, `show`, "
    "`describe`, `list`) on a non-production connection run freely; see `harness:snowflake-cli`.",
    INSTALLER_RULE: "`{what}` runs code that nobody has read, so the owner is asked first: download it to a file in `__scratch__/`, read it, "
    "then run that file, or have the owner approve the pipe.",
    AGENT_RULE: "`{what}` writes to a repository or its history, and a sub-agent never runs a git or gh command that writes. Do not "
    "rephrase it: describe the change in your handback and the main session commits it (`harness:git`). Read forms run "
    "freely: `git status`, `git diff`, `git log`, `git show`, `git branch --list`, `git stash list`, `git config --get <key>`, "
    "`gh pr view`, `gh pr list`, `gh api <path>` (a GET).",
    "glob": "this glob matches no file from {folder}, so zsh fails with 'no matches found'. cd to the right folder, or use "
    "`rg --files -g '{pattern}'` or `git ls-files`.",
    "pattern": "an unquoted glob in a pattern position (--include, -name, -g) was quoted so the tool gets the pattern, not zsh's "
    "expansion.",
    "temporary": "the guard lets this call pass, but a write under /tmp is not where throwaway files go. Throwaway files belong in the project's `__scratch__/` folder, never under /tmp.",
    "repo": "the guard lets this call pass, but project files change with the Write tool (new file) or Edit (change); a shell "
    "redirect, tee, sed -i, cp or mv belongs under `__scratch__/`.",
    "search": "a search that starts at `/`, `~` or a whole system or home folder walks the entire disk and runs for minutes, mostly "
    "finding nothing. Ask for the thing directly: `command -v tsc` for a tool on PATH, `ls node_modules/.bin` for a project tool, "
    "`rg --files -g '<name>'` inside the project. If a wider look is needed, start at the project folder or add `-maxdepth 3`.",
    "pkill": "`pkill -f`, `pkill` without `-x` and `killall -r` match a pattern against every process, and a broad pattern kills "
    "unrelated ones (`pkill -f cat` matched \"Applications\" and closed every app). Find the process with `pgrep -x <name>` (or "
    "`pgrep -af <pattern>` to look), then `kill <pid>`. `kill <pid>` and `pkill -x <name>` run.",
    PIPEFAIL_RULE: "this command pipes a test, check or build into `tail` or `grep`, where the exit code is the last command's and a "
    "failed run looks like a pass, so `set -o pipefail; ` was put in front and the call ran. Write it yourself to skip this note.",
}
PATTERN_REFUSAL = (
    "this unquoted glob is a pattern for the command, which zsh would expand first, and the guard could not quote it safely. "
    "Quote it (`--include='*.py'`), or use `rg -g '*.py'`."
)
HOME_WORDS = frozenset({"~", "$HOME", "${HOME}"})
HOME_PARENTS = frozenset({"home", "Users"})
WIDE_SEARCHERS = frozenset({"find", "fd", "rg"})
SEARCH_DEPTH_LIMIT = 3
FIND_EXPRESSION_STARTS = frozenset({"(", "!", ")", ","})
DEPTH_OPTIONS = {"find": frozenset({"-maxdepth"}), "fd": frozenset({"-d", "--max-depth"}), "rg": frozenset({"-d", "--max-depth", "--maxdepth"})}
FD_VALUE_OPTIONS = frozenset({"-d", "--max-depth", "-e", "--extension", "-E", "--exclude", "-t", "--type", "-c", "--color", "-j", "--threads", "-S", "--size", "--search-path"})
RG_VALUE_OPTIONS = frozenset({"-g", "--glob", "--iglob", "-e", "--regexp", "-f", "--file", "-t", "--type", "-T", "--type-not", "-m", "--max-count", "-A", "-B", "-C", "-d", "--max-depth", "--maxdepth", "-j", "--threads", "-M", "-r", "--replace", "--sort", "--sortr"})
SOFT_RULES = ("pattern", "temporary", "repo", "delay", PIPEFAIL_RULE)
NOTED_RULES = ("temporary", "repo")


class Policy(NamedTuple):

    root: str = ""
    scratch: str = ""
    no_tmp: bool = False
    ask_packages: bool = False
    ask_cloud: bool = False
    ask_installers: bool = False
    tool_delay_days: int = 0
    block_dbt: bool = False
    dbt_dev_targets: tuple[str, ...] = ()
    block_snow: bool = False
    is_agent: bool = False


def get_delay_days(value: object, /) -> int:

    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def get_names(value: object, /) -> tuple[str, ...]:

    return tuple(name.lower() for name in value if isinstance(name, str)) if isinstance(value, list) else ()


def get_policy(cwd: str, /) -> Policy:

    root, config = find_project(cwd)
    guard = config.get("guard", {})

    return Policy(
        root=str(root),
        scratch=get_scratch(root, config),
        no_tmp=bool(guard.get("no_tmp")),
        ask_packages=bool(guard.get("ask_packages") or guard.get("deny_packages")),
        ask_cloud=bool(guard.get("ask_cloud")),
        ask_installers=bool(guard.get("ask_installers")),
        tool_delay_days=get_delay_days(guard.get("tool_delay_days")),
        block_dbt=guard.get("block_dbt_targets") is not False,
        dbt_dev_targets=get_names(guard.get("dbt_dev_targets")),
        block_snow=guard.get("block_snow") is not False,
    )


def get_cluster_letters(argument: str, value_letters: str, /) -> str:

    letters = ""
    for letter in argument[1:]:
        letters += letter
        if letter in value_letters:
            break

    return letters


def has_long_option(arguments: list[str], options: tuple[str, ...], /) -> bool:

    return any(argument.startswith("--") and any(is_long_prefix(argument, option) for option in options) for argument in arguments)


def has_dry_run(name: str, arguments: list[str], /) -> bool:

    value_letters = DRY_RUN_VALUE_LETTERS.get(name, "")
    operands = arguments[: arguments.index("--")] if "--" in arguments else arguments
    clusters = [get_cluster_letters(argument, value_letters) for argument in operands if is_cluster(argument)]

    return has_long_option(operands, DRY_RUN_OPTIONS) or any(DRY_RUN_LETTER in letters for letters in clusters)


def is_delete(command: Command, /) -> bool:
    arguments = [word.text for word in command.arguments]
    name = os.path.basename(command.name)
    if name == "busybox" and arguments:
        return is_delete(Command(arguments[0], command.arguments[1:]))
    if name in DELETERS:
        return not has_long_option(arguments, INFORMATION_OPTIONS)
    if name == "find":
        return "-delete" in arguments
    if name in MAKERS:
        return bool(CLEAN_TARGETS & set(arguments)) and not has_dry_run("make", arguments)

    return name == "git" and get_git_subcommand(arguments) == "clean" and not has_dry_run("git", arguments[get_git_index(arguments) + 1 :])



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



DBT_TOOL = "dbt"
DBT_WRITES = frozenset({"build", "run", "test", "seed", "snapshot", "run-operation", "retry", "clone"})
DBT_VALUE_OPTIONS = frozenset({
    "--profiles-dir", "--project-dir", "--log-path", "--log-level", "--log-level-file", "--log-format", "--log-format-file",
    "--target-path", "--profile", "--target", "-t",
})
DBT_DEV_TARGETS = frozenset({"dev", "local", "sandbox"})
DBT_DEV_PREFIXES = ("dev_", "dev-")
DBT_TARGET_VARIABLE = "DBT_TARGET"
SNOW_TOOL = "snow"
SNOW_VALUE_OPTIONS = frozenset({
    "-c", "--connection", "--environment", "--role", "--warehouse", "--database", "--schema", "--format", "--config-file", "-q",
    "--query", "-f", "--filename", "-D", "--variable", "--account", "--user", "--host", "--authenticator", "--private-key-file",
})
SNOW_CONNECTION_VARIABLE = "SNOWFLAKE_DEFAULT_CONNECTION_NAME"
SNOW_VERBS = frozenset({"deploy", "drop", "execute"})
SNOW_WRITE_COMMANDS = frozenset({("object", "create"), ("stage", "remove")})
SNOW_PRODUCTION_WORD = "prod"
SNOW_PATH_LENGTH = 3
SQL_WRITES = frozenset({
    "CREATE", "ALTER", "DROP", "TRUNCATE", "DELETE", "UPDATE", "INSERT", "MERGE", "GRANT", "REVOKE", "CALL", "EXECUTE", "PUT", "REMOVE",
    "COPY", "UNDROP",
})
SQL_NOISE = re.compile(r"--[^\n]*|//[^\n]*|/\*.*?\*/|\$\$.*?\$\$|'(?:[^'\\]|\\.|'')*'|\"(?:[^\"]|\"\")*\"", re.S)
SQL_WORD = re.compile(r"[A-Za-z_]+")
SQL_READ_LIMIT = 1_000_000


def get_tool_arguments(command: Command, tool: str, /) -> list[str] | None:

    name = os.path.basename(command.name)
    arguments = [word.text for word in command.arguments]
    if name == tool:
        return arguments
    if name in CLOUD_WRAPPERS:
        wrapped = next((index for index, argument in enumerate(arguments) if os.path.basename(argument) == tool), -1)
        return arguments[wrapped + 1 :] if wrapped >= 0 else None
    module = arguments.index("-m") + 1 if name.startswith("python") and "-m" in arguments else 0
    if module and module < len(arguments) and arguments[module].split(".")[0] == tool:
        return arguments[module + 1 :]

    return None


def get_assigned_environment(segment: Segment, name: str, /) -> list[str]:

    prefix = f"{name}="

    return [word.text[len(prefix) :] for word in segment.words if word.text.startswith(prefix)]


def is_unexpanded(value: str, /) -> bool:

    return any(character in value for character in UNEXPANDED)


def is_dev_target(target: str, policy: Policy, /) -> bool:

    lowered = target.lower()

    return lowered in DBT_DEV_TARGETS or lowered.startswith(DBT_DEV_PREFIXES) or lowered in policy.dbt_dev_targets


def get_dbt_label(segment: Segment, command: Command, policy: Policy, /) -> str:

    arguments = get_tool_arguments(command, DBT_TOOL)
    if arguments is None:
        return ""

    positionals = get_positionals(arguments, DBT_VALUE_OPTIONS)
    targets = [*get_option_values(arguments, "t", "--target"), *get_assigned_environment(segment, DBT_TARGET_VARIABLE)]
    outside = [target for target in targets if target and not is_unexpanded(target) and not is_dev_target(target, policy)]
    if not positionals or positionals[0] not in DBT_WRITES or not outside:
        return ""

    return f"dbt {positionals[0]} --target {outside[0]}"


def read_sql_file(filename: str, directory: str | None, /) -> str:

    if is_unexpanded(filename) or (directory is None and not is_absolute(filename)):
        return ""
    try:
        with open(resolve_path(filename, directory or ""), errors="replace") as file:
            return file.read(SQL_READ_LIMIT)
    except OSError:
        return ""


def get_statement_keyword(statement: str, /) -> str:

    words = [word.upper() for word in SQL_WORD.findall(statement)[:3]]
    if words[:1] == ["BEGIN"]:
        words = words[1:]
    if words[:2] == ["ALTER", "SESSION"] or not words:
        return ""

    return words[0] if words[0] in SQL_WRITES else ""


def find_sql_write(text: str, /) -> str:

    bare = SQL_NOISE.sub(" ", text)
    keywords = (get_statement_keyword(statement) for statement in bare.split(";"))

    return next((keyword for keyword in keywords if keyword), "")


def get_snow_sql_write(arguments: list[str], directory: str | None, /) -> str:

    texts = get_option_values(arguments, "q", "--query")
    texts.extend(read_sql_file(filename, directory) for filename in get_option_values(arguments, "f", "--filename"))
    keywords = (find_sql_write(text) for text in texts)

    return next((keyword for keyword in keywords if keyword), "")


def get_snow_write(arguments: list[str], directory: str | None, /) -> str:

    path = get_positionals(arguments, SNOW_VALUE_OPTIONS)
    if path[:1] == ["sql"]:
        keyword = get_snow_sql_write(arguments, directory)
        return f"snow sql ({keyword})" if keyword else ""

    verbs = [index for index, word in enumerate(path[1:SNOW_PATH_LENGTH], 1) if word in SNOW_VERBS]
    is_command = tuple(path[:2]) in SNOW_WRITE_COMMANDS
    is_upload = path[:2] == ["stage", "copy"] and len(path) > 3 and path[3].startswith("@")
    end = verbs[0] + 1 if verbs else 2

    return f"snow {' '.join(path[:end])}" if verbs or is_command or is_upload else ""


def get_snow_label(segment: Segment, command: Command, directory: str | None, /) -> str:

    arguments = get_tool_arguments(command, SNOW_TOOL)
    if arguments is None:
        return ""

    write = get_snow_write(arguments, directory)
    connections = [
        *get_option_values(arguments, "c", "--connection"),
        *get_assigned_environment(segment, SNOW_CONNECTION_VARIABLE),
    ]
    production = next((name for name in connections if SNOW_PRODUCTION_WORD in name.lower()), "")

    return write or (f"snow with the production connection {production}" if production else "")


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


GIT_AGENT_READS = frozenset({
    "status", "diff", "log", "show", "blame", "ls-files", "ls-tree", "rev-parse", "rev-list", "describe", "grep", "cat-file", "show-ref",
    "for-each-ref", "merge-base", "name-rev", "shortlog", "check-ignore", "diff-tree", "diff-index", "diff-files", "ls-remote", "version", "help",
    "archive", "check-attr", "count-objects",
})
CONFIG_READS = frozenset({"--get", "--get-all", "--get-regexp", "--get-urlmatch", "--list", "-l"})
CONFIG_WRITES = frozenset({"--add", "--unset", "--unset-all", "--replace-all", "--edit", "-e", "--rename-section", "--remove-section"})
REMOTE_READS = frozenset({"get-url", "show"})
REMOTE_OPTIONS = frozenset({"-v", "--verbose"})
BRANCH_LISTERS = frozenset({"--list", "--contains", "--no-contains", "--merged", "--no-merged", "--points-at"})
BRANCH_READS = frozenset({
    *BRANCH_LISTERS, "--all", "--remotes", "--verbose", "--show-current", "--sort", "--format", "--column", "--no-column", "--color", "--no-color",
    "--abbrev", "--no-abbrev", "--ignore-case",
})
BRANCH_READ_LETTERS = frozenset("lavr")
TAG_WRITE_LETTERS = frozenset("dasufmFe")
TAG_WRITES = frozenset({"--delete", "--annotate", "--sign", "--local-user", "--force", "--message", "--file", "--edit"})
STASH_READS = frozenset({"list", "show"})
GH_VALUE_OPTIONS = frozenset({"-R", "--repo", "--hostname"})
GH_WRITES = {
    "pr": frozenset({"create", "edit", "merge", "close", "reopen", "comment", "review", "ready", "checkout", "update-branch", "revert", "lock", "unlock"}),
    "issue": frozenset({"create", "edit", "close", "comment", "reopen", "delete", "transfer", "pin", "unpin", "lock", "unlock", "develop"}),
    "release": frozenset({"create", "edit", "delete", "upload", "delete-asset"}),
    "repo": frozenset({"create", "delete", "fork", "edit", "rename", "archive", "unarchive", "sync"}),
    "workflow": frozenset({"run", "enable", "disable"}),
    "run": frozenset({"rerun", "cancel", "delete"}),
    "label": frozenset({"create", "edit", "delete", "clone"}),
    "secret": frozenset({"set", "delete", "remove"}),
    "variable": frozenset({"set", "delete"}),
    "gist": frozenset({"create", "edit", "delete", "rename"}),
    "cache": frozenset({"delete"}),
    "auth": frozenset({"login", "logout", "refresh"}),
}
GH_API_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
GH_API_BODY_OPTIONS = frozenset({"--field", "--raw-field", "--input"})


def split_options(words: list[str], /) -> tuple[list[str], list[str]]:

    options = [word for word in words if word.startswith("-") and word != "-"]
    operands = [word for word in words if not word.startswith("-") or word == "-"]

    return options, operands


def is_config_read(rest: list[str], /) -> bool:

    names = {word.partition("=")[0] for word in split_options(rest)[0]}

    return bool(names & CONFIG_READS) and not names & CONFIG_WRITES


def is_remote_read(rest: list[str], /) -> bool:

    options, operands = split_options(rest)

    return set(options) <= REMOTE_OPTIONS and (not operands or operands[0] in REMOTE_READS)


def is_branch_read(rest: list[str], /) -> bool:

    options, operands = split_options(rest)
    for option in options:
        if option.startswith("--"):
            if option.partition("=")[0] not in BRANCH_READS:
                return False
        elif not set(option[1:]) <= BRANCH_READ_LETTERS:
            return False
    is_listing = any(option.partition("=")[0] in BRANCH_LISTERS or (not option.startswith("--") and "l" in option) for option in options)

    return not operands or is_listing


def is_tag_read(rest: list[str], /) -> bool:

    options, operands = split_options(rest)
    is_listing = any(option.partition("=")[0] == "--list" or (not option.startswith("--") and "l" in option) for option in options)
    if not is_listing:
        return not options and not operands
    for option in options:
        if option.startswith("--") and option.partition("=")[0] in TAG_WRITES:
            return False
        if not option.startswith("--") and TAG_WRITE_LETTERS & set(option[1:]):
            return False

    return True


def is_stash_read(rest: list[str], /) -> bool:

    operands = split_options(rest)[1]

    return bool(operands) and operands[0] in STASH_READS


def is_apply_check(rest: list[str], /) -> bool:

    return "--check" in split_options(rest)[0]


def is_worktree_read(rest: list[str], /) -> bool:

    return split_options(rest)[1][:1] == ["list"]


GIT_AGENT_CHECKS: dict[str, Callable[[list[str]], bool]] = {
    "config": is_config_read,
    "remote": is_remote_read,
    "branch": is_branch_read,
    "tag": is_tag_read,
    "stash": is_stash_read,
    "worktree": is_worktree_read,
    "apply": is_apply_check,
}


def get_agent_git_label(arguments: list[str], /) -> str:

    index = get_git_index(arguments)
    if index >= len(arguments):
        return ""
    subcommand = arguments[index]
    rest = arguments[index + 1 :]
    check = GIT_AGENT_CHECKS.get(subcommand)
    is_read = check(rest) if check else subcommand in GIT_AGENT_READS

    return "" if is_read and not any(word.startswith("--output") for word in rest) else f"git {subcommand}"


def get_gh_api_method(rest: list[str], /) -> str:

    method = ""
    for index, word in enumerate(rest):
        if word in ("-X", "--method"):
            method = rest[index + 1] if index + 1 < len(rest) else ""
        elif word.startswith("--method="):
            method = word.partition("=")[2]
        elif word.startswith("-X"):
            method = word[2:]

    return method.upper()


def has_gh_api_body(rest: list[str], /) -> bool:

    return any(
        word.partition("=")[0] in GH_API_BODY_OPTIONS or (word.startswith(("-f", "-F")) and not word.startswith("--"))
        for word in rest
    )


def get_agent_gh_label(arguments: list[str], /) -> str:

    positionals = get_positionals(arguments, GH_VALUE_OPTIONS)
    group = positionals[0] if positionals else ""
    action = positionals[1] if len(positionals) > 1 else ""
    if group == "api":
        method = get_gh_api_method(arguments)
        is_write = method in GH_API_WRITE_METHODS if method else has_gh_api_body(arguments)
        return "gh api (not a GET)" if is_write else ""

    return f"gh {group} {action}" if action in GH_WRITES.get(group, frozenset()) else ""


def get_agent_label(command: Command, /) -> str:

    name = os.path.basename(command.name)
    arguments = [word.text for word in command.arguments]
    if name == "git":
        return get_agent_git_label(arguments)

    return get_agent_gh_label(arguments) if name == "gh" else ""



LOOSE_WORD = re.compile(r"[^\s;&|(){}<>'\"`,\[\]]+")
LOOSE_SEPARATOR = re.compile(r"&&|\|\||[;\n|&]")
LOOSE_NAMES = frozenset({"git", "pip", "pip3", "uv", *TOOL_RUNNERS, *PACKAGE_CHANGES})
LITERAL_ASSIGNMENT = re.compile(r"(?:^|(?<=[\s;&|(]))([A-Za-z_][A-Za-z0-9_]*)=(?:'([^']*)'|\"([^\"$`\\]*)\"|([^\s;&|()<>'\"`$\\]*))")
SUBSTITUTION_START = re.compile(r"\$\((?!\()|`")
BRACED_PARAMETER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
PARAMETER = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
PYTHON_DELETES = re.compile(r"(?:\bos\.(?:remove|unlink|rmdir|removedirs)|\bshutil\.rmtree|\.unlink|\.rmdir|\brmtree)\s*\(")
PYTHON_HEREDOC = re.compile(r"\bpython[\d.]*\b[^\n]*?<<-?[ \t]*['\"]?(\w+)['\"]?[^\n]*\n(.*?)(?:\n[ \t]*\1[ \t]*(?:\n|$)|\Z)", re.S)
PYTHON_RUNNERS = re.compile(r"\b(?:os\.(?:system|popen|exec\w*|spawn\w*)|subprocess\.\w+|pty\.spawn)\s*\(")
SHELL_NAMES = "|".join(sorted(SHELLS))
SHELL_HEREDOC = re.compile(rf"\b(?:{SHELL_NAMES})\b[^\n]*?<<-?[ \t]*['\"]?(\w+)['\"]?[^\n]*\n(.*?)\n[ \t]*\1[ \t]*(?:\n|$)", re.S)
SHELL_HERESTRING = re.compile(rf"\b(?:{SHELL_NAMES})\b[^\n|;&]*?<<<[ \t]*(?:'([^']*)'|\"((?:[^\"\\]|\\.)*)\"|(\S+))")
STAND_IN_NAMES = ("git", "python", "uv", *(name for name in PACKAGE_CHANGES if name not in BARE_INSTALLERS))


def get_owner_label(command: Command, directory: str | None, policy: Policy, /) -> str:

    denied = get_denied(command, directory) or (get_agent_label(command) if policy.is_agent else "")
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
    stop = min(len(text), start + MAX_ENCLOSED_CHARACTERS)
    while index < stop and depth:
        depth += {"(": 1, ")": -1}.get(text[index], 0)
        index += 1

    return text[start : index - 1 if depth == 0 else index]


def get_python_calls(code: str, /) -> list[str]:

    return [get_enclosed(code, match.end()) for match in PYTHON_RUNNERS.finditer(code)]


def get_substitutions(text: str, /) -> list[str]:

    substitutions: list[str] = []
    for match in SUBSTITUTION_START.finditer(text):
        if len(substitutions) == MAX_SUBSTITUTIONS:
            break
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


def fill_parameters(text: str, values: dict[str, str], /) -> str:

    return PARAMETER.sub(lambda match: values.get(match.group(1), match.group(0)), text)


def get_name_heads(text: str, values: dict[str, str], /) -> list[str]:

    filled = fill_parameters(text, values)

    return get_substitutions(filled) or [values[name] for name in BRACED_PARAMETER.findall(text) if name in values]


def is_variable_delete(command: Command, text: str, /) -> bool:

    if "$" not in command.name and "`" not in command.name:
        return False
    values = get_assigned_values(text)
    words = fill_parameters(command.name, values).split()
    arguments = [Word(fill_parameters(word.text, values), word.is_glob) for word in command.arguments]
    if words and "$" not in words[0] and "`" not in words[0]:
        return is_delete(Command(words[0], [*(Word(word, False) for word in words[1:]), *arguments]))
    heads = get_name_heads(text, values)

    return any(os.path.basename(word) in DELETERS for head in heads for word in LOOSE_WORD.findall(head))


def is_python_delete(command: Command, text: str, /) -> bool:

    words = [command.name, *(word.text for word in command.arguments)]
    if not any(os.path.basename(word).startswith("python") for word in words):
        return False
    code = get_python_code(words)
    scripts = [code] if code else [match.group(2) for match in PYTHON_HEREDOC.finditer(text)]

    return any(PYTHON_DELETES.search(script) for script in scripts)


def get_variable_command(command: Command, text: str, policy: Policy, /) -> str:

    values = get_assigned_values(text)
    words = [fill_parameters(word, values) for word in (command.name, *(word.text for word in command.arguments))]
    if PARAMETER.search(words[0]):
        labels = (get_owner_label(Command(stand_in, command.arguments), None, policy) for stand_in in STAND_IN_NAMES)
        return next((label for label in labels if label), "")
    if "$" in words[0] or "`" in words[0]:
        tail = " ".join(words[1:])
        heads = get_name_heads(text, values)
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

    findings = Findings([], [], [], [], [], [], [], [], [], [])
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


def is_wide_path(word: str, /) -> bool:

    if word.rstrip("/") in HOME_WORDS:
        return True
    parts = [part for part in word.split("/") if part]

    return word.startswith("/") and (len(parts) <= 1 or (len(parts) == 2 and parts[0] in HOME_PARENTS))


def get_depth_limit(arguments: list[str], options: Set[str], /) -> int | None:

    for index, argument in enumerate(arguments):
        name, _, inline = argument.partition("=")
        value = inline or (arguments[index + 1] if index + 1 < len(arguments) else "")
        if name in options and value.isdigit():
            return int(value)

    return None


def get_search_paths(name: str, arguments: list[str], /) -> list[str]:

    if name == "find":
        start = next((index for index, argument in enumerate(arguments) if not argument.startswith("-")), len(arguments))
        end = next((index for index in range(start, len(arguments)) if arguments[index].startswith("-") or arguments[index] in FIND_EXPRESSION_STARTS), len(arguments))
        return arguments[start:end]
    positionals = get_positionals(arguments, FD_VALUE_OPTIONS if name == "fd" else RG_VALUE_OPTIONS)
    has_pattern_option = any(argument in ("-e", "--regexp", "-f", "--file", "--files") for argument in arguments)

    return positionals if name == "rg" and has_pattern_option else positionals[1:]


def is_wide_search(command: Command, /) -> bool:

    name = os.path.basename(command.name)
    arguments = [word.text for word in command.arguments]
    if name not in WIDE_SEARCHERS:
        return False
    depth = get_depth_limit(arguments, DEPTH_OPTIONS[name])

    return any(is_wide_path(path) for path in get_search_paths(name, arguments)) and (depth is None or depth > SEARCH_DEPTH_LIMIT)


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


class MissingGlob(NamedTuple):

    pattern: str
    folder: str


class Findings(NamedTuple):

    missing_globs: list[MissingGlob]
    pattern_globs: list[str]
    denied: list[str]
    hidden: list[str]
    cloud: list[str]
    installer: list[str]
    delayed: list[DelayRun]
    dbt: list[str]
    snow: list[str]
    agent: list[str]


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
        name = os.path.basename(command.name)
        inner_judges = judges_globs and not (name in SHELLS and name != "zsh") and name not in JOINING_RUNNERS
        is_remote = name in REMOTE_RUNNERS
        inner = find_breaches(get_inner_segments(command), None if is_remote else directory, inner_judges, policy, findings, text)
        breaches.extend(rule for rule in inner if not is_remote or rule in REMOTE_RULES)
        may_have_written = may_have_written or name not in READ_ONLY_COMMANDS or bool(get_written_words(segment, command, directory))
        directory = get_directory_after(command, segment.in_group, directory)

    return [rule for rule in MESSAGES if rule in breaches]


def find_command_breaches(command: str, cwd: str | None, policy: Policy, /, *, is_background: bool = False, findings: Findings | None = None) -> list[str]:

    is_zsh = os.path.basename(os.environ.get("SHELL") or "") == "zsh"
    collected = findings if findings is not None else Findings([], [], [], [], [], [], [], [], [], [])

    return find_breaches(get_segments(command), cwd, is_zsh, policy, collected, command, scope=Scope(command))


def get_command_breaches(
    segment: Segment, command: Command, directory: str | None, globs: tuple[bool, bool], scope: Scope | None, findings: Findings, policy: Policy, text: str, /
) -> list[str]:

    words = get_written_words(segment, command, directory)
    written = get_written_paths(words, directory)
    arguments = [word.text for word in command.arguments]
    moved = get_written_paths(get_moved_sources(os.path.basename(command.name), arguments), directory)
    is_unknown_write = bool(policy.scratch) and directory is None and not all(is_absolute(word) for word in words)
    is_deleting = is_delete(command) or is_variable_delete(command, text) or is_python_delete(command, text)
    missing = get_failing_globs(command, directory, globs[1]) if globs[0] else []
    patterns = get_pattern_globs(command) if globs[0] else []
    findings.missing_globs.extend(MissingGlob(text, directory or "an unknown folder") for text in missing)
    findings.pattern_globs.extend(patterns)
    denied = get_denied(command, directory)
    hidden = get_hidden_command(command, text, policy)
    cloud = get_cloud_label(command) if policy.ask_cloud else ""
    findings.cloud.extend([cloud] if cloud else [])
    dbt = get_dbt_label(segment, command, policy) if policy.block_dbt else ""
    snow = get_snow_label(segment, command, directory) if policy.block_snow else ""
    findings.dbt.extend([dbt] if dbt else [])
    findings.snow.extend([snow] if snow else [])
    agent = get_agent_label(command) if policy.is_agent else ""
    findings.agent.extend([agent] if agent else [])
    findings.denied.extend([denied] if denied else [])
    findings.hidden.extend([hidden] if hidden else [])
    is_asked = policy.ask_packages and is_package_change(command, policy.root)
    delay = get_delay_run(segment, command, policy) if is_asked and policy.tool_delay_days else None
    findings.delayed.extend([delay] if delay is not None and not delay.is_flagged else [])
    checks = [
        ("delete", is_deleting and not policy.is_agent),
        (AGENT_DELETE_RULE, is_deleting and policy.is_agent),
        ("denied", bool(denied)),
        (AGENT_RULE, bool(agent)),
        ("hidden", bool(hidden)),
        (ASK_RULE, is_asked and delay is None),
        ("delay", delay is not None and not delay.is_flagged),
        (CLOUD_RULE, bool(cloud)),
        (DBT_RULE, bool(dbt)),
        (SNOW_RULE, bool(snow)),
        ("glob", bool(missing)),
        ("pattern", bool(patterns)),
        ("temporary", any(is_temporary(path, policy) for path in written)),
        ("repo", is_unknown_write or any(is_repo_write(path, policy) for path in [*written, *moved])),
        ("search", is_wide_search(command)),
        ("pkill", is_broad_kill(command)),
        (PIPEFAIL_RULE, scope is not None and is_unguarded_check_pipe(segment, command, text)),
    ]

    return [rule for rule, is_breach in checks if is_breach]


def get_kill_options(name: str, arguments: list[str], /) -> tuple[set[str], set[str]]:

    letters: set[str] = set()
    long_options: set[str] = set()
    for argument in arguments:
        if argument.startswith("--"):
            long_options.add(argument.split("=")[0])
        elif is_cluster(argument):
            for letter in argument[1:]:
                letters.add(letter)
                if letter in KILL_VALUE_LETTERS[name]:
                    break

    return letters, long_options


def is_broad_kill(command: Command, /) -> bool:

    name = os.path.basename(command.name)
    if name not in KILL_VALUE_LETTERS:
        return False
    letters, long_options = get_kill_options(name, [word.text for word in command.arguments])
    if letters & KILL_INFORMATION or long_options & KILL_INFORMATION_OPTIONS:
        return False
    if name == "killall":
        return "r" in letters or "--regexp" in long_options

    return "f" in letters or "--full" in long_options or not ("x" in letters or "--exact" in long_options)


def is_check_words(name: str, words: list[str], /, *, via_uv: bool = False) -> bool:

    if name == "uv":
        return words[:1] == ["run"] and len(words) > 1 and is_check_words(os.path.basename(words[1]), words[2:], via_uv=True)
    if name in PIPEFAIL_PYTHON_NAMES:
        return words[:2] == [PIPEFAIL_KEPT_OPTION, "pytest"] or (via_uv and words[:1] != [] and words[0].startswith(PIPEFAIL_TEST_FOLDER))
    if name not in PIPEFAIL_CHECKS:
        return False
    subcommands = PIPEFAIL_CHECKS[name]

    return not subcommands or (bool(words) and words[0] in subcommands)


def is_unguarded_check_pipe(segment: Segment, command: Command, text: str, /) -> bool:

    if PIPEFAIL_WORD in text or "|" not in text:
        return False
    arguments = [word.text for word in command.arguments if not word.text.startswith("-") or word.text == PIPEFAIL_KEPT_OPTION]
    if not is_check_words(os.path.basename(command.name), arguments):
        return False
    pattern = get_words_pattern([word.text for word in segment.words])

    return any(PIPE_INTO_READER.match(text, match.end()) for match in re.finditer(pattern, text))


class Rewrite(NamedTuple):

    tool_input: dict
    notes: list[str]
    refused: list[str]


def is_spliced_alone(command: str, spliced: str, replacements: Mapping[tuple[str, ...], list[str]], /) -> bool:

    expected = []
    for segment in get_segments(command):
        texts = [word.text for word in segment.words]
        start = next((index for index, text in enumerate(texts) if text not in LEADING_WORDS), len(texts))
        texts = texts[:start] + replacements.get(tuple(texts[start:]), texts[start:])
        expected.append((texts, segment.redirects, segment.in_loop, segment.in_group))
    found = [([word.text for word in segment.words], segment.redirects, segment.in_loop, segment.in_group) for segment in get_segments(spliced)]

    return found == expected


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


def get_rewrite(breaches: list[str], tool_input: dict, findings: Findings, cwd: str, policy: Policy, /) -> Rewrite:

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
    changed = {**tool_input, "command": command} if command != original else dict(tool_input)
    if PIPEFAIL_RULE in breaches:
        changed = {**changed, "command": PIPEFAIL_PREFIX + changed["command"]}
        notes.append(f"The harness guard changed this call: {MESSAGES[PIPEFAIL_RULE]}")

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
    dbt = MESSAGES[DBT_RULE].format(what=(findings.dbt or ["this dbt command"])[0])
    snow = MESSAGES[SNOW_RULE].format(what=(findings.snow or ["this snow command"])[0])
    agent = MESSAGES[AGENT_RULE].format(what=(findings.agent or ["this command"])[0])
    texts = {**MESSAGES, "glob": glob_text, "pattern": PATTERN_REFUSAL, "denied": denied, "hidden": hidden, CLOUD_RULE: cloud, INSTALLER_RULE: installer, DBT_RULE: dbt, SNOW_RULE: snow, AGENT_RULE: agent}
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
    policy = get_policy(cwd)._replace(is_agent=bool(event.get("agent_id")))
    findings = Findings([], [], [], [], [], [], [], [], [], [])
    if event.get("tool_name") == "Bash":
        command = tool_input.get("command") or ""
        breaches = find_command_breaches(command, cwd, policy, findings=findings)
    else:
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        breaches = ["temporary"] if is_temporary(resolve_path(path, cwd), policy) else []
    hard = [rule for rule in breaches if rule not in SOFT_RULES]
    if not hard:
        rewrite = get_rewrite(breaches, tool_input, findings, cwd, policy)
        if not rewrite.refused:
            if breaches:
                print(json.dumps(make_soft_output(rewrite, tool_input)))
            return 0
        hard = rewrite.refused

    return refuse(hard, findings)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"the harness guard failed and let the call run: {error!r}", file=sys.stderr)
        sys.exit(1)
