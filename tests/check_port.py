#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""Check bin/harness-port and port/shim.py: converted files, merge and uninstall, and the shim end to end.

Writes under __scratch__/. `install.sh` runs against a sandbox home and a local clone of HEAD. Set HARNESS_PORT_SHIM to run the shim checks against another copy of the shim. The install checks
for a broken hooks file and for a reinstall from another clone each run once on the real tool and once on a planted copy,
which they must fail.
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
PORT_SCRIPT = ROOT / "port" / "harness_port.py"
INSTALL_SH = ROOT / "install.sh"
SHIM = Path(os.environ.get("HARNESS_PORT_SHIM", ROOT / "port" / "shim.py"))
WORK = ROOT / "__scratch__" / "port-check"
FOREIGN_COMMAND = "echo foreign"
FRONTMATTER_NAME = re.compile(r"^name:\s*(.+?)\s*$", re.MULTILINE)
TOOLS_BLOCK = re.compile(r"^tools:\n((?:  - .+\n)+)", re.MULTILINE)
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


def check_texts(dest: Path, target: str) -> None:
    """Skill names match folders, no Claude-only text is left, agent files carry the right fields."""
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

    analyst = dest / "agents" / "harness-analyst"
    if target == "kiro":
        config = json.loads(analyst.with_suffix(".json").read_text())
        check(config["name"] == "harness-analyst", "kiro agent name")
        prompt_file = dest / "harness-prompts" / "harness-analyst.md"
        check(config["prompt"] == f"file://{prompt_file}", f"kiro agent prompt path {config['prompt']}")
        check(not list((dest / "agents").glob("*.md")), "kiro agents folder holds a .md file")
        check(config["tools"] == ["read", "shell"], f"kiro agent tags {config['tools']}")
        check("model" not in config, "kiro agent has a model")
        expected = f"skill://{dest / 'skills' / 'harness-report' / 'SKILL.md'}"
        check(
            expected in config["resources"],
            "kiro agent resources lack the report skill",
        )
        check(prompt_file.read_text().strip() != "", "kiro agent prompt file empty")
        return

    text = analyst.with_suffix(".md").read_text()
    check(get_cortex_tools(text) == ["read", "grep", "glob", "bash"], "cortex agent tools are not a YAML list")
    check("model:" not in text, "cortex agent has a model")
    for agent in (dest / "agents").glob("*.md"):
        tools = get_cortex_tools(agent.read_text())
        check(
            bool(tools) and tools == [tool.lower() for tool in tools],
            f"cortex tool ids not a lowercase list in {agent.name}",
        )


def get_cortex_tools(text: str) -> list[str]:
    """The ids of a Cortex agent's `tools:` YAML list, empty when it is not a block list."""
    found = TOOLS_BLOCK.search(text)
    if found is None:
        return []
    return [line.strip()[2:] for line in found.group(1).splitlines()]


def check_kiro_old_layout(base: Path) -> None:
    """An install over the old Kiro layout removes the `.md` prompts the port wrote and keeps a foreign one."""
    dest = base / "kiro-old"
    agents = dest / "agents"
    agents.mkdir(parents=True)
    old = ["agents/harness-analyst.md", "agents/harness-scout.md"]
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
    """The old Kiro hooks file name, read from the converter under test."""
    spec = importlib.util.spec_from_file_location("harness_port_under_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return str(module.LEGACY_KIRO_HOOKS)


def plant_file(path: Path, text: str) -> None:
    """Write a file, making its folder first."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def run_kiro_script(script: Path, dest: Path, *flags: str) -> None:
    """Run a converter script for Kiro into a destination and fail the run unless it exits 0."""
    done = subprocess.run(
        ["uv", "run", "--script", str(script), "--target", "kiro", "--dest", str(dest), *flags],
        capture_output=True,
        text=True,
        timeout=120,
    )
    check(done.returncode == 0, f"kiro {flags} exited {done.returncode}: {done.stderr[-300:]}")


def check_kiro_legacy_hooks(base: Path, script: Path) -> None:
    """Install and uninstall remove the old Kiro hooks file only when the port wrote it; a foreign file stays."""
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


def check_cortex(base: Path) -> None:
    """Cortex conversion, merge, rerun and uninstall."""
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
    check(
        any(g.get("matcher") == "bash|write|edit" for g in merged["hooks"]["PreToolUse"]),
        "cortex guard matcher",
    )
    run_port("cortex", dest, "--uninstall")
    check(
        json.loads((dest / "hooks.json").read_text()) == foreign,
        "uninstall did not leave exactly the foreign hook",
    )
    left = sorted(str(path.relative_to(dest)) for path in dest.rglob("*") if path.is_file())
    check(left == ["hooks.json"], f"cortex uninstall left {left}")


def run_shim(
    host: str, event: str, payload: dict, base: Path, hook: str = "", config: str = ""
) -> subprocess.CompletedProcess:
    """Run a harness hook through the shim with the owner's files out of reach."""
    home = base / "home"
    home.mkdir(parents=True, exist_ok=True)
    project = base / "project"
    project.mkdir(exist_ok=True)
    # Its own repository, so the walk to a git root stops here and not at this checkout.
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
    """A copy of the converter that stands in for another checkout, with a planted bug when `edits` are given."""
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
    """Run a converter script for Cortex into a destination and return the finished process."""
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
    """Why a broken or non-object hooks file was not refused cleanly before any write, or an empty string."""
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
    """Why a reinstall from another clone did not replace the old groups, or an empty string."""
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
    """A bad hooks file stops the install before any write; a reinstall from another clone does not double."""
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
    """The shim module, imported by path so a planted copy can stand in."""

    spec = importlib.util.spec_from_file_location("harness_shim", SHIM)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_shim(base: Path) -> None:
    """The shim end to end on both hosts."""
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

    cortex_block = run_shim("cortex", "PreToolUse", {"tool_name": "bash", "tool_input": rm_input}, base)
    blocked = cortex_block.returncode == 2 or '"block"' in cortex_block.stdout
    check(
        blocked,
        f"cortex rm -rf build not blocked: {cortex_block.returncode} {cortex_block.stdout[-200:]}",
    )


def run_install_sh(script: Path, home: Path, upstream: Path, *args: str) -> subprocess.CompletedProcess:
    """Run an install script with a sandbox home and a local repository standing in for GitHub."""
    environment = {
        **os.environ,
        "HOME": str(home),
        "HARNESS_HOME": str(home / "clone"),
        "HARNESS_REPO": str(upstream),
    }
    return subprocess.run(["sh", str(script), *args], capture_output=True, text=True, env=environment, timeout=180)


def hash_tree(folder: Path) -> list[tuple[str, str]]:
    """Every file under a folder with its content, sorted by path."""
    return sorted((str(path.relative_to(folder)), path.read_text()) for path in folder.rglob("*") if path.is_file())


def find_install_sh_fault(script: Path, base: Path) -> str:
    """Why the install script misbehaves (install, rerun, failed pull, uninstall, usage), or an empty string."""
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
    """install.sh installs, reruns unchanged, stops on a failed pull, uninstalls, and rejects a bad target."""
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
    """Run every check."""
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    (WORK.parent / ".gitignore").write_text("*\n")
    check_kiro(WORK)
    check_kiro_old_layout(WORK)
    check_kiro_legacy_hooks(WORK, PORT_SCRIPT)
    check_cortex(WORK)
    check_shim(WORK)
    check_install_guards(WORK)
    check_install_sh(WORK)
    shutil.rmtree(WORK, ignore_errors=True)
    print("check_port: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
