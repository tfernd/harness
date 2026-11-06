#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""Check bin/harness-port and port/shim.py: converted files, merge and uninstall, and the shim end to end.

Writes under scratch/. Set HARNESS_PORT_SHIM to run the shim checks against another copy of the shim.
"""

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
PORT_TOOL = ROOT / "bin" / "harness-port"
SHIM = Path(os.environ.get("HARNESS_PORT_SHIM", ROOT / "port" / "shim.py"))
WORK = ROOT / "scratch" / "port-check"
FOREIGN_COMMAND = "echo foreign"
FRONTMATTER_NAME = re.compile(r"^name:\s*(.+?)\s*$", re.MULTILINE)
TOOLS_LINE = re.compile(r"^tools:\s*(.*)$", re.MULTILINE)
SCRIPT_PATH = re.compile(r"(/[^\"\\\s]+\.py)")
# Hook scripts hooks.json runs; fewer paths found means the converter dropped hooks.
MIN_HOOK_PATHS = 10
MIN_SKILLS = 20


def check(condition: bool, message: str) -> None:
    """Fail the run with a message when the condition is false."""
    if not condition:
        print(f"FAIL: {message}")
        sys.exit(1)


def run_port(target: str, dest: Path, *flags: str) -> str:
    """Run harness-port and return its output."""
    done = subprocess.run(
        [str(PORT_TOOL), "--target", target, "--dest", str(dest), *flags], capture_output=True, text=True, timeout=120
    )
    check(done.returncode == 0, f"harness-port {target} {flags} exited {done.returncode}: {done.stderr[-300:]}")
    return done.stdout


def check_texts(dest: Path, target: str) -> None:
    """Skill names match folders, no Claude-only text is left, agent files carry the right fields."""
    skills = sorted((dest / "skills").glob("*/SKILL.md"))
    check(len(skills) >= MIN_SKILLS, f"{target}: only {len(skills)} skills")
    for skill in skills:
        found = FRONTMATTER_NAME.search(skill.read_text())
        check(found is not None and found.group(1) == skill.parent.name, f"{target}: skill name differs from folder {skill.parent.name}")
    for path in dest.rglob("*"):
        if path.is_file() and path.name != "harness-port.json":
            text = path.read_text()
            check("harness:" not in text, f"{target}: `harness:` left in {path.name}")
            check("${CLAUDE_PLUGIN_ROOT}" not in text, f"{target}: CLAUDE_PLUGIN_ROOT left in {path.name}")

    analyst = dest / "agents" / "harness-analyst"
    if target == "kiro":
        config = json.loads(analyst.with_suffix(".json").read_text())
        check(config["name"] == "harness-analyst", "kiro agent name")
        check(config["prompt"] == "file://./harness-analyst.md", "kiro agent prompt path")
        check(config["tools"] == ["read", "shell"], f"kiro agent tags {config['tools']}")
        check("model" not in config, "kiro agent has a model")
        expected = f"skill://{dest / 'skills' / 'harness-report' / 'SKILL.md'}"
        check(expected in config["resources"], "kiro agent resources lack the report skill")
        check(analyst.with_suffix(".md").read_text().strip() != "", "kiro agent prompt file empty")
        return

    text = analyst.with_suffix(".md").read_text()
    tools_line = TOOLS_LINE.search(text)
    check(tools_line is not None and tools_line.group(1) == "read, grep, glob, bash", "cortex agent tools")
    check("model:" not in text, "cortex agent has a model")
    for agent in (dest / "agents").glob("*.md"):
        line = TOOLS_LINE.search(agent.read_text())
        check(line is not None and line.group(1) == line.group(1).lower(), f"cortex tool ids not lowercase in {agent.name}")


def check_hook_paths(text: str, target: str) -> None:
    """Every script path in a hook command exists."""
    paths = SCRIPT_PATH.findall(text)
    check(len(paths) >= MIN_HOOK_PATHS, f"{target}: only {len(paths)} hook script paths")
    for path in paths:
        check(Path(path).exists(), f"{target}: hook script missing {path}")


def check_kiro(base: Path) -> None:
    """Kiro conversion, dry run and uninstall."""
    dest = base / "kiro"
    run_port("kiro", dest, "--dry-run")
    check(not dest.exists(), "dry run wrote files")
    run_port("kiro", dest)
    check_texts(dest, "kiro")
    hooks_text = (dest / "hooks" / "harness.json").read_text()
    hooks = json.loads(hooks_text)
    check(hooks["version"] == "v1", "kiro hooks version")
    check_hook_paths(hooks_text, "kiro")
    guard = next(h for h in hooks["hooks"] if h["name"] == "harness-PreToolUse-guard")
    check(guard["matcher"] == "^(execute_bash|fs_write|fs_append|str_replace)$", f"kiro guard matcher {guard['matcher']}")
    check(guard["trigger"] == "PreToolUse" and guard["action"]["type"] == "command", "kiro guard shape")
    check(not any(h["trigger"].startswith("Subagent") for h in hooks["hooks"]), "kiro subagent hook ported")
    run_port("kiro", dest, "--uninstall")
    check(not list(dest.rglob("*")), f"kiro uninstall left {list(dest.rglob('*'))[:3]}")


def check_cortex(base: Path) -> None:
    """Cortex conversion, merge, rerun and uninstall."""
    dest = base / "cortex"
    dest.mkdir(parents=True)
    foreign = {"hooks": {"PreToolUse": [{"matcher": "bash", "hooks": [{"type": "command", "command": FOREIGN_COMMAND}]}]}, "other": 1}
    (dest / "hooks.json").write_text(json.dumps(foreign))
    run_port("cortex", dest)
    first = (dest / "hooks.json").read_text()
    check_texts(dest, "cortex")
    check_hook_paths(first, "cortex")
    merged = json.loads(first)
    check(FOREIGN_COMMAND in first and merged["other"] == 1, "merge dropped the foreign hook")
    run_port("cortex", dest)
    check((dest / "hooks.json").read_text() == first, "rerun changed or duplicated hooks")
    check("SubagentStart" not in merged["hooks"], "cortex SubagentStart ported")
    check(any(g.get("matcher") == "bash|write|edit" for g in merged["hooks"]["PreToolUse"]), "cortex guard matcher")
    run_port("cortex", dest, "--uninstall")
    check(json.loads((dest / "hooks.json").read_text()) == foreign, "uninstall did not leave exactly the foreign hook")
    left = sorted(str(path.relative_to(dest)) for path in dest.rglob("*") if path.is_file())
    check(left == ["hooks.json"], f"cortex uninstall left {left}")


def run_shim(host: str, event: str, payload: dict, base: Path, hook: str = "", config: str = "") -> subprocess.CompletedProcess:
    """Run a harness hook through the shim with the owner's files out of reach."""
    home = base / "home"
    home.mkdir(parents=True, exist_ok=True)
    project = base / "project"
    project.mkdir(exist_ok=True)
    (project / ".harness.json").write_text(config or (ROOT / ".harness.json").read_text())
    environment = {**os.environ, "HOME": str(home), "HARNESS_CONFIG": str(base / "no-config.json")}
    for name in ("CLAUDE_PROJECT_DIR", "CLAUDE_PLUGIN_ROOT"):
        environment.pop(name, None)
    hook = hook or {"SessionStart": "context.py", "PreToolUse": "guard.py"}[event]
    command = ["uv", "run", "--script", str(SHIM), "--host", host, "--event", event, str(ROOT / "hooks" / hook)]
    return subprocess.run(
        command, input=json.dumps({**payload, "cwd": str(project)}), capture_output=True, text=True, env=environment, timeout=60
    )


def load_shim() -> object:
    """The shim module, imported by path so a planted copy can stand in."""

    spec = importlib.util.spec_from_file_location("harness_shim", SHIM)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_shim(base: Path) -> None:
    """The shim end to end on both hosts."""
    rm_input = {"command": "rm -rf build"}
    kiro_block = run_shim("kiro", "PreToolUse", {"tool_name": "execute_bash", "tool_input": rm_input}, base)
    check(kiro_block.returncode == 2, f"kiro rm -rf build exited {kiro_block.returncode}: {kiro_block.stderr[-200:]}")
    kiro_safe = run_shim("kiro", "PreToolUse", {"tool_name": "execute_bash", "tool_input": {"command": "ls"}}, base)
    check(kiro_safe.returncode == 0, f"kiro ls exited {kiro_safe.returncode}")

    for agent_input in ({"agent_name": "harness-scout", "prompt": "Goal: x"}, {"task": "Goal: x"}):
        spawn = run_shim("kiro", "PreToolUse", {"tool_name": "invoke_sub_agent", "tool_input": agent_input}, base, "brief_lint.py")
        check(spawn.returncode == 0, f"kiro sub-agent {agent_input} exited {spawn.returncode}: {spawn.stderr[-200:]}")

    package = run_shim("kiro", "PreToolUse", {"tool_name": "execute_bash", "tool_input": {"command": "pip install x"}}, base, config='{"guard": {"ask_packages": true}}')
    check(package.returncode == 2, f"kiro: an owner question did not become a block, exit {package.returncode}")
    shim = load_shim()
    check(shim.get_agent_type({"agent_name": "harness-scout"}) == "harness:scout", "kiro agent name not mapped to its role")
    check(shim.get_agent_type({}) == "host-agent", "a nameless kiro agent is not another tool's agent")

    start = run_shim("kiro", "SessionStart", {"hook_event_name": "agentSpawn"}, base)
    check(start.returncode == 0 and "orchestrator" in start.stdout, f"kiro SessionStart lacks orchestrator: {start.stderr[-200:]}")
    check(not start.stdout.lstrip().startswith("{"), "kiro SessionStart printed JSON")

    cortex_block = run_shim("cortex", "PreToolUse", {"tool_name": "bash", "tool_input": rm_input}, base)
    blocked = cortex_block.returncode == 2 or '"block"' in cortex_block.stdout
    check(blocked, f"cortex rm -rf build not blocked: {cortex_block.returncode} {cortex_block.stdout[-200:]}")


def main() -> int:
    """Run every check."""
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    check_kiro(WORK)
    check_cortex(WORK)
    check_shim(WORK)
    shutil.rmtree(WORK, ignore_errors=True)
    print("check_port: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
