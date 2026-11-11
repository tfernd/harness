#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT_TOOL = Path(os.environ.get("HARNESS_PORT_TOOL", ROOT / "bin" / "harness-port"))
PORT_SCRIPT = ROOT / "port" / "harness_port.py"
INSTALL_SH = ROOT / "install.sh"
SHIM = Path(os.environ.get("HARNESS_PORT_SHIM", ROOT / "port" / "shim.py"))
WORK = ROOT / "__scratch__" / "port-check"
FOREIGN_COMMAND = "echo foreign"
FRONTMATTER_NAME = re.compile(r"^name:\s*(.+?)\s*$", re.MULTILINE)
TOOLS_BLOCK = re.compile(r"^tools:\n((?:  - .+\n)+)", re.MULTILINE)
AGENT_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
SKILL_LINE = re.compile(r"^\s+-\s+(\S+)\s*$")
HARNESS_REF = re.compile(r"harness:([a-z][a-z0-9-]*)")
SCRIPT_PATH = re.compile(r"(/[^\"\\\s]+\.py)")
MIN_HOOK_PATHS = 10
MIN_SKILLS = 20
MIN_PRELOADS = 11


def check(condition: bool, message: str) -> None:
    if not condition:
        print(f"FAIL: {message}")
        sys.exit(1)


def run_port(target: str, dest: Path, *flags: str) -> str:
    done = subprocess.run(
        [str(PORT_TOOL), "--target", target, "--dest", str(dest), *flags],
        capture_output=True,
        text=True,
        timeout=120,
    )
    check(
        done.returncode == 0,
        f"harness-port {target} {flags} exited {done.returncode}: {done.stderr[-300:]}",
    )
    return done.stdout


def get_preloads(agent_file: Path) -> list[str]:
    found = AGENT_FRONTMATTER.match(agent_file.read_text())
    assert found is not None
    names: list[str] = []
    in_skills = False
    for line in found.group(1).splitlines():
        if line.startswith("skills:"):
            in_skills = True
        elif in_skills and SKILL_LINE.match(line):
            names.append(SKILL_LINE.match(line).group(1))
        else:
            in_skills = False
    return names


def get_first_body_line(skill_file: Path) -> str:
    found = AGENT_FRONTMATTER.match(skill_file.read_text())
    assert found is not None
    first = next(line for line in found.group(2).splitlines() if line.strip())
    return HARNESS_REF.sub(r"harness-\1", first)


def check_preloads(dest: Path, target: str) -> None:
    checked = 0
    for agent_file in sorted((ROOT / "agents").glob("*.md")):
        skills = get_preloads(agent_file)
        name = f"harness-{agent_file.stem}"
        if target == "kiro":
            prompt = (dest / "harness-prompts" / f"{name}.md").read_text()
            resources = json.loads((dest / "agents" / f"{name}.json").read_text())["resources"]
        else:
            prompt = (dest / "agents" / f"{name}.md").read_text()
            resources = []
        for skill in skills:
            first = get_first_body_line(ROOT / "skills" / skill / "SKILL.md")
            check(f"# Skill harness-{skill}\n" in prompt, f"{target}: {name} lacks the heading of {skill}")
            check(first in prompt, f"{target}: {name} prompt lacks the text of {skill}")
            check(
                not any(f"harness-{skill}/SKILL.md" in resource for resource in resources),
                f"{target}: {name} resources still list skill://{skill}",
            )
            checked += 1
    check(checked >= MIN_PRELOADS, f"{target}: only {checked} preloads checked")


def check_kiro_resources(dest: Path) -> None:
    config = json.loads((dest / "agents" / "harness-planner.json").read_text())
    resources = config["resources"]
    preloaded = get_preloads(ROOT / "agents" / "planner.md")
    others = [path.name for path in sorted((ROOT / "skills").iterdir()) if path.name not in preloaded]
    check("file://AGENTS.md" in resources, f"kiro: resources lack AGENTS.md: {resources}")
    check("file://.kiro/steering/**/*.md" in resources, "kiro: resources lack the steering glob")
    check(bool(preloaded) and bool(others), "kiro: planner has no preload or no other skill")
    for skill in others:
        skill_file = dest / "skills" / f"harness-{skill}" / "SKILL.md"
        check(f"skill://{skill_file}" in resources, f"kiro: resources lack skill://{skill}")
        check(skill_file.is_file(), f"kiro: {skill_file} missing after install")
    check(resources == sorted(set(resources)), "kiro: resources not sorted and unique")


def check_texts(dest: Path, target: str) -> None:
    skills = sorted((dest / "skills").glob("*/SKILL.md"))
    check(len(skills) >= MIN_SKILLS, f"{target}: only {len(skills)} skills")
    for skill in skills:
        found = FRONTMATTER_NAME.search(skill.read_text())
        check(
            found is not None and found.group(1) == skill.parent.name,
            f"{target}: skill name differs from folder {skill.parent.name}",
        )
    for path in dest.rglob("*"):
        if path.is_file() and path.name != "harness-port.json":
            text = path.read_text()
            check("harness:" not in text, f"{target}: `harness:` left in {path.name}")
            check(
                "${CLAUDE_PLUGIN_ROOT}" not in text,
                f"{target}: CLAUDE_PLUGIN_ROOT left in {path.name}",
            )

    planner = dest / "agents" / "harness-planner"
    if target == "kiro":
        config = json.loads(planner.with_suffix(".json").read_text())
        check(config["name"] == "harness-planner", "kiro agent name")
        prompt_file = dest / "harness-prompts" / "harness-planner.md"
        check(config["prompt"] == f"file://{prompt_file}", f"kiro agent prompt path {config['prompt']}")
        check(not list((dest / "agents").glob("*.md")), "kiro agents folder holds a .md file")
        check(config["tools"] == ["read", "shell"], f"kiro agent tags {config['tools']}")
        check("model" not in config, "kiro agent has a model")
        check(prompt_file.read_text().strip() != "", "kiro agent prompt file empty")
        check_preloads(dest, target)
        check_kiro_resources(dest)
        return

    text = planner.with_suffix(".md").read_text()
    check(get_cortex_tools(text) == ["read", "grep", "glob", "bash"], "cortex agent tools are not a YAML list")
    check("model:" not in text, "cortex agent has a model")
    check_preloads(dest, target)
    for agent in (dest / "agents").glob("*.md"):
        tools = get_cortex_tools(agent.read_text())
        check(
            bool(tools) and tools == [tool.lower() for tool in tools],
            f"cortex tool ids not a lowercase list in {agent.name}",
        )


def get_cortex_tools(text: str) -> list[str]:
    found = TOOLS_BLOCK.search(text)
    if found is None:
        return []
    return [line.strip()[2:] for line in found.group(1).splitlines()]


def check_kiro_old_layout(base: Path) -> None:
    dest = base / "kiro-old"
    agents = dest / "agents"
    agents.mkdir(parents=True)
    old = ["agents/harness-planner.md", "agents/harness-scout.md"]
    for name in old:
        (dest / name).write_text("old prompt\n")
    (agents / "mine.md").write_text("foreign\n")
    (dest / "harness-port.json").write_text(json.dumps({"target": "kiro", "files": old, "merged": []}))
    run_port("kiro", dest)
    left = sorted(path.name for path in agents.glob("*.md"))
    check(left == ["mine.md"], f"kiro install over the old layout left {left}")
    run_port("kiro", dest, "--uninstall")
    check(not (dest / "harness-prompts").exists(), "kiro uninstall left the prompts folder")
    check((agents / "mine.md").exists(), "kiro uninstall removed a foreign agent file")


def load_legacy_name(script: Path) -> str:
    spec = importlib.util.spec_from_file_location("harness_port_under_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return str(module.LEGACY_KIRO_HOOKS)


def plant_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def run_kiro_script(script: Path, dest: Path, *flags: str) -> None:
    done = subprocess.run(
        ["uv", "run", "--script", str(script), "--target", "kiro", "--dest", str(dest), *flags],
        capture_output=True,
        text=True,
        timeout=120,
    )
    check(done.returncode == 0, f"kiro {flags} exited {done.returncode}: {done.stderr[-300:]}")


def check_kiro_legacy_hooks(base: Path, script: Path) -> None:
    legacy_name = load_legacy_name(script)
    ours = json.dumps(
        {
            "version": "v1",
            "hooks": [
                {
                    "name": "old",
                    "trigger": "PreToolUse",
                    "action": {"type": "command", "command": "python3 /old/checkout/port/shim.py guard"},
                    "timeout": 5,
                }
            ],
        }
    )
    foreign = json.dumps(
        {
            "version": "v1",
            "hooks": [
                {
                    "name": "mine",
                    "trigger": "PreToolUse",
                    "action": {"type": "command", "command": "echo mine"},
                    "timeout": 5,
                }
            ],
        }
    )

    ours_dest = base / "kiro-legacy-ours"
    plant_file(ours_dest / legacy_name, ours)
    run_kiro_script(script, ours_dest)
    check(
        not (ours_dest / legacy_name).exists(),
        "kiro install left the old hooks file the port wrote",
    )
    check(
        (ours_dest / "hooks" / "harness-hooks.json").exists(),
        "kiro install did not write the new hooks file",
    )
    plant_file(ours_dest / legacy_name, ours)
    run_kiro_script(script, ours_dest, "--uninstall")
    check(
        not (ours_dest / legacy_name).exists(),
        "kiro uninstall left the old hooks file the port wrote",
    )

    foreign_dest = base / "kiro-legacy-foreign"
    plant_file(foreign_dest / legacy_name, foreign)
    run_kiro_script(script, foreign_dest)
    kept = (foreign_dest / legacy_name).read_text() if (foreign_dest / legacy_name).exists() else None
    check(kept == foreign, f"kiro install changed or removed a foreign hooks file: {kept!r}")
    run_kiro_script(script, foreign_dest, "--uninstall")
    kept = (foreign_dest / legacy_name).read_text() if (foreign_dest / legacy_name).exists() else None
    check(kept == foreign, f"kiro uninstall removed a foreign hooks file: {kept!r}")


def check_hook_paths(text: str, target: str) -> None:
    paths = SCRIPT_PATH.findall(text)
    check(len(paths) >= MIN_HOOK_PATHS, f"{target}: only {len(paths)} hook script paths")
    for path in paths:
        check(Path(path).exists(), f"{target}: hook script missing {path}")


def check_kiro(base: Path) -> None:
    dest = base / "kiro"
    run_port("kiro", dest, "--dry-run")
    check(not dest.exists(), "dry run wrote files")
    run_port("kiro", dest)
    check_texts(dest, "kiro")
    hooks_text = (dest / "hooks" / "harness-hooks.json").read_text()
    hooks = json.loads(hooks_text)
    check(hooks["version"] == "v1", "kiro hooks version")
    check_hook_paths(hooks_text, "kiro")
    guard = next(h for h in hooks["hooks"] if h["name"] == "harness-PreToolUse-guard")
    check(
        guard["matcher"] == "^(execute_bash|fs_write|fs_append|str_replace)$",
        f"kiro guard matcher {guard['matcher']}",
    )
    check(
        guard["trigger"] == "PreToolUse" and guard["action"]["type"] == "command",
        "kiro guard shape",
    )
    check(
        not any(h["trigger"].startswith("Subagent") for h in hooks["hooks"]),
        "kiro subagent hook ported",
    )
    run_port("kiro", dest, "--uninstall")
    check(not list(dest.rglob("*")), f"kiro uninstall left {list(dest.rglob('*'))[:3]}")


def get_crew_names(path: Path) -> list[str]:
    return [entry["name"] for entry in json.loads(path.read_text())["hooks"]]


def check_kiro_crew(base: Path) -> None:
    absent = base / "crew-absent"
    run_port("kiro", absent)
    check(not (absent / "crew").exists(), "crew folder created from nothing")
    check("crew hooks skipped" in run_port("kiro", absent, "--dry-run"), "crew skip note missing")
    run_port("kiro", absent, "--uninstall")

    dest = base / "crew-present"
    crew_file = dest / "crew" / "hooks.json"
    owner = {
        "id": "a0f9acde",
        "name": "owner-gate",
        "event": "Stop",
        "matcher": "",
        "matcher_mode": "glob",
        "command": "true",
        "skills": [],
        "timeout": 30,
        "enabled": True,
        "last_run": 0.0,
        "last_status": "",
        "last_error": "",
        "run_count": 0,
    }
    plant_file(crew_file, json.dumps({"hooks": [owner]}))
    run_port("kiro", dest)
    names = get_crew_names(crew_file)
    check(names[0] == "owner-gate", f"owner entry lost or moved {names[:2]}")
    check(json.loads(crew_file.read_text())["hooks"][0] == owner, "owner entry changed")
    ours = [name for name in names if name.startswith("harness-")]
    check(ours and len(ours) == len(names) - 1, f"crew entries {names}")
    check((dest / "crew" / "hooks.json.harness-backup").exists(), "no crew backup")
    document = json.loads(crew_file.read_text())
    guard = next(e for e in document["hooks"] if e["name"] == "harness-PreToolUse-guard")
    check(
        guard["event"] == "PreToolUse" and guard["matcher"] == "*" and guard["matcher_mode"] == "glob",
        f"crew guard shape {guard}",
    )
    check(set(guard) == set(owner), f"crew entry keys {sorted(guard)}")
    check(guard["enabled"] is True and guard["timeout"] > 8 and guard["skills"] == [], f"crew guard fields {guard}")
    check(any(e["event"] == "AgentSpawn" for e in document["hooks"]), "no AgentSpawn entry")
    check(not any("Subagent" in e["event"] for e in document["hooks"]), "subagent hook in crew")
    check(guard["command"].startswith("sh -c "), "crew command not wrapped")
    ids = [e["id"] for e in document["hooks"]]
    check(len(set(ids)) == len(ids), "crew ids not unique")
    check_crew_entries_narrow(document, dest.parent)

    run_port("kiro", dest)
    check(get_crew_names(crew_file) == names, "reinstall changed or duplicated crew entries")

    run_port("kiro", dest, "--uninstall")
    check(get_crew_names(crew_file) == ["owner-gate"], f"uninstall left {get_crew_names(crew_file)}")


def check_crew_wrapper() -> None:
    port = load_port_module()
    fake = Path(WORK) / "fake-uv"
    for code in (0, 1, 2, 3):
        fake.write_text(f"#!/bin/sh\nexit {code}\n")
        fake.chmod(0o755)
        command = port.make_crew_command(str(fake), "PreToolUse", "uv run --script ${CLAUDE_PLUGIN_ROOT}/hooks/guard.py")
        got = subprocess.run(command, shell=True, capture_output=True, timeout=60).returncode
        want = 2 if code == 2 else 0
        check(got == want, f"crew wrapper: hook exit {code} gave {got}, wanted {want}")
    fake.write_text("#!/bin/sh\nsleep 30\n")
    command = port.make_crew_command(str(fake), "PreToolUse", "uv run --script x.py")
    got = subprocess.run(command, shell=True, capture_output=True, timeout=60).returncode
    check(got == 0, f"crew wrapper: timeout gave {got}")


def check_cortex(base: Path) -> None:
    dest = base / "cortex"
    dest.mkdir(parents=True)
    foreign = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "bash",
                    "hooks": [{"type": "command", "command": FOREIGN_COMMAND}],
                }
            ]
        },
        "other": 1,
    }
    (dest / "hooks.json").write_text(json.dumps(foreign))
    run_port("cortex", dest)
    first = (dest / "hooks.json").read_text()
    check_texts(dest, "cortex")
    check_hook_paths(first, "cortex")
    merged = json.loads(first)
    check(
        FOREIGN_COMMAND in first and merged["other"] == 1,
        "merge dropped the foreign hook",
    )
    run_port("cortex", dest)
    check((dest / "hooks.json").read_text() == first, "rerun changed or duplicated hooks")
    check("SubagentStart" not in merged["hooks"], "cortex SubagentStart ported")
    check_cortex_ids(dest, merged)
    check(
        any(
            g.get("matcher") == "bash|Bash|write|Write|edit|Edit|multi_edit|Multi_edit"
            for g in merged["hooks"]["PreToolUse"]
        ),
        "cortex guard matcher",
    )
    run_port("cortex", dest, "--uninstall")
    check(
        json.loads((dest / "hooks.json").read_text()) == foreign,
        "uninstall did not leave exactly the foreign hook",
    )
    left = sorted(str(path.relative_to(dest)) for path in dest.rglob("*") if path.is_file())
    check(left == ["hooks.json"], f"cortex uninstall left {left}")


def check_cortex_ids(dest: Path, merged: dict) -> None:
    groups = merged["hooks"]["PreToolUse"]
    task_groups = [g for g in groups if "task" in g.get("matcher", "").split("|")]
    commands = " ".join(h["command"] for g in task_groups for h in g["hooks"])
    check("brief_lint.py" in commands, "cortex PreToolUse has no task group running brief_lint")
    delegating = [
        g
        for g in groups
        if any("delegate.py" in h["command"] for h in g["hooks"])
        and "multi_edit" in g["matcher"].split("|")
    ]
    check(bool(delegating), "cortex delegate.py group does not match multi_edit")
    turn_groups = [
        g
        for g in merged["hooks"]["PostToolUse"]
        if any("turn.py" in h["command"] for h in g["hooks"])
    ]
    check(
        any("task" in g["matcher"].split("|") for g in turn_groups),
        "cortex turn.py group does not match task",
    )
    for group in groups:
        if FOREIGN_COMMAND in group["hooks"][0]["command"]:
            continue
        names = group.get("matcher", "").split("|")
        check(len(names) == len(set(names)), f"cortex matcher repeats an id: {names}")
        if "bash" in names:
            check("Bash" in names, f"cortex matcher lacks Bash: {names}")
    check_cortex_agent_task(dest.parent)


def load_port_module() -> object:
    script = PORT_TOOL.resolve().parent.parent / "port" / "harness_port.py"
    spec = importlib.util.spec_from_file_location("harness_port_under_check", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def check_cortex_agent_task(base: Path) -> None:
    port = load_port_module()
    agent_file = base / "spawner.md"
    agent_file.write_text(
        "---\nname: spawner\ndescription: d\ntools: Read, Agent, Edit\n---\nbody\n"
    )
    plan = port.Plan()
    port.plan_agent(plan, base / "out", "cortex", agent_file, {})
    written = plan.files[base / "out" / "agents" / "harness-spawner.md"]
    check(
        get_cortex_tools(written) == ["read", "task", "edit"],
        f"agent with Agent lacks task: {get_cortex_tools(written)}",
    )


def run_shim(
    host: str,
    event: str,
    payload: dict,
    base: Path,
    hook: str = "",
    config: str = "",
    matcher: str = "",
) -> subprocess.CompletedProcess:
    home = base / "home"
    home.mkdir(parents=True, exist_ok=True)
    project = base / "project"
    project.mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    (base / "owner.json").write_text(config or "{}")
    environment = {
        **os.environ,
        "HOME": str(home),
        "HARNESS_CONFIG": str(base / "owner.json"),
    }
    for name in ("CLAUDE_PROJECT_DIR", "CLAUDE_PLUGIN_ROOT"):
        environment.pop(name, None)
    hook = hook or {"SessionStart": "context.py", "PreToolUse": "guard.py"}[event]
    command = [
        "uv",
        "run",
        "--script",
        str(SHIM),
        "--host",
        host,
        "--event",
        event,
        *(["--matcher", matcher] if matcher else []),
        str(ROOT / "hooks" / hook),
    ]
    return subprocess.run(
        command,
        input=json.dumps({**payload, "cwd": str(project)}),
        capture_output=True,
        text=True,
        env=environment,
        timeout=60,
    )


def make_clone(base: Path, name: str, edits: tuple[tuple[str, str], ...] = ()) -> Path:
    clone = base / name
    (clone / "port").mkdir(parents=True)
    text = PORT_SCRIPT.read_text()
    for old, new in edits:
        check(text.count(old) == 1, f"plant text not found once: {old}")
        text = text.replace(old, new)
    (clone / "port" / "harness_port.py").write_text(text)
    for folder in ("skills", "agents", "hooks"):
        (clone / folder).symlink_to(ROOT / folder)
    return clone / "port" / "harness_port.py"


def run_script(script: Path, dest: Path, *flags: str) -> subprocess.CompletedProcess:
    command = [
        "uv",
        "run",
        "--script",
        str(script),
        "--target",
        "cortex",
        "--dest",
        str(dest),
        *flags,
    ]
    return subprocess.run(command, capture_output=True, text=True, timeout=120)


def find_write_on_broken(script: Path, base: Path) -> str:
    for name, content in (("broken", "{not json"), ("array", "[]")):
        dest = base / name
        dest.mkdir(parents=True)
        (dest / "hooks.json").write_text(content)
        done = run_script(script, dest)
        written = sorted(path.name for path in dest.iterdir() if path.name != "hooks.json")
        if done.returncode == 0:
            return f"{name}: exit 0 on a bad hooks file"
        if written or (dest / "hooks.json").read_text() != content:
            return f"{name}: wrote before refusing: {written}"
        if "hooks.json" not in done.stderr or "Traceback" in done.stderr:
            return f"{name}: no clear message: {done.stderr[-200:]}"
    return ""


def find_doubled_groups(script: Path, base: Path) -> str:
    other = make_clone(base, "other-clone")
    dest = base / "reinstalled"
    fresh = base / "fresh"
    for target, path in ((dest, other), (dest, script), (fresh, script)):
        done = run_script(path, target)
        if done.returncode != 0:
            return f"install exited {done.returncode}: {done.stderr[-200:]}"
    if (dest / "hooks.json").read_text() != (fresh / "hooks.json").read_text():
        return "reinstall from another clone left the old clone's groups"
    return ""


def check_install_guards(base: Path) -> None:
    no_validation = (
        (
            "merge_cortex_hooks(load_json(hooks_path), plan.cortex_hooks) if merged else {}",
            "{}",
        ),
        (
            "hooks_path.write_text(json.dumps(document,",
            "hooks_path.write_text(json.dumps(merge_cortex_hooks(load_json(hooks_path), plan.cortex_hooks),",
        ),
    )
    old_match = (("SHIM_SUFFIX in hook.get", "str(SHIM) in hook.get"),)
    real = make_clone(base, "real")
    reason = find_write_on_broken(real, base / "real-broken")
    check(reason == "", f"broken hooks file: {reason}")
    planted = find_write_on_broken(make_clone(base, "late", no_validation), base / "late-broken")
    check(planted != "", "control: validating after the writes was not caught")
    reason = find_doubled_groups(real, base / "real-double")
    check(reason == "", f"reinstall: {reason}")
    planted = find_doubled_groups(make_clone(base, "path-match", old_match), base / "path-match-double")
    check(planted != "", "control: matching the shim by absolute path was not caught")


def load_shim() -> object:

    spec = importlib.util.spec_from_file_location("harness_shim", SHIM)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_shim_cortex_ids() -> None:
    shim = load_shim()
    spawn_input = {"description": "d", "prompt": "Goal: keep me", "subagent_type": "scout"}
    spawn = shim.map_event({"tool_name": "task", "tool_input": spawn_input}, "cortex", "PreToolUse")
    check(spawn["tool_name"] == "Agent", f"cortex task became {spawn['tool_name']}")
    check(spawn["tool_input"] == spawn_input, f"cortex task input changed: {spawn['tool_input']}")
    edit = shim.map_event(
        {"tool_name": "multi_edit", "tool_input": {"file_path": "a.py", "edits": []}},
        "cortex",
        "PreToolUse",
    )
    check(edit["tool_name"] == "Edit", f"cortex multi_edit became {edit['tool_name']}")
    check(edit["tool_input"]["file_path"] == "a.py", "cortex multi_edit lost file_path")


def get_source_matcher(hook: str, /) -> str:
    source = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]["PreToolUse"]
    matchers = [
        group.get("matcher", "")
        for group in source
        for entry in group["hooks"]
        if f"hooks/{hook}" in entry["command"]
    ]
    assert len(matchers) == 1, matchers
    return matchers[0]


def run_crew_entry(entry: dict, payload: dict, base: Path) -> subprocess.CompletedProcess:
    home = base / "home"
    home.mkdir(parents=True, exist_ok=True)
    project = base / "project"
    project.mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    (base / "owner.json").write_text("{}")
    environment = {**os.environ, "HOME": str(home), "HARNESS_CONFIG": str(base / "owner.json")}
    for name in ("CLAUDE_PROJECT_DIR", "CLAUDE_PLUGIN_ROOT"):
        environment.pop(name, None)
    return subprocess.run(
        entry["command"],
        shell=True,
        input=json.dumps({**payload, "cwd": str(project)}),
        capture_output=True,
        text=True,
        env=environment,
        timeout=90,
    )


def check_shim_matcher(base: Path) -> None:
    lint_matcher = get_source_matcher("brief_lint.py")
    guard_matcher = get_source_matcher("guard.py")
    check(lint_matcher != "" and guard_matcher != "", "source hooks.json lost a matcher")

    read = run_shim(
        "kiro",
        "PreToolUse",
        {"tool_name": "fs_read", "tool_input": {"path": "x"}},
        base,
        "brief_lint.py",
        matcher=lint_matcher,
    )
    check(read.returncode == 0, f"crew read event refused by brief_lint: {read.returncode} {read.stderr[-200:]}")

    named = {"agent_name": "harness-scout", "prompt": "Goal: x"}
    spawn = run_shim(
        "kiro",
        "PreToolUse",
        {"tool_name": "core/spawn_run", "tool_input": named},
        base,
        "brief_lint.py",
        matcher=lint_matcher,
    )
    check(spawn.returncode == 0, f"crew spawn_run with an agent name exited {spawn.returncode}: {spawn.stderr[-200:]}")

    generic = run_shim(
        "kiro",
        "PreToolUse",
        {"tool_name": "spawn_run", "tool_input": {"agent_name": "general-purpose"}},
        base,
        "brief_lint.py",
        matcher=lint_matcher,
    )
    check(generic.returncode == 2, f"crew spawn_run did not reach brief_lint: {generic.returncode}")

    nameless = run_shim(
        "kiro",
        "PreToolUse",
        {"tool_name": "core/spawn_run", "tool_input": {"prompt": "Goal: x"}},
        base,
        "brief_lint.py",
        matcher=lint_matcher,
    )
    check(nameless.returncode == 0, f"crew spawn_run with no agent field exited {nameless.returncode}")

    bash = run_shim(
        "kiro",
        "PreToolUse",
        {"tool_name": "execute_bash", "tool_input": {"command": "rm -rf build"}},
        base,
        "guard.py",
        matcher=guard_matcher,
    )
    check(bash.returncode == 2, f"matcher stopped a Bash call reaching guard: {bash.returncode} {bash.stderr[-200:]}")

    session = run_shim(
        "kiro",
        "SessionStart",
        {"hook_event_name": "agentSpawn"},
        base,
        matcher="Agent",
    )
    check(
        session.returncode == 0 and "orchestrator" in session.stdout,
        f"matcher stopped a non-tool event: {session.stderr[-200:]}",
    )


def check_crew_entries_narrow(document: dict, base: Path) -> None:
    entries = {entry["name"]: entry for entry in document["hooks"]}
    lint = entries["harness-PreToolUse-brief_lint"]
    guard = entries["harness-PreToolUse-guard"]
    read = run_crew_entry(lint, {"tool_name": "fs_read", "tool_input": {"path": "x"}}, base)
    check(read.returncode == 0, f"crew brief_lint entry refused a read: {read.returncode} {read.stderr[-200:]}")
    rm = run_crew_entry(guard, {"tool_name": "execute_bash", "tool_input": {"command": "rm -rf build"}}, base)
    check(rm.returncode == 2, f"crew guard entry let rm -rf through: {rm.returncode}")


def check_shim(base: Path) -> None:
    rm_input = {"command": "rm -rf build"}
    kiro_block = run_shim(
        "kiro",
        "PreToolUse",
        {"tool_name": "execute_bash", "tool_input": rm_input},
        base,
    )
    check(
        kiro_block.returncode == 2,
        f"kiro rm -rf build exited {kiro_block.returncode}: {kiro_block.stderr[-200:]}",
    )
    kiro_safe = run_shim(
        "kiro",
        "PreToolUse",
        {"tool_name": "execute_bash", "tool_input": {"command": "ls"}},
        base,
    )
    check(kiro_safe.returncode == 0, f"kiro ls exited {kiro_safe.returncode}")

    for agent_input in (
        {"agent_name": "harness-scout", "prompt": "Goal: x"},
        {"task": "Goal: x"},
    ):
        spawn = run_shim(
            "kiro",
            "PreToolUse",
            {"tool_name": "invoke_sub_agent", "tool_input": agent_input},
            base,
            "brief_lint.py",
        )
        check(
            spawn.returncode == 0,
            f"kiro sub-agent {agent_input} exited {spawn.returncode}: {spawn.stderr[-200:]}",
        )

    package = run_shim(
        "kiro",
        "PreToolUse",
        {"tool_name": "execute_bash", "tool_input": {"command": "pip install x"}},
        base,
        config='{"guard": {"ask_packages": true}}',
    )
    check(
        package.returncode == 2,
        f"kiro: an owner question did not become a block, exit {package.returncode}",
    )
    shim = load_shim()
    check(
        shim.get_agent_type({"agent_name": "harness-scout"}) == "harness:scout",
        "kiro agent name not mapped to its role",
    )
    check(
        shim.get_agent_type({}) == "host-agent",
        "a nameless kiro agent is not another tool's agent",
    )

    start = run_shim("kiro", "SessionStart", {"hook_event_name": "agentSpawn"}, base)
    check(
        start.returncode == 0 and "orchestrator" in start.stdout,
        f"kiro SessionStart lacks orchestrator: {start.stderr[-200:]}",
    )
    check(not start.stdout.lstrip().startswith("{"), "kiro SessionStart printed JSON")

    check_shim_cortex_ids()
    cortex_block = run_shim("cortex", "PreToolUse", {"tool_name": "bash", "tool_input": rm_input}, base)
    blocked = cortex_block.returncode == 2 or '"block"' in cortex_block.stdout
    check(
        blocked,
        f"cortex rm -rf build not blocked: {cortex_block.returncode} {cortex_block.stdout[-200:]}",
    )


def run_install_sh(script: Path, home: Path, upstream: Path, *args: str) -> subprocess.CompletedProcess:
    environment = {
        **os.environ,
        "HOME": str(home),
        "HARNESS_HOME": str(home / "clone"),
        "HARNESS_REPO": str(upstream),
    }
    return subprocess.run(["sh", str(script), *args], capture_output=True, text=True, env=environment, timeout=180)


def hash_tree(folder: Path) -> list[tuple[str, str]]:
    return sorted((str(path.relative_to(folder)), path.read_text()) for path in folder.rglob("*") if path.is_file())


def find_install_sh_fault(script: Path, base: Path) -> str:
    home = base / "home"
    home.mkdir(parents=True)
    upstream = base / "upstream"
    git = ["git", "-c", "user.name=t", "-c", "user.email=none"]
    subprocess.run(["git", "clone", "-q", str(ROOT), str(upstream)], check=True)
    for args, expected in (((), 2), (("windows",), 2)):
        done = run_install_sh(script, home, upstream, *args)
        if done.returncode != expected:
            return f"args {args} exited {done.returncode}, not {expected}"
    done = run_install_sh(script, home, upstream, "kiro")
    if done.returncode != 0:
        return f"install exited {done.returncode}: {done.stderr[-200:]}"
    installed = hash_tree(home / ".kiro")
    if not any(name == "harness-port.json" for name, _ in installed):
        return "install wrote no manifest into the sandbox home"
    done = run_install_sh(script, home, upstream, "kiro")
    if done.returncode != 0 or hash_tree(home / ".kiro") != installed:
        return f"rerun changed the tree or exited {done.returncode}"
    (upstream / "extra.txt").write_text("upstream\n")
    subprocess.run([*git, "-C", str(upstream), "add", "extra.txt"], check=True)
    subprocess.run([*git, "-C", str(upstream), "commit", "-q", "-m", "upstream"], check=True)
    (home / "clone" / "local.txt").write_text("local\n")
    subprocess.run([*git, "-C", str(home / "clone"), "add", "local.txt"], check=True)
    subprocess.run([*git, "-C", str(home / "clone"), "commit", "-q", "-m", "local"], check=True)
    done = run_install_sh(script, home, upstream, "kiro")
    if done.returncode == 0 or not (home / "clone" / "local.txt").exists():
        return f"a diverged clone did not stop the run (exit {done.returncode})"
    subprocess.run([*git, "-C", str(home / "clone"), "reset", "-q", "--hard", "HEAD~1"], check=True)
    done = run_install_sh(script, home, upstream, "kiro", "--uninstall")
    if done.returncode != 0 or "rm -rf" not in done.stdout:
        return f"uninstall exited {done.returncode} or printed no rm -rf line"
    left = sorted(path.name for path in (home / ".kiro").rglob("*"))
    if left:
        return f"uninstall left {left[:3]}"
    if not (home / "clone").exists():
        return "uninstall deleted the clone"
    return ""


def check_install_sh(base: Path) -> None:
    reason = find_install_sh_fault(INSTALL_SH, base / "install-real")
    check(reason == "", f"install.sh: {reason}")
    text = INSTALL_SH.read_text()
    plants = {
        "pull failure ignored": ("git -C \"$dir\" pull -q --ff-only", "git -C \"$dir\" pull -q --ff-only || true"),
        "target not passed": ('--target "$target" "$@"', '"$@"'),
    }
    for name, (old, new) in plants.items():
        check(text.count(old) == 1, f"plant text not found once: {old}")
        planted = base / f"install-{name.replace(' ', '-')}"
        planted.mkdir(parents=True)
        (planted / "install.sh").write_text(text.replace(old, new))
        check(find_install_sh_fault(planted / "install.sh", planted / "run") != "", f"control: {name} was not caught")


def main() -> int:
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    (WORK.parent / ".gitignore").write_text("*\n")
    check_kiro(WORK)
    check_kiro_crew(WORK)
    check_crew_wrapper()
    check_kiro_old_layout(WORK)
    check_kiro_legacy_hooks(WORK, PORT_SCRIPT)
    check_cortex(WORK)
    check_shim(WORK)
    check_shim_matcher(WORK)
    check_install_guards(WORK)
    check_install_sh(WORK)
    shutil.rmtree(WORK, ignore_errors=True)
    print("check_port: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
