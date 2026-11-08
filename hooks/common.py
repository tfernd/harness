# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""What the hooks share: the project and its config layers, the roles the plugin judges, the data folder, fences, and
the command a shell segment runs past its prefixes and wrappers."""

from __future__ import annotations

import fnmatch
import json
import os
import re
from collections.abc import Set
from pathlib import Path
from typing import NamedTuple

from shell import Segment, Word, get_segments

# The variable that points at the owner's config file; tests point it away.
USER_CONFIG_VARIABLE = "HARNESS_CONFIG"
# The plugin's default settings: every section is a rule that runs in every project; the owner's file only overrides.
DEFAULTS: dict = {  # keys are data
    "guard": {"scratch": "__scratch__", "no_tmp": True, "ask_packages": True},
    "brief": {},
    "progress": {"every": 10},
    "tests_kept": {"enabled": True},
    "main_edits": {"max": 3, "allow": ["__harness__/*", "__scratch__/*"]},
    "skill_gate": {
        "*.py": ["harness:code-python"],
        "*.js": ["harness:code-js"],
        "*.mjs": ["harness:code-js"],
        "*.cjs": ["harness:code-js"],
        "*.ts": ["harness:code-js"],
        "*.mts": ["harness:code-js"],
        "*.cts": ["harness:code-js"],
        "*.tsx": ["harness:code-js"],
        "*.jsx": ["harness:code-js"],
        "*.html": ["harness:code-html-css"],
        "*.css": ["harness:code-html-css"],
        "*.tf": ["harness:code-terraform"],
        "*.tfvars": ["harness:code-terraform"],
        "test_*.py": ["harness:testing"],
        "*.test.*": ["harness:testing"],
        "*.spec.*": ["harness:testing"],
        "*.sh": ["harness:code-shell"],
        "*.bash": ["harness:code-shell"],
        "tests/*.py": ["harness:testing", "harness:code-python"],
        ".github/workflows/*": ["harness:release"],
    },
    "stop": {"rule_paths": ["AGENTS.md", "CLAUDE.md", "skills", "agents", "hooks", "templates", ".claude"]},
}
PLUGIN_PREFIX = "harness:"
HANDBACK_TOOL = "SubagentHandback"
EDIT_TOOLS = frozenset({"Edit", "Write", "NotebookEdit"})
# The kind of a session's file that counts the main session's edits, written before each edit runs.
EDITS_KIND = "edits"
# The folder of the harness's own state in a project, ignored by git through its own `.gitignore`.
HARNESS_FOLDER = "__harness__"
# The folder of a project's throwaway files, ignored the same way.
SCRATCH_FOLDER = "__scratch__"
FEEDBACK_FOLDER = f"{HARNESS_FOLDER}/feedback"
# The folder the guard moves deleted paths into, one subfolder per call, for the owner to empty.
TRASH_FOLDER = f"{HARNESS_FOLDER}/trash"
# The feedback folder of the plugin versions that kept it at the project root, moved at session start.
OLD_FEEDBACK_FOLDER = "harness-feedback"
IGNORE_FILE = ".gitignore"
IGNORE_TEXT = "*\n"
HARNESS_README = """# __harness__

State of the harness plugin in this project. Git ignores this whole folder (its `.gitignore` holds `*`), and `rg` and Glob skip
ignored folders too, so read these files by path.

- `feedback/inbox.md`: one line per Feedback item of an agent's report. The report gate appends; a retro reads.
- `feedback/handled.md`: one line per item a retro closed, `<id>: rule written in <file>`. The main session writes; the Stop hook and the
  start-of-agent lessons read.
- `feedback/open.md`: problems a retro kept that no rule fixes yet, `- <role or all>: <problem>`. The main session writes; agents read at start.
- `feedback/retro-mark`: how many inbox items the last retro covered. The Stop hook keeps it.
- `trash/<call id>/`: what the guard moved here instead of deleting, each path under its place from the project root.
  Nothing reads it; the owner empties it.

Per-machine data (the ledger of reports, turn counters, send-backs, progress) lives in the plugin's data folder (`$CLAUDE_PLUGIN_DATA`,
else `~/.cache/harness`), not here.
"""
INBOX = f"{FEEDBACK_FOLDER}/inbox.md"
# The path of the handled file; `turn.py` imports it as HANDLED_NAME, since it names its own line pattern HANDLED.
HANDLED = f"{FEEDBACK_FOLDER}/handled.md"
# How many inbox items the last retro covered, which the Stop hook keeps.
RETRO_MARK = f"{FEEDBACK_FOLDER}/retro-mark"
# Lines `- <role or all>: <problem>` the main session keeps from a retro, told to agents at their start.
OPEN_PROBLEMS = f"{FEEDBACK_FOLDER}/open.md"
# The characters a file named in the handled file may carry around it, such as a closing period or backticks.
FILE_EDGES = "`'\".,;:()"
def read_sections(path: Path, /) -> dict:  # keys are data
    """The sections of a JSON config file, {} when it is missing. A broken file raises."""

    if not path.is_file():
        return {}
    config = json.loads(path.read_text())
    # A section of the wrong type counts as empty, so one bad key can't crash a hook and drop every rule.
    sections = config.items() if isinstance(config, dict) else ()

    return {key: value if isinstance(value, dict) else {} for key, value in sections}


def merge_sections(*layers: dict) -> dict:  # keys are data
    """The layers' sections, a later layer's keys over an earlier one's, key by key inside each section."""

    merged: dict = {}
    for layer in layers:
        for key, value in layer.items():
            merged[key] = {**merged.get(key, {}), **value}

    return merged


class Project(NamedTuple):
    """A project's folder and its merged config."""

    root: Path
    config: dict  # keys are data: the user's config sections


def find_git_root(start: Path, /) -> Path | None:
    """The nearest folder from `start` upward that holds a `.git` entry, None when there is none below the home folder."""

    for candidate in (start, *start.parents):
        # The home folder and its parents are no project, so a repository kept there does not swallow the folders under it.
        if not is_project_root(candidate):
            return None
        if (candidate / ".git").exists():
            return candidate

    return None


def get_project_entries(projects: object, root: Path, /) -> dict:  # keys are data
    """The sections of every `projects` entry of the owner's file whose path or glob matches the project root."""

    layers: list[dict] = []
    if isinstance(projects, dict):
        for pattern, entry in projects.items():
            if isinstance(entry, dict) and fnmatch.fnmatch(str(root), os.path.expanduser(str(pattern))):
                layers.append({key: value for key, value in entry.items() if isinstance(value, dict)})

    return merge_sections(*layers)


def find_project(cwd: str, /) -> Project:  # keys are data: the dict holds keys of the user's config, not names in code
    """The project folder and its config: the defaults, then the owner's file, then its `projects` entry for this folder.

    The project folder is the git work-tree root of `CLAUDE_PROJECT_DIR` (else `cwd`), found by walking up to a `.git`
    entry; with none it is the start folder itself, so a `cd` in a session does not change its project.
    The owner's file is `$HARNESS_CONFIG`, else `~/.config/harness/config.json`; its optional `projects` maps an absolute
    path or glob to sections that apply to a matching folder. No file inside a project is read. Every section of `DEFAULTS` is a
    default, so every rule runs in every project; a file only overrides (`delegate` stays off until it names it).
    A broken owner file counts as empty, so the hard rules stay on.
    """

    start = Path(os.environ.get("CLAUDE_PROJECT_DIR") or cwd).resolve()
    root = find_git_root(start) or start
    user_path = Path(os.environ.get(USER_CONFIG_VARIABLE) or Path.home() / ".config" / "harness" / "config.json")
    try:
        owner = read_sections(user_path)
    except (OSError, ValueError):
        owner = {}
    entries = get_project_entries(owner.pop("projects", {}), root)

    return Project(root, merge_sections(DEFAULTS, owner, entries))


def is_project_root(root: Path, /) -> bool:
    """Whether the folder may take project rules that write into it or walk it: not `/`, the home folder or a parent of it."""

    home = Path.home().resolve()

    return root != home and root not in home.parents


def ensure_ignored_folder(folder: Path, readme: str = "", /) -> None:
    """Creates `folder` with a `.gitignore` holding `*` (and `readme` when given) if they are missing; never raises.

    Called whenever a hook creates or writes into one of the harness's folders, so git never sees it.
    """

    try:
        folder.mkdir(parents=True, exist_ok=True)
        ignore = folder / IGNORE_FILE
        if not ignore.exists():
            ignore.write_text(IGNORE_TEXT)
        readme_path = folder / "README.md"
        if readme and not readme_path.exists():
            readme_path.write_text(readme)
    except OSError:
        pass


def ensure_harness_folder(base: Path, /) -> Path:
    """Creates `base/__harness__` as an ignored folder with its README; returns it."""

    folder = base / HARNESS_FOLDER
    ensure_ignored_folder(folder, HARNESS_README)

    return folder


def get_feedback_root(root: Path, /) -> Path:
    """The folder that holds `__harness__/`: the project itself, else one in the data folder
    when the start folder is no project root (`/` or the home folder), so no inbox lands there."""

    if is_project_root(root):
        return root

    return data_folder() / "projects" / (re.sub(r"[^A-Za-z0-9]+", "-", str(root)).strip("-") or "root")


def get_scratch(root: Path, config: dict, /) -> str:  # config keys
    """The resolved absolute folder of `guard.scratch` (`__scratch__/` and `./__scratch__` are `__scratch__`), empty when not set
    or when the root is no project root, where a scratch rule would cover the whole home folder."""

    scratch = config.get("guard", {}).get("scratch")
    if not is_project_root(root):
        return ""

    return os.path.realpath(root / scratch) if scratch else ""


def make_note_output(note: str, /) -> dict:  # keys are data
    """The PreToolUse output that lets the call run and gives the agent a note with the result.

    Never carries a `permissionDecision`: the owner's permission prompts still apply to the call.
    """

    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": note}}


def get_fenced_indices(lines: list[str], /) -> set[int]:
    """The indices of the lines inside a fenced block, fences included. A fence that never closes hides nothing."""

    fenced: set[int] = set()
    opened = -1
    for index, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            if opened < 0:
                opened = index
            else:
                fenced.update(range(opened, index + 1))
                opened = -1

    return fenced


def get_unfenced_lines(text: str, /) -> list[str]:
    """The lines of a message outside its fenced blocks, which hold examples. A fence that never closes hides nothing."""

    lines = text.splitlines()
    fenced = get_fenced_indices(lines)

    return [line for index, line in enumerate(lines) if index not in fenced]


def read_events(path: Path, /) -> list[dict]:  # keys are data
    """A transcript's lines that parse to an object; a torn line or any other JSON value is skipped."""

    events: list[dict] = []
    for line in path.read_bytes().decode(errors="replace").split("\n"):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)

    return events


def get_turns(events: list[dict], /) -> list[list[dict]]:  # keys are data
    """The tool calls of each model turn; a transcript line holds one block, and the lines of a turn share a message id."""

    turns: list[list[dict]] = []
    last_id = None
    for event in events:
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        calls = [block for block in content if isinstance(block, dict) and block.get("type") == "tool_use"] if isinstance(content, list) else []
        if event.get("type") != "assistant" or not calls:
            continue
        message_id = message.get("id")
        if message_id and message_id == last_id:
            turns[-1].extend(calls)
        else:
            turns.append(calls)
        last_id = message_id

    return turns


def read_tail(path: Path, size: int, /) -> bytes:
    """The last `size` bytes of a file, from its first whole line, so a long transcript is never read whole."""

    with open(path, "rb") as file:
        end = file.seek(0, os.SEEK_END)
        start = max(0, end - size)
        file.seek(start)
        data = file.read()

    return data.partition(b"\n")[2] if start else data


def data_folder() -> Path:
    """The plugin's data folder, which survives plugin updates, created if missing."""

    folder = Path(os.environ.get("CLAUDE_PLUGIN_DATA") or Path.home() / ".cache" / "harness")
    folder.mkdir(parents=True, exist_ok=True)

    return folder


def write_atomic(path: Path, text: str, /) -> None:
    """Write `text` to `path` so a reader sees the old file or the whole new one, never an empty or partial one.

    The text goes to a sibling file first and `os.replace` swaps it in. Appends stay plain appends: one short write
    in append mode lands whole on Linux.
    """

    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(text)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


# ===========================================================================
# Commands
# ===========================================================================

# The words after which the next word is the command, with no option of their own: wrappers (`command`, `exec`, `nohup`,
# `time`, `builtin`, `noglob`) and shell keywords or punctuation (`then`, `do`, `else`, `elif`, `if`, `while`, `until`, `!`, `{`, `}`).
PREFIXES = frozenset({
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
})
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
# The shells whose -c string is a command, and their options that take a value in the next word, before that string.
SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
SHELL_VALUE_OPTIONS = frozenset({"-o", "+o", "-O", "+O", "--rcfile", "--init-file"})
# The options of find that run the words after them, up to a `;` or a `+`.
FIND_RUNNERS = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
FIND_RUNNER_ENDS = frozenset({";", "+"})
# The options of git before its subcommand that take a value in the next word.
GIT_VALUE_OPTIONS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--attr-source"})
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")
# The commands that run the rest of their words, joined, as a shell command, each with its options that take a value in
# the next word: `watch`, `parallel` up to its `:::` arguments, and `ssh` after its host, on that host.
JOINING_RUNNERS = {
    "watch": frozenset({"-n", "--interval"}),
    "parallel": frozenset({"-j", "--jobs", "-P", "--max-procs", "-S", "--sshlogin", "-a", "--arg-file", "--delay", "--timeout", "-n", "-N", "--max-args", "--joblog", "--results", "--colsep", "-C", "-d", "--delimiter", "-E", "-I", "-L", "--workdir", "--wd", "--tmpdir", "--retries", "--halt", "-l", "--load", "-s", "--tagstring", "--env"}),
    "ssh": frozenset({"-b", "-B", "-c", "-D", "-E", "-e", "-F", "-I", "-i", "-J", "-L", "-l", "-m", "-O", "-o", "-p", "-Q", "-R", "-S", "-W", "-w"}),
}
# The runner whose command runs on another machine, where only the rules about git and packages apply.
REMOTE_RUNNERS = frozenset({"ssh"})
# The words of `parallel` that end its command and start its arguments.
PARALLEL_ARGUMENTS = frozenset({":::", "::::", ":::+", "::::+"})
# The commands that run the value of their `-c` (or `--command`) option as a shell command.
OPTION_RUNNERS = frozenset({"su", "script"})


class Command(NamedTuple):
    """A simple command resolved past its prefixes: the command word and its arguments."""

    name: str
    arguments: list[Word]


def skip_options(words: list[Word], index: int, value_options: Set[str], /) -> int:
    """The index of the first word from `index` that is not an option or an option's value."""

    while index < len(words) and words[index].text.startswith("-"):
        index += 2 if words[index].text in value_options else 1

    return index


def resolve(segment: Segment, policy: object = None, /) -> Command:
    """The command a segment runs, past assignments and prefixes; `policy` is not read, and kept for callers that pass one."""

    words = segment.words
    index = 0
    while index < len(words):
        word = words[index].text
        if ASSIGNMENT.match(word) or word in PREFIXES:
            index += 1
        elif word in OPTION_PREFIXES:
            index = skip_options(words, index + 1, OPTION_PREFIXES[word])
            if word == "timeout":
                index += 1  # skip its duration, the first non-option word
        else:
            break
    if index >= len(words):
        return Command("", [])

    return Command(words[index].text, words[index + 1 :])


def is_cluster(argument: str, /) -> bool:
    """Whether an argument is a cluster of short options, such as `-xf`."""

    return argument.startswith("-") and not argument.startswith("--")


def get_git_index(arguments: list[str], /) -> int:
    """The index of a git call's subcommand among its arguments, past its global options; the length when there is none."""

    index = 0
    while index < len(arguments) and arguments[index].startswith("-"):
        index += 2 if arguments[index] in GIT_VALUE_OPTIONS else 1

    return min(index, len(arguments))


def get_git_subcommand(arguments: list[str], /) -> str:
    """The subcommand of a git call, past its global options."""

    index = get_git_index(arguments)

    return arguments[index] if index < len(arguments) else ""


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


def get_joined_run(name: str, arguments: list[Word], /) -> str:
    """The shell command a joining runner runs: its words past its options (and the host of `ssh`), up to `parallel`'s `:::`."""

    index = skip_options(arguments, 0, JOINING_RUNNERS[name])
    index += 1 if name in REMOTE_RUNNERS else 0
    words = [word.text for word in arguments[index:]]
    end = next((position for position, word in enumerate(words) if word in PARALLEL_ARGUMENTS), len(words)) if name == "parallel" else len(words)

    return " ".join(words[:end])


def get_option_run(arguments: list[str], /) -> str:
    """The value of a `-c` or `--command` option, in a cluster ending in `c` (`-qc`) too; "" when there is none."""

    for index, argument in enumerate(arguments):
        following = arguments[index + 1] if index + 1 < len(arguments) else ""
        if argument == "--command" or (is_cluster(argument) and argument.endswith("c")):
            return following
        if argument.startswith("--command="):
            return argument.split("=", 1)[1]

    return ""


def get_alias_runs(name: str, arguments: list[str], /) -> list[Segment]:
    """The commands an alias definition stands for: a shell `alias n=value`, or a git alias set by `git config alias.n value`
    or `git -c alias.n=value`, a value starting with `!` being a shell command."""

    if name == "alias":
        return [segment for argument in arguments if "=" in argument for segment in get_segments(argument.split("=", 1)[1])]
    values: list[str] = []
    index = get_git_index(arguments)
    for position, argument in enumerate(arguments[:index]):
        if argument == "-c" and arguments[position + 1 : position + 2] and arguments[position + 1].lower().startswith("alias."):
            values.append(arguments[position + 1].split("=", 1)[-1] if "=" in arguments[position + 1] else "")
    if arguments[index : index + 1] == ["config"]:
        keys = [position for position, argument in enumerate(arguments) if position > index and argument.lower().startswith("alias.")]
        values += [arguments[position + 1] for position in keys[:1] if position + 1 < len(arguments)]
    texts = [value[1:] if value.startswith("!") else f"git {value}" for value in values if value]

    return [segment for text in texts for segment in get_segments(text)]


def get_inner_segments(command: Command, /) -> list[Segment]:
    """The commands a command runs from its arguments: a shell's -c string, an `eval`'s words, a find's -exec, the words of
    `watch`, `parallel` and `ssh`, the `-c` of `su` and `script`, and what a shell or git alias it defines stands for."""

    name = os.path.basename(command.name)
    arguments = [word.text for word in command.arguments]
    if name in SHELLS:
        return get_segments(get_shell_string(arguments))
    if name == "eval":
        return get_segments(" ".join(arguments))
    if name == "find":
        return get_find_runs(command.arguments)
    if name in JOINING_RUNNERS:
        return get_segments(get_joined_run(name, command.arguments))
    if name in OPTION_RUNNERS:
        return get_segments(get_option_run(arguments))
    if name in ("alias", "git"):
        return get_alias_runs(name, arguments)

    return []
