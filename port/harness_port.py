#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import sys
from pathlib import Path
from typing import Literal, NamedTuple

Target = Literal["kiro", "cortex"]
TARGETS: tuple[Target, ...] = ("kiro", "cortex")

CHECKOUT = Path(__file__).resolve().parent.parent
SHIM_SUFFIX = "port/shim.py"
SHIM = CHECKOUT / SHIM_SUFFIX
MANIFEST_NAME = "harness-port.json"
KIRO_PROMPTS_FOLDER = "harness-prompts"
KIRO_AGENTS_FILE = "file://AGENTS.md"
KIRO_STEERING_GLOB = "file://.kiro/steering/**/*.md"
LEGACY_KIRO_HOOKS = "hooks/harness.json"
HOOK_TIMEOUT_SECONDS = 10
CREW_FOLDER = "crew"
CREW_HOOKS_NAME = "hooks.json"
CREW_BACKUP_NAME = "hooks.json.harness-backup"
CREW_ENTRY_PREFIX = "harness-"
CREW_COMMAND_TIMEOUT_SECONDS = 8
CREW_ENTRY_TIMEOUT_SECONDS = 30
CREW_ID_LENGTH = 8
CREW_BLOCK_EXIT = 2
CREW_TOOL_EVENTS = ("PreToolUse", "PostToolUse")
CREW_TRIGGERS = {
    "SessionStart": "AgentSpawn",
    "UserPromptSubmit": "UserPromptSubmit",
    "PreToolUse": "PreToolUse",
    "PostToolUse": "PostToolUse",
    "Stop": "Stop",
}
CREW_NOT_PORTED = (
    "kiro crew: SubagentStart and SubagentStop have no crew event; "
    "a guard 'ask' becomes a block and a command rewrite becomes a block with a note"
)
HARNESS_REF = re.compile(r"harness:([a-z][a-z0-9-]*)")
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)
HOOK_SCRIPT = re.compile(r"hooks/(\w+)\.py")

KIRO_TAGS = {
    "Read": "read", "Grep": "read", "Glob": "read",
    "Edit": "write", "Write": "write", "NotebookEdit": "write",
    "Bash": "shell", "WebFetch": "web", "WebSearch": "web",
    "Agent": "subagent", "Task": "subagent",
}
CORTEX_TOOLS = {
    "Read": "read", "Write": "write", "Edit": "edit", "Grep": "grep", "Glob": "glob",
    "Bash": "bash", "WebFetch": "web_fetch", "WebSearch": "web_search",
    "Agent": "task", "Task": "task",
}
CORTEX_EXTRA_IDS = {"Edit": ["multi_edit"]}
KIRO_MATCHER_IDS = {
    "Bash": ["execute_bash"],
    "Read": ["read_file"],
    "Write": ["fs_write", "fs_append"],
    "Edit": ["str_replace"],
    "Grep": ["grep_search"],
    "Glob": ["file_search"],
    "Agent": ["invoke_sub_agent"],
    "Task": ["invoke_sub_agent"],
}
KIRO_TRIGGERS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Stop",
)


class Frontmatter(NamedTuple):

    fields: dict[str, str | list[str]]
    body: str


class Plan:

    def __init__(self) -> None:
        self.files: dict[Path, str] = {}
        self.cortex_hooks: dict[str, list[dict]] = {}
        self.not_ported: list[str] = []
        self.crew_hooks: list[dict] = []


def parse_frontmatter(text: str, /) -> Frontmatter:
    found = FRONTMATTER.match(text)
    if found is None:
        return Frontmatter({}, text)

    fields: dict[str, str | list[str]] = {}
    current_key = ""
    for line in found.group(1).splitlines():
        item = re.match(r"^\s+-\s+(.*?)\s*$", line)
        key = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if item and current_key:
            value = fields.setdefault(current_key, [])
            assert isinstance(value, list)
            value.append(item.group(1))
        elif key:
            current_key = key.group(1)
            fields[current_key] = key.group(2) if key.group(2) else []
    return Frontmatter(fields, found.group(2))


def rewrite_text(text: str, /) -> str:
    return HARNESS_REF.sub(r"harness-\1", text).replace(
        "${CLAUDE_PLUGIN_ROOT}", str(CHECKOUT)
    )


def split_tools(value: str | list[str], /) -> list[str]:
    assert isinstance(value, str)
    return [name.strip() for name in value.split(",") if name.strip()]


def get_kiro_matcher(names: list[str], /) -> str | None:
    ids = [tool_id for name in names for tool_id in KIRO_MATCHER_IDS.get(name, [])]
    unique = list(dict.fromkeys(ids))
    return f"^({'|'.join(unique)})$" if unique else None


def get_cortex_matcher(names: list[str], /) -> str | None:
    ids = [
        tool_id
        for name in names
        if name in CORTEX_TOOLS
        for tool_id in [CORTEX_TOOLS[name], *CORTEX_EXTRA_IDS.get(name, [])]
    ]
    spellings = [spelling for tool_id in ids for spelling in (tool_id, tool_id.capitalize())]
    unique = list(dict.fromkeys(spellings))
    return "|".join(unique) if unique else None


def make_command(target: Target, event: str, hook_command: str, /) -> str:
    tail = hook_command.partition("uv run --script ")[2].replace(
        "${CLAUDE_PLUGIN_ROOT}", str(CHECKOUT)
    )
    return f'uv run --script "{SHIM}" --host {target} --event {event} {tail}'


def make_crew_command(uv_path: str, event: str, hook_command: str, /) -> str:
    inner = make_command("kiro", event, hook_command).replace(
        "uv run --script", f"{shlex.quote(uv_path)} run --script", 1
    )
    script = (
        "if command -v timeout >/dev/null 2>&1; "
        f"then timeout {CREW_COMMAND_TIMEOUT_SECONDS} sh -c {shlex.quote(inner)}; "
        f"else sh -c {shlex.quote(inner)}; fi; "
        f'rc=$?; [ "$rc" -eq {CREW_BLOCK_EXIT} ] && exit {CREW_BLOCK_EXIT}; exit 0'
    )
    return f"sh -c {shlex.quote(script)}"


def make_crew_entry(uv_path: str, event: str, hook_command: str, /) -> dict:
    script = HOOK_SCRIPT.search(hook_command)
    name = f"{CREW_ENTRY_PREFIX}{event}-{script.group(1) if script else 'hook'}"
    return {
        "id": hashlib.sha256(name.encode()).hexdigest()[:CREW_ID_LENGTH],
        "name": name,
        "event": CREW_TRIGGERS[event],
        "matcher": "*" if event in CREW_TOOL_EVENTS else "",
        "matcher_mode": "glob",
        "command": make_crew_command(uv_path, CREW_TRIGGERS[event], hook_command),
        "skills": [],
        "timeout": CREW_ENTRY_TIMEOUT_SECONDS,
        "enabled": True,
        "last_run": 0.0,
        "last_status": "",
        "last_error": "",
        "run_count": 0,
    }


def plan_crew_hooks(plan: Plan, source: dict, /) -> None:
    uv_path = shutil.which("uv")
    if uv_path is None:
        plan.not_ported.append("kiro crew: uv not found on PATH, crew hooks skipped")
        return
    for event, groups in source.items():
        if event not in CREW_TRIGGERS:
            continue
        for group in groups:
            for hook in group["hooks"]:
                plan.crew_hooks.append(make_crew_entry(uv_path, event, hook["command"]))


def plan_skills(plan: Plan, dest: Path, /) -> None:
    for skill_file in sorted((CHECKOUT / "skills").glob("*/SKILL.md")):
        fields, body = parse_frontmatter(skill_file.read_text())
        name = f"harness-{skill_file.parent.name}"
        header = (
            f"---\nname: {name}\ndescription: {fields.get('description', '')}\n---\n"
        )
        folder = dest / "skills" / name
        plan.files[folder / "SKILL.md"] = rewrite_text(header + body)
        for reference in sorted((skill_file.parent / "references").glob("*")):
            if reference.is_file():
                plan.files[folder / "references" / reference.name] = rewrite_text(
                    reference.read_text()
                )


def get_preload_sections(skills: list[str], /) -> str:
    sections = ""
    for skill in skills:
        _, body = parse_frontmatter((CHECKOUT / "skills" / skill / "SKILL.md").read_text())
        sections += f"\n# Skill harness-{skill}\n\n{rewrite_text(body.strip())}\n"
    return sections


def get_kiro_resources(dest: Path, preloaded: list[str], /) -> list[str]:
    skill_resources = {
        f"skill://{dest / 'skills' / f'harness-{skill_file.parent.name}' / 'SKILL.md'}"
        for skill_file in (CHECKOUT / "skills").glob("*/SKILL.md")
        if skill_file.parent.name not in preloaded
    }
    return sorted({KIRO_AGENTS_FILE, KIRO_STEERING_GLOB} | skill_resources)


def plan_agent(
    plan: Plan, dest: Path, target: Target, agent_file: Path, models: dict[str, str], /
) -> None:
    fields, body = parse_frontmatter(agent_file.read_text())
    name = f"harness-{fields['name']}"
    tools = split_tools(fields.get("tools", ""))
    skills = fields.get("skills", [])
    model = models.get(str(fields.get("model", "")))
    assert isinstance(skills, list)
    prompt = rewrite_text(body.lstrip("\n")) + get_preload_sections(skills)
    prompt_path = dest / KIRO_PROMPTS_FOLDER / f"{name}.md"

    if target == "kiro":
        config: dict[str, object] = {
            "name": name,
            "description": str(fields["description"]),
            "prompt": f"file://{prompt_path}",
            "tools": list(
                dict.fromkeys(KIRO_TAGS[tool] for tool in tools if tool in KIRO_TAGS)
            ),
            "resources": get_kiro_resources(dest, skills),
        }
        if model:
            config["model"] = model
        plan.files[dest / "agents" / f"{name}.json"] = (
            json.dumps(config, indent=2) + "\n"
        )
        plan.files[prompt_path] = prompt
        return

    dropped = [tool for tool in tools if tool not in CORTEX_TOOLS]
    if dropped:
        plan.not_ported.append(
            f"agent {name}: tools {', '.join(dropped)} (no Cortex id)"
        )
    ids = list(dict.fromkeys(CORTEX_TOOLS[tool] for tool in tools if tool in CORTEX_TOOLS))
    tool_lines = "".join(f"  - {tool_id}\n" for tool_id in ids)
    header = f"---\nname: {name}\ndescription: {fields['description']}\ntools:\n{tool_lines}"
    if model:
        header += f"model: {model}\n"
    plan.files[dest / "agents" / f"{name}.md"] = header + "---\n\n" + prompt


def plan_hook_group(
    plan: Plan, target: Target, event: str, group: dict, kiro_entries: list[dict], /
) -> None:
    names = group["matcher"].split("|") if group.get("matcher") else []
    if target == "kiro":
        if event not in KIRO_TRIGGERS:
            plan.not_ported.append(f"hook {event}: Kiro has no such trigger")
            return
        matcher = get_kiro_matcher(names)
    else:
        if event == "SubagentStart":
            plan.not_ported.append("hook SubagentStart: Cortex has no such event")
            return
        if event == "SubagentStop":
            plan.not_ported.append(
                "hook SubagentStop report gate: advisory only, Cortex cannot block there"
            )
        matcher = get_cortex_matcher(names)
    if names and matcher is None:
        plan.not_ported.append(f"hook {event} {group['matcher']}: no {target} tool id")
        return

    for hook in group["hooks"]:
        command = make_command(target, event, hook["command"])
        if target == "cortex":
            cortex_group: dict = {
                "hooks": [
                    {
                        "type": "command",
                        "command": command,
                        "timeout": HOOK_TIMEOUT_SECONDS,
                    }
                ]
            }
            if matcher:
                cortex_group["matcher"] = matcher
            plan.cortex_hooks.setdefault(event, []).append(cortex_group)
            continue
        script = HOOK_SCRIPT.search(hook["command"])
        entry: dict = {
            "name": f"harness-{event}-{script.group(1) if script else 'hook'}",
            "trigger": event,
        }
        if matcher:
            entry["matcher"] = matcher
        entry["action"] = {"type": "command", "command": command}
        entry["timeout"] = HOOK_TIMEOUT_SECONDS
        kiro_entries.append(entry)


def plan_hooks(plan: Plan, dest: Path, target: Target, /) -> None:
    source = json.loads((CHECKOUT / "hooks" / "hooks.json").read_text())["hooks"]
    kiro_entries: list[dict] = []
    for event, groups in source.items():
        for group in groups:
            plan_hook_group(plan, target, event, group, kiro_entries)
    if target == "kiro":
        plan.files[dest / "hooks" / "harness-hooks.json"] = (
            json.dumps({"version": "v1", "hooks": kiro_entries}, indent=2) + "\n"
        )
        plan.not_ported.append(
            "kiro: a guard 'ask' becomes a block, and a command rewrite becomes a block with a note"
        )
        plan_crew_hooks(plan, source)


def is_ours(group: dict, /) -> bool:
    return any(
        SHIM_SUFFIX in hook.get("command", "") for hook in group.get("hooks", [])
    )


def is_ours_kiro_hooks(text: str, /) -> bool:
    try:
        document = json.loads(text)
    except ValueError:
        return False
    if not isinstance(document, dict) or document.get("version") != "v1":
        return False
    entries = document.get("hooks")
    if not isinstance(entries, list) or not entries:
        return False
    return all(
        isinstance(entry, dict)
        and isinstance(entry.get("action"), dict)
        and SHIM_SUFFIX in str(entry["action"].get("command", ""))
        for entry in entries
    )


def find_legacy_hooks(dest: Path, /) -> list[str]:
    try:
        text = (dest / LEGACY_KIRO_HOOKS).read_text()
    except (OSError, UnicodeDecodeError):
        return []
    return [LEGACY_KIRO_HOOKS] if is_ours_kiro_hooks(text) else []


def merge_cortex_hooks(
    existing: dict, ours: dict[str, list[dict]], /
) -> dict:
    hooks = existing.get("hooks", {})
    if not isinstance(hooks, dict) or not all(
        isinstance(groups, list) for groups in hooks.values()
    ):
        raise ValueError(
            "the existing hooks document must hold `hooks` as an object of lists; nothing was written"
        )

    merged = dict(existing)
    events = {
        event: [group for group in groups if not is_ours(group)]
        for event, groups in existing.get("hooks", {}).items()
    }
    for event, groups in ours.items():
        events.setdefault(event, []).extend(groups)
    merged["hooks"] = {event: groups for event, groups in events.items() if groups}
    return merged


def is_crew_ours(entry: object, /) -> bool:
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("name"), str)
        and entry["name"].startswith(CREW_ENTRY_PREFIX)
    )


def merge_crew_hooks(existing: dict, ours: list[dict], /) -> dict:
    entries = existing.get("hooks", [])
    if entries == {}:
        entries = []
    if not isinstance(entries, list):
        raise ValueError(
            "the crew hooks document must hold `hooks` as a list; nothing was written"
        )

    merged = dict(existing)
    merged["hooks"] = [entry for entry in entries if not is_crew_ours(entry)] + ours
    return merged


def write_crew_hooks(path: Path, document: dict, /) -> None:
    if path.exists():
        shutil.copy2(path, path.with_name(CREW_BACKUP_NAME))
    path.write_text(json.dumps(document, indent=2) + "\n")


def load_json(path: Path, /) -> dict:
    if not path.exists():
        return {}

    try:
        document = json.loads(path.read_text())
    except ValueError as error:
        raise ValueError(
            f"{path} is not valid JSON ({error}); fix or remove it. Nothing was written."
        ) from error
    if not isinstance(document, dict):
        raise TypeError(
            f"{path} must hold a JSON object, not {type(document).__name__}. Nothing was written."
        )

    return document


def uninstall(dest: Path, /, *, dry_run: bool) -> list[str]:
    manifest_path = dest / MANIFEST_NAME
    if not manifest_path.exists():
        return [f"nothing to remove: no {manifest_path}"]

    manifest = load_json(manifest_path)
    documents = {
        name: merge_cortex_hooks(load_json(dest / name), {})
        for name in manifest.get("merged", [])
    }
    legacy = find_legacy_hooks(dest) if manifest.get("target") == "kiro" else []
    crew_path = dest / CREW_FOLDER / CREW_HOOKS_NAME
    crew_document = (
        merge_crew_hooks(load_json(crew_path), [])
        if manifest.get("crew_merged") and crew_path.exists()
        else None
    )
    lines = []
    for name in dict.fromkeys([*manifest.get("files", []), *legacy]):
        lines.append(f"remove {name}")
        if dry_run:
            continue
        (dest / name).unlink(missing_ok=True)
        parent = (dest / name).parent
        while parent != dest and parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    for name in manifest.get("merged", []):
        lines.append(f"unmerge {name}")
        if dry_run:
            continue
        path = dest / name
        document = documents[name]
        if document["hooks"] or len(document) > 1:
            path.write_text(json.dumps(document, indent=2) + "\n")
        else:
            path.unlink(missing_ok=True)
    if crew_document is not None:
        lines.append(f"unmerge {CREW_FOLDER}/{CREW_HOOKS_NAME}")
        if not dry_run:
            write_crew_hooks(crew_path, crew_document)
    if not dry_run:
        manifest_path.unlink()
    return lines


def install(
    dest: Path, target: Target, models: dict[str, str], /, *, dry_run: bool
) -> list[str]:
    plan = Plan()
    plan_skills(plan, dest)
    for agent_file in sorted((CHECKOUT / "agents").glob("*.md")):
        plan_agent(plan, dest, target, agent_file, models)
    plan_hooks(plan, dest, target)

    crew_path = dest / CREW_FOLDER / CREW_HOOKS_NAME
    has_crew = target == "kiro" and bool(plan.crew_hooks) and crew_path.parent.is_dir()
    if has_crew:
        plan.not_ported.append(CREW_NOT_PORTED)
    elif target == "kiro":
        plan.not_ported.append(f"kiro crew: no {crew_path.parent} folder or no uv, crew hooks skipped")

    names = sorted(str(path.relative_to(dest)) for path in plan.files)
    merged = ["hooks.json"] if target == "cortex" else []
    legacy = find_legacy_hooks(dest) if target == "kiro" else []
    lines = [f"write {name}" for name in names] + [f"merge {name}" for name in merged]
    lines += [f"remove {name}" for name in legacy]
    if has_crew:
        lines.append(f"merge {CREW_FOLDER}/{CREW_HOOKS_NAME}")
    lines += [f"not ported: {item}" for item in plan.not_ported]

    previous = dest / MANIFEST_NAME
    hooks_path = dest / "hooks.json"
    stale = (set(load_json(previous).get("files", [])) - set(names)) | set(legacy)
    document = (
        merge_cortex_hooks(load_json(hooks_path), plan.cortex_hooks) if merged else {}
    )
    crew_document = (
        merge_crew_hooks(load_json(crew_path), plan.crew_hooks) if has_crew else {}
    )
    if dry_run:
        return lines

    for name in sorted(stale):
        (dest / name).unlink(missing_ok=True)
    for path, text in plan.files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    if merged:
        hooks_path.write_text(json.dumps(document, indent=2) + "\n")
    if has_crew:
        write_crew_hooks(crew_path, crew_document)
    manifest = {
        "target": target,
        "checkout": str(CHECKOUT),
        "files": names,
        "merged": merged,
        "crew_merged": has_crew,
        "not_ported": plan.not_ported,
    }
    previous.write_text(json.dumps(manifest, indent=2) + "\n")
    return lines


def get_default_dest(target: Target, /) -> Path:
    home = Path(os.path.expanduser("~"))
    return home / ".kiro" if target == "kiro" else home / ".snowflake" / "cortex"


def main() -> int:
    parser = argparse.ArgumentParser(description="Install this plugin's skills, agents and hooks into Kiro CLI or Snowflake Cortex Code.")
    parser.add_argument("--target", choices=TARGETS, required=True)
    parser.add_argument("--dest", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        metavar="NAME=ID",
        help="e.g. haiku=<model id>",
    )
    args = parser.parse_args()

    dest = (args.dest or get_default_dest(args.target)).resolve()
    models = dict(item.split("=", 1) for item in args.model if "=" in item)
    try:
        if args.uninstall:
            lines = uninstall(dest, dry_run=args.dry_run)
        else:
            lines = install(dest, args.target, models, dry_run=args.dry_run)
    except (ValueError, TypeError) as error:
        print(f"harness-port: {error}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
