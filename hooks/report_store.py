from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

from common import PLUGIN_PREFIX, data_folder, ensure_state_folder, find_project, write_atomic

SLUG_CHARS = 40
SAVED_LINE_PREFIX = "Saved report: "


def get_agent_transcript(event: dict, /) -> Path:

    given = event.get("agent_transcript_path") or ""
    if given:
        return Path(given)
    session = event.get("transcript_path") or ""

    return Path(session).with_suffix("") / "subagents" / f"agent-{event.get('agent_id') or 'unknown'}.jsonl"


def get_description(event: dict, /) -> str:

    try:
        meta = json.loads(get_agent_transcript(event).with_suffix(".meta.json").read_text())
        return " ".join(str(meta.get("description") or "").split())
    except (OSError, ValueError, AttributeError):
        return ""


def get_slug(event: dict, /) -> str:

    description = get_description(event)
    slug = re.sub(r"[^a-z0-9]+", "-", description.lower())[:SLUG_CHARS].strip("-")
    agent_id = re.sub(r"[^A-Za-z0-9_-]", "", str(event.get("agent_id") or ""))[:80]

    return slug or agent_id or "unknown"


def get_saved_marker(event: dict, /) -> Path:

    name = re.sub(r"[^A-Za-z0-9_-]", "", str(event.get("agent_id") or "unknown"))[:80]

    return data_folder() / "saved" / f"{name}.path"


def create_unique(folder: Path, stem: str, /) -> tuple[Path, int]:

    suffix = 1
    while True:
        path = folder / (f"{stem}.md" if suffix == 1 else f"{stem}-{suffix}.md")
        try:
            return path, os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            suffix += 1


def save_report(event: dict, report: str, /) -> str:

    try:
        marker = get_saved_marker(event)
        if marker.is_file():
            return ""
        root, _ = find_project(event.get("cwd") or os.getcwd())
        folder = ensure_state_folder(root) / "reports"
        folder.mkdir(parents=True, exist_ok=True)
        role = str(event.get("agent_type") or "agent").removeprefix(PLUGIN_PREFIX)
        stem = f"{datetime.now().strftime('%Y-%m-%d-%H%M')}-{role}-{get_slug(event)}"
        path, descriptor = create_unique(folder, stem)
        with os.fdopen(descriptor, "w") as file:
            file.write(report)
        marker.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(marker, str(path))

        return f"{SAVED_LINE_PREFIX}{path}"
    except OSError:
        return ""


def get_notes_path(event: dict, /) -> Path:

    session = event.get("session_id") or Path(event.get("transcript_path") or "").stem
    name = re.sub(r"[^A-Za-z0-9_-]", "", str(session))[:80] or "unknown"

    return data_folder() / "saved" / f"{name}.notes"


def add_note(event: dict, line: str, /) -> None:

    try:
        path = get_notes_path(event)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as file:
            file.write(line + "\n")
    except OSError:
        pass


def take_notes(event: dict, /) -> str:

    path = get_notes_path(event)
    try:
        text = path.read_text()
        path.write_text("")
    except OSError:
        return ""

    return "; ".join(text.splitlines())
