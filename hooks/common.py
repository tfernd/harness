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
from pathlib import Path

CONFIG_NAME = ".harness.json"
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
def find_project(cwd: str, /) -> tuple[Path | None, dict]:  # keys are data: the dict holds keys of the user's config, not names in code
    """The folder holding `.harness.json` and its contents, or (None, {}) when there is none.

    The search starts from `CLAUDE_PROJECT_DIR`, so a `cd` in a session does not change its project; from `cwd` only when
    the variable is not set. Without the file a project gets the always-on guard rules and no other hook acts (no budget,
    brief, delegate, report or turn check). A broken
    file raises: each hook then exits 1, which shows the error and lets the call run.
    """

    folder = Path(os.environ.get("CLAUDE_PROJECT_DIR") or cwd).resolve()
    for candidate in (folder, *folder.parents):
        path = candidate / CONFIG_NAME
        if path.is_file():
            config = json.loads(path.read_text())
            # A section of the wrong type counts as empty, so one bad key can't crash a hook and drop every rule.
            return candidate, {key: value if isinstance(value, dict) else {} for key, value in config.items()}

    return None, {}


def get_scratch(root: Path, config: dict, /) -> str:  # config keys
    """The resolved absolute folder of `guard.scratch` (`scratch/` and `./scratch` are `scratch`), empty when not set."""

    scratch = config.get("guard", {}).get("scratch")

    return os.path.realpath(root / scratch) if scratch else ""


def get_unfenced_lines(text: str, /) -> list[str]:
    """The lines of a message outside its fenced blocks, which hold examples. A fence that never closes hides nothing."""

    lines = text.splitlines()
    fenced: set[int] = set()
    opened = -1
    for index, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            if opened < 0:
                opened = index
            else:
                fenced.update(range(opened, index + 1))
                opened = -1

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
