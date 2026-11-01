"""What the hooks share: the project and its `.harness.json`, the roles the plugin judges, the data folder, fences."""

from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_NAME = ".harness.json"
PLUGIN_PREFIX = "harness:"
FEEDBACK_FOLDER = "harness-feedback"
INBOX = f"{FEEDBACK_FOLDER}/inbox.md"
HANDLED = f"{FEEDBACK_FOLDER}/handled.md"
# The plugin's roles, by the report form each owes.
FULL_ROLES = {"worker", "reviewer", "auditor"}
SHORT_ROLES = {"scout", "runner", "cold-reader"}
ROLES = FULL_ROLES | SHORT_ROLES


def find_project(cwd: str, /) -> tuple[Path | None, dict]:  # keys are data
    """The folder holding `.harness.json` and its contents, or (None, {}) when there is none.

    The search starts from `CLAUDE_PROJECT_DIR`, so a `cd` in a session does not change its project; from `cwd` only when
    the variable is not set. Without the file a project gets the always-on guard rules and no pipeline gate. A broken
    file raises: each hook then exits 1, which shows the error and lets the call run.
    """

    folder = Path(os.environ.get("CLAUDE_PROJECT_DIR") or cwd).resolve()
    for candidate in (folder, *folder.parents):
        path = candidate / CONFIG_NAME
        if path.is_file():
            return candidate, json.loads(path.read_text())

    return None, {}


def get_scratch(root: Path, config: dict, /) -> str:  # keys are data
    """The resolved absolute folder of `guard.scratch` (`scratch/` and `./scratch` are `scratch`), empty when not set."""

    scratch = config.get("guard", {}).get("scratch")

    return os.path.realpath(root / scratch) if scratch else ""


def get_report_form(agent_type: str, settings: dict, /) -> str:  # keys are data
    """The report an agent type owes under `.harness.json`'s `report` settings: "full", "short", or "" for not judged.

    The six roles count with or without the plugin's prefix, so `other:worker` is another plugin's agent. `report.short`
    and `report.full` add roles by the name the event carries.
    """

    role = agent_type.removeprefix(PLUGIN_PREFIX)
    if role in SHORT_ROLES or role in settings.get("short", ()):
        return "short"
    if role in FULL_ROLES or role in settings.get("full", ()):
        return "full"

    return ""


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


def data_folder() -> Path:
    """The plugin's data folder, which survives plugin updates, created if missing."""

    folder = Path(os.environ.get("CLAUDE_PLUGIN_DATA") or Path.home() / ".cache" / "harness")
    folder.mkdir(parents=True, exist_ok=True)

    return folder
