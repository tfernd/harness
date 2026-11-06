# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""What the hooks share: the project and its `.harness.json`, the roles the plugin judges, the data folder, fences."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

CONFIG_NAME = ".harness.json"
# The variable that points at the owner's config file, which every project gets under its own file; tests point it away.
USER_CONFIG_VARIABLE = "HARNESS_CONFIG"
TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "harness.json"
# The template sections every project gets with no file of its own. `guard` names project facts (a scratch folder), so it stays out.
DEFAULT_SECTIONS = ("brief", "skill_gate")
PLUGIN_PREFIX = "harness:"
HANDBACK_TOOL = "SubagentHandback"
EDIT_TOOLS = {"Edit", "Write", "NotebookEdit"}
FEEDBACK_FOLDER = "harness-feedback"
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


def find_project(cwd: str, /) -> tuple[Path, dict]:  # keys are data: the dict holds keys of the user's config, not names in code
    """The project folder and its config: the template's DEFAULT_SECTIONS, then the owner's file, then the project's `.harness.json`.

    The project folder is the nearest one holding `.harness.json`, else the start folder itself. The search starts from
    `CLAUDE_PROJECT_DIR`, so a `cd` in a session does not change its project; from `cwd` only when the variable is not set.
    The owner's file is `$HARNESS_CONFIG`, else `~/.config/harness/config.json`. So the budget, brief, skill, report and turn
    checks run in every project; the guard's project rules, the commit rule and delegation need the project's file
    (`has_project_file`). A broken file raises: each hook then exits 1, which shows the error and lets the call run.
    """

    folder = Path(os.environ.get("CLAUDE_PROJECT_DIR") or cwd).resolve()
    template = read_sections(TEMPLATE)
    user_path = Path(os.environ.get(USER_CONFIG_VARIABLE) or Path.home() / ".config" / "harness" / "config.json")
    # A broken owner's file counts as empty: it would otherwise take the guard's hard rules down in every project.
    try:
        owner = read_sections(user_path)
    except (OSError, ValueError):
        owner = {}
    base = merge_sections({key: template[key] for key in DEFAULT_SECTIONS if key in template}, owner)
    for candidate in (folder, *folder.parents):
        path = candidate / CONFIG_NAME
        if path.is_file():
            return candidate, merge_sections(base, read_sections(path))

    return folder, base


def has_project_file(root: Path, /) -> bool:
    """Whether the project's folder holds its own `.harness.json`, which opts it into the rules that need project facts."""

    return (root / CONFIG_NAME).is_file()


def get_feedback_root(root: Path, /) -> Path:
    """The folder that holds `harness-feedback/`: the project itself when it has its own file, else one in the data folder,
    so no file is ever written into a repo that never opted in."""

    if has_project_file(root):
        return root

    return data_folder() / "projects" / (re.sub(r"[^A-Za-z0-9]+", "-", str(root)).strip("-") or "root")


def get_scratch(root: Path, config: dict, /) -> str:  # config keys
    """The resolved absolute folder of `guard.scratch` (`scratch/` and `./scratch` are `scratch`), empty when not set."""

    scratch = config.get("guard", {}).get("scratch")

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
