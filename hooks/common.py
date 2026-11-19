# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///

from __future__ import annotations

import fnmatch
import glob
import json
import os
import re
import shutil
import time
from collections.abc import Set
from pathlib import Path
from typing import NamedTuple

from shell import Segment, Word, get_segments

USER_CONFIG_VARIABLE = "HARNESS_CONFIG"
DEFAULTS: dict = {
    "guard": {"ask_packages": True, "ask_cloud": True, "ask_installers": True, "tool_delay_days": 7},
    "progress": {"every": 10},
    "tests_kept": {"enabled": True},
    "lint": {"rules": ["comment", "docstring", "split", "untyped"]},
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
        "*.sql": ["harness:code-sql"],
        "*.yaml": ["harness:code-yaml"],
        "*.yml": ["harness:code-yaml"],
        "Makefile": ["harness:code-make"],
        "GNUmakefile": ["harness:code-make"],
        "*.mk": ["harness:code-make"],
        "*.sh": ["harness:code-shell"],
        "*.bash": ["harness:code-shell"],
        "tests/*.py": ["harness:testing", "harness:code-python"],
    },
}
PLUGIN_PREFIX = "harness:"
HANDBACK_TOOL = "SubagentHandback"
EDIT_TOOLS = frozenset({"Edit", "Write", "NotebookEdit"})
HARNESS_FOLDER = "__harness__"
SCRATCH_ROOT = Path("/tmp/harness")
STATE_FOLDER_NAME = "harness"
STATE_FOLDER_DISPLAY = "~/.local/state/harness"
HARNESS_README = """# harness state

State of the harness plugin for this project, kept outside the project so git never sees it. Read these files by path.

Per-machine data (turn counters, send-backs, progress) lives in the plugin's data folder (`$CLAUDE_PLUGIN_DATA`,
else `~/.cache/harness`), not here.
"""


def read_sections(path: Path, /) -> dict:

    if not path.is_file():
        return {}
    config = json.loads(path.read_text())
    sections = config.items() if isinstance(config, dict) else ()

    return {key: value if isinstance(value, dict) else {} for key, value in sections}


def merge_sections(*layers: dict) -> dict:

    merged: dict = {}
    for layer in layers:
        for key, value in layer.items():
            merged[key] = {**merged.get(key, {}), **value}

    return merged


class Project(NamedTuple):

    root: Path
    config: dict


def find_git_root(start: Path, /) -> Path | None:

    for candidate in (start, *start.parents):
        if not is_project_root(candidate):
            return None
        if (candidate / ".git").exists():
            return candidate

    return None


def get_project_entries(projects: object, root: Path, /) -> dict:

    layers: list[dict] = []
    if isinstance(projects, dict):
        for pattern, entry in projects.items():
            if isinstance(entry, dict) and fnmatch.fnmatch(str(root), os.path.expanduser(str(pattern))):
                layers.append({key: value for key, value in entry.items() if isinstance(value, dict)})

    return merge_sections(*layers)


def find_project(cwd: str, /) -> Project:

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

    home = Path.home().resolve()

    return root != home and root not in home.parents


def get_scratch_folder(root: Path, /) -> Path:

    return SCRATCH_ROOT / root.name


def get_state_folder(root: Path, /) -> Path:

    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")

    return base / STATE_FOLDER_NAME / root.name


def ensure_scratch_folder(root: Path, /) -> Path:

    folder = get_scratch_folder(root)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        os.chmod(SCRATCH_ROOT, 0o1777)
    except OSError:
        pass

    return folder


def ensure_state_folder(root: Path, /) -> Path:

    folder = get_state_folder(root)
    old = root / HARNESS_FOLDER
    try:
        folder.mkdir(parents=True, exist_ok=True)
        if old.is_dir() and not any(folder.iterdir()):
            shutil.copytree(old, folder, dirs_exist_ok=True)
        readme = folder / "README.md"
        if not readme.exists():
            readme.write_text(HARNESS_README)
    except OSError:
        pass

    return folder


def get_scratch(root: Path, config: dict, /) -> str:

    scratch = config.get("guard", {}).get("scratch")
    if not is_project_root(root):
        return ""

    return os.path.realpath(root / scratch) if scratch else ""


def make_note_output(note: str, /) -> dict:

    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": note}}


def get_fenced_indices(lines: list[str], /) -> set[int]:

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

    lines = text.splitlines()
    fenced = get_fenced_indices(lines)

    return [line for index, line in enumerate(lines) if index not in fenced]


def get_turns(events: list[dict], /) -> list[list[dict]]:

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

    with open(path, "rb") as file:
        end = file.seek(0, os.SEEK_END)
        start = max(0, end - size)
        file.seek(start)
        data = file.read()

    return data.partition(b"\n")[2] if start else data


def data_folder() -> Path:

    folder = Path(os.environ.get("CLAUDE_PLUGIN_DATA") or Path.home() / ".cache" / "harness")
    folder.mkdir(parents=True, exist_ok=True)

    return folder


def write_atomic(path: Path, text: str, /) -> None:

    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(text)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)



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
SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
SHELL_VALUE_OPTIONS = frozenset({"-o", "+o", "-O", "+O", "--rcfile", "--init-file"})
FIND_RUNNERS = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
FIND_RUNNER_ENDS = frozenset({";", "+"})
GIT_VALUE_OPTIONS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--attr-source"})
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")
JOINING_RUNNERS = {
    "watch": frozenset({"-n", "--interval"}),
    "parallel": frozenset({"-j", "--jobs", "-P", "--max-procs", "-S", "--sshlogin", "-a", "--arg-file", "--delay", "--timeout", "-n", "-N", "--max-args", "--joblog", "--results", "--colsep", "-C", "-d", "--delimiter", "-E", "-I", "-L", "--workdir", "--wd", "--tmpdir", "--retries", "--halt", "-l", "--load", "-s", "--tagstring", "--env"}),
    "ssh": frozenset({"-b", "-B", "-c", "-D", "-E", "-e", "-F", "-I", "-i", "-J", "-L", "-l", "-m", "-O", "-o", "-p", "-Q", "-R", "-S", "-W", "-w"}),
}
REMOTE_RUNNERS = frozenset({"ssh"})
PARALLEL_ARGUMENTS = frozenset({":::", "::::", ":::+", "::::+"})
OPTION_RUNNERS = frozenset({"su", "script"})


class Command(NamedTuple):

    name: str
    arguments: list[Word]


def skip_options(words: list[Word], index: int, value_options: Set[str], /) -> int:

    while index < len(words) and words[index].text.startswith("-"):
        index += 2 if words[index].text in value_options else 1

    return index


def resolve(segment: Segment, policy: object = None, /) -> Command:

    words = segment.words
    index = 0
    while index < len(words):
        word = words[index].text
        if ASSIGNMENT.match(word) or word in PREFIXES:
            index += 1
        elif word in OPTION_PREFIXES:
            index = skip_options(words, index + 1, OPTION_PREFIXES[word])
            if word == "timeout":
                index += 1
        else:
            break
    if index >= len(words):
        return Command("", [])

    return Command(words[index].text, words[index + 1 :])


def is_cluster(argument: str, /) -> bool:

    return argument.startswith("-") and not argument.startswith("--")


def get_git_index(arguments: list[str], /) -> int:

    index = 0
    while index < len(arguments) and arguments[index].startswith("-"):
        index += 2 if arguments[index] in GIT_VALUE_OPTIONS else 1

    return min(index, len(arguments))


def get_git_subcommand(arguments: list[str], /) -> str:

    index = get_git_index(arguments)

    return arguments[index] if index < len(arguments) else ""


def get_shell_string(arguments: list[str], /) -> str:

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

    index = skip_options(arguments, 0, JOINING_RUNNERS[name])
    index += 1 if name in REMOTE_RUNNERS else 0
    words = [word.text for word in arguments[index:]]
    end = next((position for position, word in enumerate(words) if word in PARALLEL_ARGUMENTS), len(words)) if name == "parallel" else len(words)

    return " ".join(words[:end])


def get_option_run(arguments: list[str], /) -> str:

    for index, argument in enumerate(arguments):
        following = arguments[index + 1] if index + 1 < len(arguments) else ""
        if argument == "--command" or (is_cluster(argument) and argument.endswith("c")):
            return following
        if argument.startswith("--command="):
            return argument.split("=", 1)[1]

    return ""


def get_alias_runs(name: str, arguments: list[str], /) -> list[Segment]:

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


JOBS_FOLDER = "waits"
JOBS_KEEP = 200
JOBS_MAX_BYTES = 65536
OUTPUT_DESCRIPTORS = ("1", "2")
PROC_FOLDER = os.environ.get("HARNESS_PROC_FOLDER", "/proc")


class BackgroundJob(NamedTuple):

    task_id: str
    output_path: str
    agent_id: str
    pid: int
    started: int


class Holder(NamedTuple):

    pid: int
    started: int


def get_jobs_path(session: str, kind: str, /) -> Path:

    folder = data_folder() / JOBS_FOLDER
    folder.mkdir(exist_ok=True)

    return folder / f"{session}.{kind}"


def get_tasks_folder(event: dict, session: str, /) -> Path | None:

    scratchpad = str(event.get("scratchpad_dir") or "")
    if scratchpad:
        return Path(scratchpad).parent / "tasks"
    matches = sorted(glob.glob(f"/tmp/claude-{os.getuid()}/*/{session}/tasks"))

    return Path(matches[0]) if matches else None


def get_start_time(pid: int, /) -> int | None:

    try:
        stat = Path(f"{PROC_FOLDER}/{pid}/stat").read_text()
        return int(stat.rpartition(")")[2].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def does_hold_output(pid: int, output_path: str, /) -> bool:

    for descriptor in OUTPUT_DESCRIPTORS:
        try:
            if os.readlink(f"{PROC_FOLDER}/{pid}/fd/{descriptor}") == output_path:
                return True
        except OSError:
            continue

    return False


def find_holders(output_path: str, /) -> list[Holder]:

    if not os.path.isdir(PROC_FOLDER):
        return []
    holders = []
    for name in os.listdir(PROC_FOLDER):
        if not name.isdigit() or not does_hold_output(int(name), output_path):
            continue
        started = get_start_time(int(name))
        if started is not None:
            holders.append(Holder(int(name), started))

    return holders


def record_background_job(event: dict, /) -> None:

    response = event.get("tool_response")
    session = str(event.get("session_id") or "")
    task_id = response.get("backgroundTaskId") if isinstance(response, dict) else None
    if event.get("tool_name") != "Bash" or not session or not isinstance(task_id, str) or not re.fullmatch(r"[\w-]+", task_id):
        return
    folder = get_tasks_folder(event, session)
    if folder is None:
        return
    output_path = str(folder / f"{task_id}.output")
    holders = find_holders(output_path)
    if not holders:
        return
    shell = min(holders, key=lambda holder: (holder.started, holder.pid))
    path = get_jobs_path(session, "jobs")
    with open(path, "a") as file:
        file.write(f"{task_id}\t{output_path}\t{event.get('agent_id') or ''}\t{shell.pid}\t{shell.started}\n")
    if path.stat().st_size > JOBS_MAX_BYTES:
        write_atomic(path, "\n".join(path.read_text().splitlines()[-JOBS_KEEP:]) + "\n")


def parse_background_job(line: str, /) -> BackgroundJob | None:

    row = line.split("\t")
    if len(row) != 5:
        return None
    try:
        return BackgroundJob(row[0], row[1], row[2], int(row[3]), int(row[4]))
    except ValueError:
        return None


def read_background_jobs(session: str, /) -> list[BackgroundJob]:

    path = get_jobs_path(session, "jobs")
    if not path.exists():
        return []
    jobs = [parse_background_job(line) for line in path.read_text().splitlines()]

    return [job for job in jobs if job is not None]


def is_job_running(job: BackgroundJob, /) -> bool:

    return get_start_time(job.pid) == job.started and does_hold_output(job.pid, job.output_path)


def get_pending_jobs(session: str, agent_id: str, /) -> list[BackgroundJob]:

    jobs = [job for job in read_background_jobs(session) if job.agent_id == agent_id]

    return [job for job in jobs if is_job_running(job)]


def read_looks(session: str, /) -> dict:

    path = get_jobs_path(session, "looks")
    looks = json.loads(path.read_text()) if path.exists() else {}

    return looks if isinstance(looks, dict) else {}


def get_look_wait_seconds(session: str, task_id: str, window_seconds: int, /) -> int:

    last = read_looks(session).get(task_id)
    if not isinstance(last, (int, float)):
        return 0

    return max(0, int(last + window_seconds - time.time()) + 1)


def mark_looked(session: str, task_ids: list[str], /) -> None:

    looks = read_looks(session)
    looks.update({task_id: time.time() for task_id in task_ids})
    write_atomic(get_jobs_path(session, "looks"), json.dumps(looks))
