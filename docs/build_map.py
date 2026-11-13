#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///

from __future__ import annotations

import argparse
import ast
import builtins
import hashlib
import html
import importlib.util
import io
import json
import keyword
import re
import shutil
import subprocess
import sys
import tokenize
from collections.abc import Iterable
from pathlib import Path
from types import ModuleType
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = Path("docs") / "map.html.in"
PAGE = Path("docs") / "index.html"
BAND_TEMPLATE = Path("docs") / "band.html.in"
BAND_PAGE = Path("docs") / "band.html"
FLOW_TEMPLATE = Path("docs") / "flow.html.in"
FLOW_PAGE = Path("docs") / "flow.html"
PAGES = ((TEMPLATE, PAGE), (FLOW_TEMPLATE, FLOW_PAGE), (BAND_TEMPLATE, BAND_PAGE))
BAND_VIEW_BUILDER = Path("docs") / "band-host" / "build.ts"
BAND_VIEW_BUNDLE = Path("docs") / "band-view.js"
ASSETS = (Path("docs") / "style.css", Path("docs") / "script.js", Path("docs") / "site.js", Path("docs") / "flow.js")
SITE_PAGES = (
    ("home", "index.html", "Harness", "What the harness plugin for Claude Code does: its agents, skills and hooks, and how hard each rule binds.", ()),
    ("flow", "flow.html", "How it connects", "How the harness parts call each other: the main session, its agents, their skills and the hooks that check them.", ("flow.css",)),
    ("band", "band.html", "Band", "A live, simulated preview of the agent band: a mod that sits above the Claude Code prompt and shows limits, context, cost and every agent.", ("band.css",)),
)
SITE_REPO = "https://github.com/tfernd/harness"
THEME_SCRIPT = """  <script>
    try {
      const savedTheme = localStorage.getItem("harness-map-theme");
      const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      if (savedTheme === "dark" || (savedTheme === null && prefersDark)) document.documentElement.dataset.theme = "dark";
      const savedTarget = localStorage.getItem("harness-map-target");
      if (savedTarget === "cortex" || savedTarget === "kiro") document.documentElement.dataset.target = savedTarget;
    } catch (error) {
      console.warn("The saved theme or install target could not be read.", error);
    }
  </script>"""
FINGERPRINT_LENGTH = 10
DISPATCH_COMMAND = re.compile(r"hooks/dispatch\.py\"\s+(\w+)")
HOOK_COMMAND = re.compile(r"uv run --script \"[^\"]*hooks/([\w-]+\.py)\"(?:\s+(\S+))?")
SLOT = re.compile(r"\[\[@([a-z-]+)([^\]]*?)\]\]")
FACT = re.compile(r"\{\{(\w+)\}\}")
LIST_ITEM = re.compile(r"\s+- (.+)")
SENTENCE_END = re.compile(r"(?<=\.)\s+(?=[A-Z])")
SUMMARY_END = re.compile(r" - |: |\. ")
MAX_SUMMARY = 170
MIN_JOB = 20
MIN_CLAUSE = 40
SNIPPET = 60
SNIPPET_LEAD = 20
SINGLE_SLOTS = ("pyramid", "panels")
SKILL_MENTION = re.compile(r"harness:([a-z][a-z0-9-]*)")
CODE_SKILLS = ("code-python", "code-js", "code-html-css", "code-shell", "code-make", "code-yaml", "code-terraform", "code-sql", "git")
HOOK_WIRES = (
    ("context.py", "start text for all", "inject", ("main", "agents", "skill:tool-habits", "skill:orchestrator", "skill:report")),
    ("skill_gate.py", "language rules on edit", "inject", tuple(f"skill:{name}" for name in CODE_SKILLS)),
    ("guard.py", "refuses risky calls", "check", ("main", "agents")),
    ("commit_gate.py", "commit message form", "check", ("main", "skill:git")),
    ("report_gate.py", "report sections", "check", ("agents", "skill:report")),
    ("budget.py", "agent progress note", "inject", ("main",)),
    ("turn.py", "closing status", "check", ("main",)),
)
WIRE_KINDS = (
    ("spawn", "main session spawns an agent", True),
    ("preload", "agent preloads a skill", True),
    ("inject", "hook injects text", True),
    ("check", "hook checks or blocks", True),
    ("point", "skill points to a skill", False),
)
WIRE_WIDTH = 1120
WIRE_TOP = 56
WIRE_COLUMN_X = {"hook": 24, "agent": 440, "skill": 830}
WIRE_COLUMN_WIDTH = {"hook": 210, "agent": 220, "skill": 190}
WIRE_COLUMN_TITLE = {"hook": "Hooks", "agent": "Main session and agents", "skill": "Skills"}
WIRE_BIG_HEIGHT = 54
WIRE_BIG_PITCH = 78
WIRE_SKILL_HEIGHT = 24
WIRE_SKILL_PITCH = 30
WIRE_PORT_INSET = 7
WIRE_BOW_MIN = 36
WIRE_BOW_MAX = 100
WIRE_BOTTOM_MARGIN = 24
HEADING = re.compile(r"(#{1,6})\s+(.+?)\s*#*")
FENCE = re.compile(r"(`{3,}|~{3,})\s*([\w+-]*)\s*")
BULLET = re.compile(r"([-*+]|\d{1,9}[.)])\s+(.*)")
RULE = re.compile(r"([-*_])(?:\s*\1){2,}\s*")
TABLE_DIVIDER = re.compile(r"\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*")
CODE_SPAN = re.compile(r"(`+)(.+?)\1(?!`)")
LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
BOLD = re.compile(r"\*\*(.+?)\*\*")
ITALIC = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])|(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)")
HEADING_SHIFT = 2
PORT_STATES = {
    "runs": "runs",
    "partial": "partly ported",
    "advisory": "advisory, warns but blocks nothing",
    "off": "not ported",
}
TOOL_EVENTS = ("PreToolUse", "PostToolUse")
TARGETS = ("cortex", "kiro")
STATE_RANK = {"runs": 0, "partial": 1, "advisory": 2, "off": 3}
PORT_DEST = Path("port-dest")
INSTALL_COMMANDS = {
    "claude": "claude plugin marketplace add tfernd/harness; claude plugin marketplace update harness && claude plugin install harness@harness --scope user && claude plugin update harness@harness",
    "cortex": "cortex plugin update harness || cortex plugin install tfernd/harness",
    "kiro": "curl -fsSL https://raw.githubusercontent.com/tfernd/harness/main/install.sh | sh -s -- kiro",
    "band": "claude plugin marketplace add tfernd/harness; claude plugin marketplace update harness && claude plugin install harness-band@harness --scope user && claude plugin update harness-band@harness",
}
UNINSTALL_COMMANDS = {
    "claude-off": "claude plugin uninstall harness@harness && claude plugin marketplace remove harness",
    "cortex-off": "cortex plugin uninstall harness; curl -fsSL https://raw.githubusercontent.com/tfernd/harness/main/install.sh | sh -s -- cortex --uninstall",
    "band-off": "claude plugin uninstall harness-band@harness",
    "kiro-off": "curl -fsSL https://raw.githubusercontent.com/tfernd/harness/main/install.sh | sh -s -- kiro --uninstall; rm -rf ~/.local/share/harness",
}
SHELL_TOKEN = re.compile(r"""(?P<space>\s+)|(?P<comment>#.*)|(?P<string>'[^']*'|"(?:\\.|[^"\\])*")|(?P<operator>&&|\|\||[|;<>()])|(?P<word>[^\s'"|&;<>()]+|.)""")
SHELL_STARTERS = ("&&", "||", "|", ";", "(")
HEREDOC = re.compile(r"""<<-?\s*(['"]?)(\w+)\1""")
JSON_TOKEN = re.compile(r"""(?P<string>"(?:\\.|[^"\\])*")(?P<colon>\s*:)?|(?P<number>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|(?P<keyword>\b(?:true|false|null)\b)""")
PYTHON_STRINGS = {tokenize.STRING, tokenize.FSTRING_START, tokenize.FSTRING_MIDDLE, tokenize.FSTRING_END}
PYTHON_QUIET = {tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.COMMENT, tokenize.ENDMARKER}
BUILTIN_NAMES = frozenset(name for name in dir(builtins) if not name.startswith("_"))
LANGUAGES = {"python": "python", "py": "python", "bash": "shell", "sh": "shell", "shell": "shell", "json": "json"}


class Agent(NamedTuple):

    name: str
    model: str
    tools: tuple[str, ...]
    skills: tuple[str, ...]
    job: str
    use: str


class Skill(NamedTuple):

    job: str
    when: str


class Hook(NamedTuple):

    event: str
    matcher: str
    script: str
    argument: str


class Reach(NamedTuple):

    state: str
    missing: tuple[str, ...]


class Facts(NamedTuple):

    agents: tuple[Agent, ...]
    skills: dict[str, Skill]
    hooks: tuple[Hook, ...]
    ports: dict[str, dict[str, str]]
    reach: dict[str, dict[str, Reach]]
    values: dict[str, str]
    full: dict[str, str]
    skill_links: dict[str, tuple[str, ...]]


class Slot(NamedTuple):

    name: str
    arguments: tuple[str, ...]


class Kind(NamedTuple):

    name: str
    text: str
    members: tuple[str, ...]


class Level(NamedTuple):

    key: str
    name: str
    short: str
    text: str
    can: str


class Event(NamedTuple):

    key: str
    moment: str


class Rule(NamedTuple):

    text: str
    level: str
    script: str


class WireNode(NamedTuple):

    key: str
    column: str
    tone: str
    label: str
    sub: str
    x: int
    y: int
    width: int
    height: int


class WireEdge(NamedTuple):

    source: str
    target: str
    kind: str


class Layout(NamedTuple):

    facts: Facts
    level_hooks: dict[str, list[str]]


class Port(NamedTuple):

    key: str
    label: str


class PortNote(NamedTuple):

    script: str
    target: str
    state: str
    note: str
    phrase: str


AGENT_KINDS = (
    Kind("Thinkers", "Work out what to do; write no files.", ("planner",)),
    Kind("Finders", "Look things up and answer with sources.", ("scout", "researcher")),
    Kind("Doers", "Change the files their brief names.", ("worker", "designer")),
    Kind("Checkers", "Test someone else's work.", ("reviewer",)),
)
SKILL_KINDS = (
    Kind("Run the job", "Plan, brief, accept, set up.", ("orchestrator", "workflows", "init")),
    Kind("Think", "Settle facts and causes first.", ("evidence", "spec")),
    Kind(
        "Build",
        "Write code, commits and pages.",
        ("code-python", "code-js", "code-html-css", "code-shell", "code-terraform", "code-sql", "code-yaml", "code-make", "code", "git", "design"),
    ),
    Kind("Tools", "Run a command-line tool without breaking an account.", ("aws-cli", "snowflake-cli")),
    Kind("Check", "Judge work against its spec.", ("testing", "review")),
    Kind("Report", "Close a job; write hooks, skills and agents.", ("report", "authoring")),
    Kind("Habits", "Cheap tool calls, every session.", ("tool-habits",)),
)
HOOK_KINDS = (
    Kind("Guards", "Refuse a risky call before it runs.", ("guard.py", "commit_gate.py")),
    Kind("Gates", "Check what crosses a hand-off.", ("report_gate.py",)),
    Kind("Teachers", "Add a note when it helps.", ("context.py", "skill_gate.py", "budget.py")),
    Kind("Closers", "Hold the turn until it is recorded.", ("turn.py",)),
)
HOOK_JOBS = {
    "guard.py": "Refuses deletes, history rewrites, a sub-agent's git writes and wildcards the shell would get wrong; asks you before a package change, an AWS write, a credential read or a piped installer.",
    "commit_gate.py": "Refuses a commit message out of form or crediting an AI, and a commit that drops tests without saying why.",
    "budget.py": "Tells the main session what each agent is doing.",
    "report_gate.py": "Sends a report back when a required section is missing or out of order.",
    "context.py": "Starts every session and agent with the tool habits.",
    "skill_gate.py": "Hands an agent the rules for a kind of file before its first edit of one, and the commit rules before a commit.",
    "turn.py": "Holds the main session's turn until it ends with a closing status.",
}
LEVELS = (
    Level("stopped", "Stops the call", "never runs", "The call never runs; the agent is told which rule fired and what to do instead.", "stop the call"),
    Level("asks", "Asks you", "waits for your yes", "Claude Code pauses and asks you; your yes runs it.", "ask you first"),
    Level("sent-back", "Sent back", "report redone", "The report goes back to its agent, naming only the parts that are wrong, up to {send_backs} times.", "send the report back"),
    Level("turn", "Turn can't end", "until it is fixed", "The main session's turn does not end until it adds what is missing; it gets {max_blocks} tries.", "keep the turn open until it is fixed"),
    Level("reminder", "Reminds the model", "runs, with a note", "The call runs; one line of advice comes back with the result.", "remind the model"),
    Level("advice", "Advice", "read, not checked", "Text the model reads before a kind of work. Nothing checks it was followed; a reviewer catches what slips.", "give the model advice"),
    Level("written", "Written down", "your AGENTS.md", "Your project's own rules in AGENTS.md, written once by /harness:init; they bind as far as the model reads them.", "write the rule into AGENTS.md"),
)
BRACES = (
    ("hooks", "Hooks enforce", "the call waits"),
    ("reminder", "Hook notes", ""),
    ("model", "Model decides", "nothing checks"),
)
SKILL_LEVEL = "advice"
FILE_LEVEL = "written"
EVENTS = (
    Event("SessionStart", "at session start"),
    Event("UserPromptSubmit", "on your prompt"),
    Event("PreToolUse", "before"),
    Event("PostToolUse", "after"),
    Event("SubagentStart", "when an agent starts"),
    Event("SubagentStop", "when an agent stops"),
    Event("Stop", "when the turn ends"),
)
RULES = (
    Rule("Deleting files is refused, in the scratch folder too", "stopped", "guard.py"),
    Rule("Rewriting shared history is refused", "stopped", "guard.py"),
    Rule("A wildcard the shell would get wrong is refused", "stopped", "guard.py"),
    Rule("A commit message out of form, or crediting an AI, is refused", "stopped", "commit_gate.py"),
    Rule("A commit that leaves fewer tests without saying why is refused", "stopped", "commit_gate.py"),
    Rule("Adding or removing packages asks you first", "asks", "guard.py"),
    Rule("Reading a credential file or printing a secret asks you first", "asks", "guard.py"),
    Rule("Writing to an AWS account asks you first", "asks", "guard.py"),
    Rule("Piping a downloaded script into a shell asks you first", "asks", "guard.py"),
    Rule("A sub-agent's git or gh command that writes is refused", "stopped", "guard.py"),
    Rule("A report needs its parts and a verdict", "sent-back", "report_gate.py"),
    Rule("A long turn ends with a closing status", "turn", "turn.py"),
    Rule("A turn that ran agents names each one with its verdict", "reminder", "turn.py"),
    Rule("The rules for a kind of file arrive before its first edit", "reminder", "skill_gate.py"),
    Rule("The main session gets a note of what each agent is doing", "reminder", "budget.py"),
    Rule("A shell write outside the scratch folder gets a note", "reminder", "guard.py"),
    Rule("The tool habits go in front of every session and agent", "advice", "context.py"),
)
PORTS = (Port("claude", "Claude"), Port("cortex", "Cortex"), Port("kiro", "Kiro"))
PORT_NOTES = (
    PortNote("report_gate.py", "cortex", "advisory", "Cortex cannot block at SubagentStop", "the report gate blocks nothing (advisory)"),
    PortNote("guard.py", "kiro", "runs", 'an "ask" becomes a block', 'a guard "ask" becomes a block'),
    PortNote("guard.py", "cortex", "runs", 'an "ask" becomes a block', 'An "ask" becomes a block.'),
)




def read_frontmatter(path: Path, /) -> dict[str, str | list[str]]:

    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise ValueError(f"{path.name} opens with no frontmatter")

    fields: dict[str, str | list[str]] = {}
    key = ""
    for line in lines[1:]:
        if line == "---":
            return fields
        item = LIST_ITEM.fullmatch(line)
        if item:
            listed = fields.get(key)
            if not isinstance(listed, list):
                raise ValueError(f"{path.name}: a list item under no list key: {line!r}")
            listed.append(item.group(1).strip())
        elif line.strip():
            key, _, value = line.partition(":")
            key = key.strip()
            fields[key] = value.strip() or []

    raise ValueError(f"{path.name}: the frontmatter never closes")


def get_text(fields: dict[str, str | list[str]], key: str, path: Path, /) -> str:

    value = fields.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{path.name} has no `{key}:` line")

    return value


def get_items(fields: dict[str, str | list[str]], key: str, path: Path, /) -> list[str]:

    value = fields.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"{path.name}: `{key}:` should be a list")

    return value


def get_agents(root: Path, /) -> tuple[Agent, ...]:

    agents = []
    for path in sorted((root / "agents").glob("*.md")):
        fields = read_frontmatter(path)
        sentences = SENTENCE_END.split(get_text(fields, "description", path).strip())
        uses = [sentence for sentence in sentences if sentence.startswith("Use ")]
        agent = Agent(
            name=get_text(fields, "name", path),
            model=get_text(fields, "model", path),
            tools=tuple(tool.strip() for tool in get_text(fields, "tools", path).split(",")),
            skills=tuple(get_items(fields, "skills", path)),
            job=sentences[0],
            use=uses[0] if uses else "",
        )
        agents.append(agent)

    return tuple(agents)


def get_skill(description: str, /) -> Skill:

    sentences = [sentence.strip().rstrip(".") for sentence in SENTENCE_END.split(description.strip())]
    loads = [sentence for sentence in sentences if sentence.startswith("Load ")]
    others = [sentence for sentence in sentences if not sentence.startswith("Load ")]

    if others and (len(others[0]) >= MIN_JOB or not loads):
        clause = SUMMARY_END.split(others[0], maxsplit=1)[0]
        job = clause if len(clause) >= MIN_CLAUSE else others[0]
        when = ". ".join(loads)
    else:
        stripped = loads[0].removeprefix("Load ").removeprefix("to ")
        job = SUMMARY_END.split(stripped[:1].upper() + stripped[1:], maxsplit=1)[0]
        when = ". ".join(others)
    if len(job) > MAX_SUMMARY:
        job = job[:MAX_SUMMARY].rsplit(" ", 1)[0] + "…"

    return Skill(job, when + "." if when else "")


def get_skills(root: Path, /) -> dict[str, Skill]:

    skills = {}
    for path in sorted((root / "skills").glob("*/SKILL.md")):
        fields = read_frontmatter(path)
        skills[get_text(fields, "name", path)] = get_skill(get_text(fields, "description", path))

    return skills


def get_events(root: Path, /) -> dict[str, list[dict]]:

    events = json.loads((root / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    routes = get_constant(root / "hooks" / "dispatch.py", "ROUTES", dict)
    expanded: dict[str, list[dict]] = {}
    for event, groups in events.items():
        expanded[event] = []
        for group in groups:
            for command in group["hooks"]:
                match = DISPATCH_COMMAND.search(command["command"])
                if match is None:
                    expanded[event].append({**group, "hooks": [command]})
                    continue
                for matcher, script, argument in routes[match.group(1)]:
                    run = f'uv run --script "hooks/{script}"' + (f" {argument}" if argument else "")
                    expanded[event].append({"matcher": matcher or group.get("matcher", ""), "hooks": [{"type": "command", "command": run}]})

    return expanded


def get_hooks(root: Path, /) -> tuple[Hook, ...]:

    events = get_events(root)
    hooks = []
    for event, groups in events.items():
        for group in groups:
            for command in group["hooks"]:
                match = HOOK_COMMAND.search(command["command"])
                if match is None:
                    raise ValueError(f"a {event} hook runs no script under hooks/: {command['command']!r}")
                hooks.append(Hook(event, group.get("matcher", ""), match.group(1), match.group(2) or ""))

    return tuple(hooks)


def get_constant[T](path: Path, name: str, kind: type[T], /) -> T:

    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        match node:
            case ast.Assign(targets=[ast.Name(id=found)], value=value) | ast.AnnAssign(target=ast.Name(id=found), value=ast.expr() as value) if (
                found == name
            ):
                literal = ast.literal_eval(value)
                if not isinstance(literal, kind):
                    raise ValueError(f"{path.name}: {name} is a {type(literal).__name__}, not a {kind.__name__}")
                return literal

    raise ValueError(f"{path.name} assigns no {name} at its top level")


def import_path(path: Path, /) -> ModuleType:

    spec = importlib.util.spec_from_file_location(f"map_source_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"{path.name} cannot be imported")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))

    return module


def get_port_label(target: str, /) -> str:

    return next(item.label for item in PORTS if item.key == target)


def get_hook_reach(port: ModuleType, events: dict[str, list[dict]], script: str, target: str, /) -> Reach:

    marker = f"hooks/{script}"
    known = port.KIRO_MATCHER_IDS if target == "kiro" else port.CORTEX_TOOLS
    converted = 0
    missing: list[str] = []
    for event, event_groups in events.items():
        for group in event_groups:
            if not any(marker in command["command"] for command in group["hooks"]):
                continue
            plan = port.Plan()
            kiro_entries: list[dict] = []
            port.plan_hook_group(plan, target, event, group, kiro_entries)
            commands = [entry["action"]["command"] for entry in kiro_entries]
            commands.extend(hook["command"] for cortex_group in plan.cortex_hooks.get(event, []) for hook in cortex_group["hooks"])
            if not any(marker in command for command in commands):
                missing.extend(note.removeprefix("hook ") for note in plan.not_ported)
                continue
            converted += 1
            dropped = [name for name in group.get("matcher", "").split("|") if name and name not in known]
            if dropped:
                missing.append(f"{event}: no {get_port_label(target)} id for {', '.join(dropped)}")
    state = "off" if not converted else "partial" if missing else "runs"
    for note in PORT_NOTES:
        if note.script == script and note.target == target:
            missing.append(note.note)
            state = note.state if STATE_RANK[note.state] > STATE_RANK[state] else max(state, "partial", key=STATE_RANK.__getitem__)

    return Reach(state, tuple(dict.fromkeys(missing)))


def get_agent_reach(port: ModuleType, root: Path, name: str, target: str, /) -> Reach:

    plan = port.Plan()
    port.plan_agent(plan, PORT_DEST, target, root / "agents" / f"{name}.md", {})
    missing = tuple(note.removeprefix(f"agent harness-{name}: ") for note in plan.not_ported)

    return Reach("off" if not plan.files else "partial" if missing else "runs", missing)


def get_reach(port: ModuleType, root: Path, agents: tuple[Agent, ...], skills: Iterable[str], scripts: Iterable[str], /) -> dict[str, dict[str, Reach]]:

    events = get_events(root)
    plan = port.Plan()
    port.plan_skills(plan, PORT_DEST)
    written = {path.parent.name for path in plan.files if path.name == "SKILL.md"}
    reach = {f"agent:{agent.name}": {target: get_agent_reach(port, root, agent.name, target) for target in TARGETS} for agent in agents}
    for name in skills:
        reach[f"skill:{name}"] = dict.fromkeys(TARGETS, Reach("runs" if f"harness-{name}" in written else "off", ()))
    for script in scripts:
        reach[f"hook:{script}"] = {target: get_hook_reach(port, events, script, target) for target in TARGETS}

    return reach


def get_fingerprint(path: Path, /) -> str:

    return hashlib.sha256(path.read_bytes()).hexdigest()[:FINGERPRINT_LENGTH]


def get_skill_links(root: Path, skills: dict[str, Skill], /) -> dict[str, tuple[str, ...]]:

    links = {}
    for name in skills:
        body = (root / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        mentioned = {mention for mention in SKILL_MENTION.findall(body) if mention in skills and mention != name}
        links[name] = tuple(sorted(mentioned))

    return links


def get_facts(root: Path, /) -> Facts:

    hooks_folder = root / "hooks"
    turn = hooks_folder / "turn.py"
    report_gate = hooks_folder / "report_gate.py"
    agents = get_agents(root)
    skills = get_skills(root)
    hooks = get_hooks(root)
    scripts = list(dict.fromkeys(hook.script for hook in hooks))
    port = import_path(root / "port" / "harness_port.py")
    reach = get_reach(port, root, agents, skills, scripts)

    values = {
        "agents": len(agents),
        "skills": len(skills),
        "hooks": len(scripts),
        "send_backs": get_constant(report_gate, "MAX_SEND_BACKS", int),
        "max_blocks": get_constant(turn, "MAX_BLOCKS", int),
        "min_calls": get_constant(turn, "MIN_CALLS", int),
        "headings": ", ".join(get_constant(turn, "HEADINGS", tuple)),
        "style_hash": get_fingerprint(root / ASSETS[0]),
        "script_hash": get_fingerprint(root / ASSETS[1]),
        "site_hash": get_fingerprint(root / ASSETS[2]),
        "flow_hash": get_fingerprint(root / ASSETS[3]),
    }

    return Facts(
        agents,
        skills,
        hooks,
        {script: {"claude": "runs", **{target: reach[f"hook:{script}"][target].state for target in TARGETS}} for script in scripts},
        reach,
        {key: str(value) for key, value in values.items()},
        get_full_texts(root, agents, skills, scripts),
        get_skill_links(root, skills),
    )




def make_inline(text: str, /) -> str:

    parts = []
    last = 0
    for span in CODE_SPAN.finditer(text):
        parts.append(make_emphasis(text[last : span.start()]))
        parts.append(f"<code>{html.escape(span.group(2).strip())}</code>")
        last = span.end()
    parts.append(make_emphasis(text[last:]))

    return "".join(parts)


def make_emphasis(text: str, /) -> str:

    def link(match: re.Match[str]) -> str:
        words, target = html.escape(match.group(1)), match.group(2)
        if not target.startswith(("http://", "https://")):
            return words
        return f'<a href="{html.escape(target)}" rel="noopener">{words}</a>'

    pieces = []
    last = 0
    for match in LINK.finditer(text):
        pieces.append(make_marks(text[last : match.start()]))
        pieces.append(link(match))
        last = match.end()
    pieces.append(make_marks(text[last:]))

    return "".join(pieces)


def make_marks(text: str, /) -> str:

    escaped = html.escape(text)
    bold = BOLD.sub(r"<strong>\1</strong>", escaped)

    return ITALIC.sub(lambda match: f"<em>{match.group(1) or match.group(2)}</em>", bold)


def make_token(kind: str, value: str, /) -> str:

    escaped = html.escape(value, quote=False)

    return f'<span class="tok-{kind}">{escaped}</span>' if kind and value else escaped


def make_shell(text: str, /) -> str:

    lines = []
    continued = False
    heredoc_end = ""
    for line in text.split("\n"):
        if heredoc_end:
            lines.append(html.escape(line, quote=False))
            heredoc_end = "" if line.strip() == heredoc_end else heredoc_end
            continue
        at_command = not continued
        parts = []
        for match in SHELL_TOKEN.finditer(line):
            kind, value = match.lastgroup or "", match.group()
            if kind == "space":
                parts.append(value)
                continue
            if kind == "word":
                kind = "command" if at_command and "=" not in value else "flag" if value.startswith("-") else ""
                at_command = at_command and "=" in value
            elif kind == "operator":
                at_command = value in SHELL_STARTERS
            else:
                at_command = False
            parts.append(make_token(kind, value))
        continued = line.rstrip().endswith("\\")
        heredoc = HEREDOC.search(line)
        heredoc_end = heredoc.group(2) if heredoc else ""
        lines.append("".join(parts))

    return "\n".join(lines)


def make_json(text: str, /) -> str:

    parts = []
    last = 0
    for match in JSON_TOKEN.finditer(text):
        parts.append(html.escape(text[last : match.start()], quote=False))
        if match.group("string") is not None:
            colon = match.group("colon") or ""
            parts.append(make_token("key" if colon else "string", match.group("string")) + html.escape(colon, quote=False))
        else:
            kind = match.lastgroup or ""
            parts.append(make_token(kind, match.group()))
        last = match.end()
    parts.append(html.escape(text[last:], quote=False))

    return "".join(parts)


def get_python_kind(token: tokenize.TokenInfo, previous: tokenize.TokenInfo | None, /) -> str:

    if token.type in PYTHON_STRINGS:
        return "string"
    if token.type == tokenize.NUMBER:
        return "number"
    if token.type == tokenize.COMMENT:
        return "comment"
    if token.type != tokenize.NAME:
        return ""
    if keyword.iskeyword(token.string):
        return "keyword"
    after_dot = previous is not None and previous.string == "."
    after_definition = previous is not None and previous.string in {"def", "class"}

    return "builtin" if token.string in BUILTIN_NAMES and not after_dot and not after_definition else ""


def make_python(text: str, /) -> str:

    starts = [0]
    for line in text.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError):
        return html.escape(text, quote=False)
    parts = []
    last = 0
    previous = None
    in_decorator = False
    for token in tokens:
        start = starts[min(token.start[0], len(starts)) - 1] + token.start[1]
        end = starts[min(token.end[0], len(starts)) - 1] + token.end[1]
        if start < last or end <= start:
            continue
        if token.string == "@" and not token.line[: token.start[1]].strip():
            in_decorator = True
        elif in_decorator and not (token.type == tokenize.NAME or token.string == "."):
            in_decorator = False
        kind = "decorator" if in_decorator else get_python_kind(token, previous)
        parts.append(html.escape(text[last:start], quote=False))
        parts.append(make_token(kind, text[start:end]))
        last = end
        if token.type not in PYTHON_QUIET:
            previous = token
    parts.append(html.escape(text[last:], quote=False))

    return "".join(parts)


def make_code(text: str, language: str, /) -> str:

    match LANGUAGES.get(language.lower(), ""):
        case "python":
            return make_python(text)
        case "shell":
            return make_shell(text)
        case "json":
            return make_json(text)
        case _:
            return html.escape(text, quote=False)


def make_code_block(lines: Iterable[str], language: str, /) -> str:

    label = f' data-language="{html.escape(language)}"' if language else ""

    return f'<pre class="full-code"{label} tabindex="0"><code>{make_code(chr(10).join(lines), language)}</code></pre>'


def split_cells(line: str, /) -> list[str]:

    cells = []
    current = []
    in_code = False
    index = 0
    stripped = line.strip().removeprefix("|")
    while index < len(stripped):
        char = stripped[index]
        if char == "\\" and stripped[index + 1 : index + 2] == "|":
            current.append("|")
            index += 1
        elif char == "`":
            in_code = not in_code
            current.append(char)
        elif char == "|" and not in_code:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    if current or not stripped.endswith("|"):
        cells.append("".join(current).strip())

    return cells


def make_table(rows: list[str], /) -> str:

    head, *body = (split_cells(row) for row in (rows[0], *rows[2:]))
    width = len(head)
    header = "".join(f"<th>{make_inline(cell)}</th>" for cell in head)
    lines = []
    for cells in body:
        padded = (cells + [""] * width)[:width]
        lines.append("<tr>" + "".join(f"<td>{make_inline(cell)}</td>" for cell in padded) + "</tr>")

    return f'<div class="full-table" tabindex="0"><table><thead><tr>{header}</tr></thead><tbody>{"".join(lines)}</tbody></table></div>'


def is_block_start(line: str, next_line: str, /) -> bool:

    return bool(
        HEADING.fullmatch(line)
        or FENCE.match(line)
        or BULLET.match(line.lstrip()) and len(line) - len(line.lstrip()) < 4
        or RULE.fullmatch(line)
        or line.startswith(">")
        or "|" in line and TABLE_DIVIDER.fullmatch(next_line) and "-" in next_line
    )


def make_list(lines: list[str], start: int, /) -> tuple[str, int]:

    indent = len(lines[start]) - len(lines[start].lstrip())
    first = BULLET.match(lines[start].lstrip())
    assert first is not None
    ordered = first.group(1)[0].isdigit()
    items = []
    index = start
    while index < len(lines):
        match = BULLET.match(lines[index].lstrip())
        line_indent = len(lines[index]) - len(lines[index].lstrip())
        if match is None or line_indent != indent or match.group(1)[0].isdigit() != ordered:
            break
        content_indent = line_indent + len(lines[index].lstrip()) - len(match.group(2)) if match.group(2) else line_indent + 2
        body = [match.group(2)]
        index += 1
        while index < len(lines):
            line = lines[index]
            if not line.strip():
                ahead = next((later for later in lines[index + 1 :] if later.strip()), "")
                if ahead and len(ahead) - len(ahead.lstrip()) >= content_indent:
                    body.append("")
                    index += 1
                    continue
                break
            line_indent_here = len(line) - len(line.lstrip())
            if line_indent_here >= content_indent:
                body.append(line[content_indent:])
            elif BULLET.match(line.lstrip()) and line_indent_here <= indent:
                break
            elif body[-1] and not is_block_start(line, ""):
                body.append(line.strip())
            else:
                break
            index += 1
        ahead = next((later for later in lines[index:] if later.strip()), "")
        while index < len(lines) and not lines[index].strip() and BULLET.match(ahead.lstrip()) and len(ahead) - len(ahead.lstrip()) == indent:
            index += 1
        inner = make_blocks(body)
        if inner.startswith("<p>") and inner.count("<p>") == 1 and inner.endswith("</p>"):
            inner = inner[3:-4]
        items.append(f"<li>{inner}</li>")
    tag = "ol" if ordered else "ul"

    return f"<{tag}>{''.join(items)}</{tag}>", index


def make_blocks(lines: list[str], /) -> str:

    out = []
    index = 0
    while index < len(lines):
        line = lines[index]
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        stripped = line.strip()
        fence = FENCE.fullmatch(stripped)
        heading = HEADING.fullmatch(line)
        if not stripped:
            index += 1
        elif fence:
            mark, language = fence.group(1), fence.group(2)
            body = []
            index += 1
            while index < len(lines) and not (lines[index].strip().startswith(mark) and set(lines[index].strip()) <= set(mark[0])):
                body.append(lines[index])
                index += 1
            index += 1
            out.append(make_code_block(body, language))
        elif heading:
            hashes, text = heading.groups()
            level = min(len(hashes) + HEADING_SHIFT, 6)
            out.append(f"<h{level}>{make_inline(text)}</h{level}>")
            index += 1
        elif RULE.fullmatch(stripped) and not BULLET.match(stripped):
            out.append("<hr>")
            index += 1
        elif "|" in line and TABLE_DIVIDER.fullmatch(next_line) and "-" in next_line:
            rows = [line, next_line]
            index += 2
            while index < len(lines) and lines[index].strip() and "|" in lines[index]:
                rows.append(lines[index])
                index += 1
            out.append(make_table(rows))
        elif BULLET.match(line.lstrip()) and len(line) - len(line.lstrip()) < 4:
            markup, index = make_list(lines, index)
            out.append(markup)
        elif stripped.startswith(">"):
            quoted = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quoted.append(lines[index].strip().removeprefix(">").removeprefix(" "))
                index += 1
            out.append(f"<blockquote>{make_blocks(quoted)}</blockquote>")
        else:
            paragraph = [stripped]
            index += 1
            while index < len(lines) and lines[index].strip() and not is_block_start(lines[index], lines[index + 1] if index + 1 < len(lines) else ""):
                paragraph.append(lines[index].strip())
                index += 1
            out.append(f"<p>{make_inline(' '.join(paragraph))}</p>")

    return "".join(out)


def make_markdown(text: str, /) -> str:

    lines = text.splitlines()
    if lines and lines[0] == "---":
        end = next((number for number, line in enumerate(lines[1:], start=1) if line == "---"), None)
        if end is not None:
            lines = lines[end + 1 :]

    return make_blocks(lines)


def get_full_texts(root: Path, agents: tuple[Agent, ...], skills: dict[str, Skill], scripts: Iterable[str], /) -> dict[str, str]:

    full = {}
    for agent in agents:
        full[f"agent:{agent.name}"] = make_markdown((root / "agents" / f"{agent.name}.md").read_text(encoding="utf-8"))
    for name in skills:
        full[f"skill:{name}"] = make_markdown((root / "skills" / name / "SKILL.md").read_text(encoding="utf-8"))
    for script in scripts:
        source = (root / "hooks" / script).read_text(encoding="utf-8")
        full[f"hook:{script}"] = make_code_block(source.splitlines(), "python")

    return full




def check_kinds(kinds: tuple[Kind, ...], names: Iterable[str], where: str, /) -> None:

    members = [member for kind in kinds for member in kind.members]
    real = list(names)
    placeless = [name for name in real if name not in members]
    if placeless:
        raise ValueError(f"{where.format(placeless[0])} has no band: add it to a kind in docs/build_map.py")
    unknown = [member for member in members if member not in real]
    if unknown:
        raise ValueError(f"a kind in docs/build_map.py names {unknown[0]!r}, which the repository does not have")
    if len(set(members)) != len(members):
        raise ValueError(f"a kind in docs/build_map.py names {where.format('a part')} twice")


def check_places(facts: Facts, /) -> None:

    check_kinds(AGENT_KINDS, (agent.name for agent in facts.agents), "agents/{}.md")
    check_kinds(SKILL_KINDS, facts.skills, "skills/{}")
    check_kinds(HOOK_KINDS, facts.ports, "hooks/{}")
    jobless = [script for script in facts.ports if script not in HOOK_JOBS]
    if jobless:
        raise ValueError(f"hooks/{jobless[0]} has no plain job in HOOK_JOBS in docs/build_map.py")
    placed = {event.key for event in EVENTS}
    unplaced = [hook.event for hook in facts.hooks if hook.event not in placed]
    if unplaced:
        raise ValueError(f"hooks/hooks.json runs a hook at {unplaced[0]}, which EVENTS in docs/build_map.py does not place")


def get_level_hooks(hooks: tuple[Hook, ...], /) -> dict[str, list[str]]:

    keys = [level.key for level in LEVELS]
    scripts = {hook.script for hook in hooks}
    for rule in RULES:
        if rule.level not in keys:
            raise ValueError(f"RULES in docs/build_map.py puts {rule.text!r} at {rule.level!r}, which LEVELS does not have")
        if rule.script not in scripts:
            raise ValueError(f"RULES in docs/build_map.py names hooks/{rule.script}, which hooks/hooks.json does not run")
    ruled = {rule.script for rule in RULES}
    unruled = [hook.script for hook in hooks if hook.script not in ruled]
    if unruled:
        raise ValueError(f"hooks/{unruled[0]} has no rule in RULES in docs/build_map.py")

    return {key: list(dict.fromkeys(rule.script for rule in RULES if rule.level == key)) for key in keys}


def check_port_notes(root: Path, /) -> None:

    readme_lines = (root / "README.md").read_text(encoding="utf-8").splitlines()
    for note in PORT_NOTES:
        found = [number for number, line in enumerate(readme_lines, start=1) if note.phrase in line]
        if len(found) != 1:
            raise ValueError(f"README.md must hold the phrase {note.phrase!r} on one line, found it on {found}")




def get_tip_id(panel: str, name: str, /) -> str:

    return f"tip-{panel}-{re.sub(r'[^a-z0-9-]', '-', name)}"


def get_hook_levels(layout: Layout, script: str, /) -> tuple[Level, ...]:

    return tuple(level for level in LEVELS if script in layout.level_hooks[level.key])


def get_access(tools: tuple[str, ...], /) -> str:

    access = "edits files" if {"Edit", "Write"} & set(tools) else "read-only"

    return access + ", web" if {"WebFetch", "WebSearch"} & set(tools) else access


def make_row(icon: str, term: str, value: str, /, *, is_markup: bool = False) -> str:

    if not value:
        return ""
    shown = value if is_markup else html.escape(value)
    icon_markup = f'<svg class="icon" width="14" height="14" aria-hidden="true"><use href="#i-{icon}"/></svg>'

    return f"<dt>{icon_markup}{html.escape(term)}</dt><dd>{shown}</dd>"


def get_reach_text(reach: Reach, target: str, /) -> str:

    head = "Not ported" if reach.state == "off" else "Partly ported"
    missing = f": {'; '.join(reach.missing)}" if reach.missing else ""

    return f"{head} to {get_port_label(target)}{missing}."


def make_reach(reach: dict[str, Reach], /) -> tuple[str, str, str]:

    gaps = [(target, reach[target]) for target in TARGETS if reach[target].state != "runs"]
    attributes = "".join(f' data-port-{target}="{"off" if gap.state == "off" else "partial"}"' for target, gap in gaps)
    notes = "".join(
        f'<span class="visually-hidden chip-port is-{target}">, {"not" if gap.state == "off" else "partly"} ported to {get_port_label(target)}</span>' for target, gap in gaps
    )
    rows = "".join(
        f'<div class="tip-port is-{target}">{make_row("ports", f"On {get_port_label(target)}", get_reach_text(gap, target))}</div>' for target, gap in gaps
    )

    return attributes, notes, rows


def make_chip(panel: str, name: str, job: str, rows: Iterable[str], full: str, reach: dict[str, Reach], /, *, levels: tuple[Level, ...] = ()) -> str:

    tip_id = get_tip_id(panel, name)
    escaped = html.escape(name)
    keys = " ".join(level.key for level in levels)
    data_levels = f' data-levels="{keys}"' if keys else ""
    port_attributes, port_notes, port_rows = make_reach(reach)
    rows = (*rows, port_rows)

    return (
        f'<li class="chip-item"><button type="button" class="chip" data-item="{panel}:{escaped}"{data_levels}{port_attributes} aria-describedby="{tip_id}">'
        f"{escaped}{port_notes}</button>"
        f'<div class="tip kind-{panel}" id="{tip_id}" role="group" aria-label="{escaped}" hidden>'
        f'<p class="tip-strip"><span class="tip-kind">{panel}</span><span class="tip-name">{escaped}</span>'
        f'<button type="button" class="tip-switch" data-full="{tip_id}-full" aria-expanded="false" aria-controls="{tip_id}-view">Full text</button></p>'
        f'<div class="tip-body"><p class="tip-job">{html.escape(job)}</p><dl class="tip-grid">{"".join(rows)}</dl></div>'
        f'<div class="tip-view" id="{tip_id}-view" role="region" aria-label="Full text of {escaped}" tabindex="0" hidden></div></div>'
        f'<template id="{tip_id}-full">{full}</template></li>'
    )


def make_agent_chip(agent: Agent, facts: Facts, /) -> str:

    rows = (
        make_row("model", "Model", agent.model),
        make_row("tools", "Tools", get_access(agent.tools)),
        make_row("load", "Preloads", ", ".join(agent.skills)),
        make_row("when", "Use", agent.use),
    )

    return make_chip("agent", agent.name, agent.job, rows, facts.full[f"agent:{agent.name}"], facts.reach[f"agent:{agent.name}"])


def make_skill_chip(name: str, layout: Layout, /) -> str:

    skill = layout.facts.skills[name]
    preloaders = [agent.name for agent in layout.facts.agents if name in agent.skills]
    if preloaders and len(preloaders) == len(layout.facts.agents):
        loaded = "preloaded by every role"
    elif preloaders:
        loaded = f"preloaded by {', '.join(preloaders)}"
    else:
        loaded = "loaded when the work needs it"
    rows = (make_row("kind", "Kind", "advice"), make_row("load", "Loaded", loaded), make_row("when", "Load", skill.when))
    levels = tuple(level for level in LEVELS if level.key == SKILL_LEVEL)

    return make_chip("skill", name, skill.job, rows, layout.facts.full[f"skill:{name}"], layout.facts.reach[f"skill:{name}"], levels=levels)


def make_ports(states: dict[str, str], /) -> str:

    badges = "".join(f'<span class="port" data-state="{states[port.key]}">{port.label} {PORT_STATES[states[port.key]].split(",")[0]}</span>' for port in PORTS)

    return f'<span class="ports">{badges}</span>'


def get_moments(script: str, hooks: tuple[Hook, ...], /) -> str:

    moments: list[str] = []
    for hook in hooks:
        if hook.script != script:
            continue
        event = next(event for event in EVENTS if event.key == hook.event)
        moment = f"{event.moment} {', '.join(hook.matcher.split('|')) or 'every tool'}" if hook.event in TOOL_EVENTS else event.moment
        if moment not in moments:
            moments.append(moment)

    return "; ".join(moments)


def get_enforcement_sentence(levels: tuple[Level, ...], /) -> str:

    phrases = [level.can for level in LEVELS if level in levels]
    if not phrases:
        return ""
    if len(phrases) == 1:
        return f"Can {phrases[0]}."
    joiner = ", or " if len(phrases) > 2 else " or "

    return f"Can {', '.join(phrases[:-1])}{joiner}{phrases[-1]}."


def make_meter(levels: tuple[Level, ...], /) -> str:

    keys = {level.key for level in levels}
    segments = "".join(
        f'<span class="meter-seg is-{level.key} is-on"></span>' if level.key in keys else '<span class="meter-seg"></span>'
        for level in LEVELS
        if level.key not in {SKILL_LEVEL, FILE_LEVEL}
    )
    sentence = get_enforcement_sentence(levels)

    return f'<span class="meter" aria-hidden="true">{segments}</span><span class="meter-sentence">{html.escape(sentence)}</span>'


def make_hook_chip(script: str, layout: Layout, /) -> str:

    levels = get_hook_levels(layout, script)
    rows = (
        make_row("events", "Runs", get_moments(script, layout.facts.hooks)),
        make_row("levels", "Enforcement", make_meter(levels), is_markup=True),
        make_row("ports", "Ported", make_ports(layout.facts.ports[script]), is_markup=True),
    )

    return make_chip("hook", script, HOOK_JOBS[script], rows, layout.facts.full[f"hook:{script}"], layout.facts.reach[f"hook:{script}"], levels=levels)


def make_panel(panel: str, title: str, kicker: str, bands: Iterable[tuple[Kind, list[str]]], /) -> str:

    rows = []
    count = 0
    for kind, chips in bands:
        count += len(chips)
        rows.append(
            f'<div class="band"><div class="band-label"><h4 class="band-name">{html.escape(kind.name)}</h4>'
            f'<p class="band-text">{html.escape(kind.text)}</p></div>\n<ul class="chips">\n' + "\n".join(chips) + "\n</ul></div>"
        )

    return (
        f'<section class="panel is-{panel}s" aria-labelledby="panel-{panel}s-title">\n'
        f'<div class="panel-head"><h3 class="panel-title" id="panel-{panel}s-title">{title}</h3>'
        f'<span class="panel-count">{count}</span><p class="panel-kicker">{kicker}</p></div>\n'
        f'<div class="bands">\n' + "\n".join(rows) + "\n</div>\n</section>"
    )


def make_panels(layout: Layout, /) -> str:

    facts = layout.facts
    by_name = {agent.name: agent for agent in facts.agents}
    agents = [(kind, [make_agent_chip(by_name[name], facts) for name in kind.members]) for kind in AGENT_KINDS]
    skills = [(kind, [make_skill_chip(name, layout) for name in kind.members]) for kind in SKILL_KINDS]
    hooks = [(kind, [make_hook_chip(script, layout) for script in kind.members]) for kind in HOOK_KINDS]

    return "\n".join(
        (
            make_panel("agent", "Agents", "Separate sessions, one role each, that the main session hires for a job.", agents),
            make_panel("skill", "Skills", "Rule sheets a model reads before a kind of work: advice, not enforced.", skills),
            make_panel("hook", "Hooks", "Programs Claude Code runs at fixed moments; the model cannot argue with them.", hooks),
        )
    )


def get_lit(level: Level, layout: Layout, /) -> tuple[int, str]:

    scripts = layout.level_hooks[level.key]
    names = ", ".join(scripts)
    if level.key == FILE_LEVEL:
        return 1, "Lights nothing on the right: AGENTS.md is your project's own file."
    if level.key == SKILL_LEVEL:
        num_skills = len(layout.facts.skills)
        return num_skills + len(scripts), f"Lights all {num_skills} skills" + (f" and {names}." if scripts else ".")

    return len(scripts), f"Lights {len(scripts)} hook{'' if len(scripts) == 1 else 's'}: {names}."


def make_pyramid(layout: Layout, /) -> str:

    steps = []
    notes = ['<p class="level-note" data-level-note="none">Point at a level to light its parts on the right; click to keep it lit.</p>']
    for level in LEVELS:
        count, lit = get_lit(level, layout)
        text = level.text.format_map(layout.facts.values)
        steps.append(
            f'<li class="pyramid-step"><button type="button" class="level is-{level.key}" data-level="{level.key}" aria-pressed="false" '
            f'aria-describedby="level-note-{level.key}"><span class="level-text"><span class="level-name">{html.escape(level.name)}</span>'
            f'<span class="level-short">{html.escape(level.short)}</span></span><span class="level-count">{count}</span></button></li>'
        )
        notes.append(
            f'<p class="level-note" id="level-note-{level.key}" data-level-note="{level.key}" hidden>'
            f'<strong class="level-note-name">{html.escape(level.name)}.</strong> {html.escape(text)} '
            f'<span class="level-note-lit">{html.escape(lit)}</span></p>'
        )
    braces = "\n".join(
        f'<p class="brace brace-{kind}"><span class="brace-title">{html.escape(title)}</span>'
        + (f'<span class="brace-aside">{html.escape(note)}</span>' if note else "")
        + "</p>"
        for kind, title, note in BRACES
    )

    return (
        '<div class="pyramid-split">\n<ol class="pyramid" aria-label="Levels, hardest first">\n'
        + "\n".join(steps)
        + "\n</ol>\n"
        + braces
        + '\n</div>\n<div class="level-notes">\n'
        + "\n".join(notes)
        + "\n</div>"
    )


def get_wire_nodes(facts: Facts, /) -> dict[str, WireNode]:

    skill_names = sorted(facts.skills)
    skills_height = len(skill_names) * WIRE_SKILL_PITCH
    big_offset = max(0, (skills_height - len(HOOK_WIRES) * WIRE_BIG_PITCH) // 2)
    nodes = {}
    for index, (script, sub, _, _) in enumerate(HOOK_WIRES):
        nodes[f"hook:{script}"] = WireNode(f"hook:{script}", "hook", "hook", script, sub, WIRE_COLUMN_X["hook"], WIRE_TOP + big_offset + index * WIRE_BIG_PITCH, WIRE_COLUMN_WIDTH["hook"], WIRE_BIG_HEIGHT)
    actors = [("main", "main", "the orchestrator session")] + [(agent.name, "agent", agent.model) for agent in facts.agents]
    for index, (name, tone, sub) in enumerate(actors):
        nodes[f"agent:{name}"] = WireNode(f"agent:{name}", "agent", tone, name, sub, WIRE_COLUMN_X["agent"], WIRE_TOP + big_offset + index * WIRE_BIG_PITCH, WIRE_COLUMN_WIDTH["agent"], WIRE_BIG_HEIGHT)
    for index, name in enumerate(skill_names):
        nodes[f"skill:{name}"] = WireNode(f"skill:{name}", "skill", "skill", name, "", WIRE_COLUMN_X["skill"], WIRE_TOP + index * WIRE_SKILL_PITCH, WIRE_COLUMN_WIDTH["skill"], WIRE_SKILL_HEIGHT)

    return nodes


def get_wire_targets(target: str, facts: Facts, /) -> list[str]:

    if target == "agents":
        return [f"agent:{agent.name}" for agent in facts.agents]
    if target == "main":
        return ["agent:main"]

    return [target]


def get_wire_edges(facts: Facts, nodes: dict[str, WireNode], /) -> list[WireEdge]:

    edges = [WireEdge("agent:main", f"agent:{agent.name}", "spawn") for agent in facts.agents]
    edges += [WireEdge(f"agent:{agent.name}", f"skill:{skill}", "preload") for agent in facts.agents for skill in agent.skills]
    scripts = {hook.script for hook in facts.hooks}
    for script, _, kind, targets in HOOK_WIRES:
        if script not in scripts:
            raise ValueError(f"the diagram names a hook that does not exist: {script}")
        edges += [WireEdge(f"hook:{script}", key, kind) for target in targets for key in get_wire_targets(target, facts)]
    edges += [WireEdge(f"skill:{name}", f"skill:{linked}", "point") for name, linked_names in facts.skill_links.items() for linked in linked_names]
    unknown = sorted({key for edge in edges for key in (edge.source, edge.target) if key not in nodes})
    if unknown:
        raise ValueError(f"the diagram names a part that does not exist: {', '.join(unknown)}")

    return edges


def get_wire_sides(edge: WireEdge, nodes: dict[str, WireNode], /) -> tuple[int, int]:

    source, target = nodes[edge.source], nodes[edge.target]
    if source.column == target.column:
        return 1, 1
    order = ("hook", "agent", "skill")
    is_forward = order.index(source.column) < order.index(target.column)

    return (1, -1) if is_forward else (-1, 1)


def get_wire_ports(edges: list[WireEdge], nodes: dict[str, WireNode], /) -> dict[tuple[int, str], float]:

    waiting: dict[tuple[str, int], list[tuple[float, int, str]]] = {}
    for index, edge in enumerate(edges):
        source_side, target_side = get_wire_sides(edge, nodes)
        source, target = nodes[edge.source], nodes[edge.target]
        waiting.setdefault((edge.source, source_side), []).append((target.y + target.height / 2, index, "source"))
        waiting.setdefault((edge.target, target_side), []).append((source.y + source.height / 2, index, "target"))
    ports = {}
    for (key, _), entries in waiting.items():
        node = nodes[key]
        span = node.height - 2 * WIRE_PORT_INSET
        for position, (_, index, role) in enumerate(sorted(entries)):
            ports[(index, role)] = node.y + WIRE_PORT_INSET + span * (position + 0.5) / len(entries)

    return ports


def make_wire_path(edge: WireEdge, index: int, nodes: dict[str, WireNode], ports: dict[tuple[int, str], float], /) -> str:

    source, target = nodes[edge.source], nodes[edge.target]
    source_side, target_side = get_wire_sides(edge, nodes)
    start_x = source.x + (source.width if source_side > 0 else 0)
    end_x = target.x + (target.width if target_side > 0 else 0)
    start_y, end_y = ports[(index, "source")], ports[(index, "target")]
    if source.column == target.column:
        reach = min(WIRE_BOW_MAX, WIRE_BOW_MIN + abs(end_y - start_y) * 0.3)
    else:
        reach = max(WIRE_BOW_MIN, abs(end_x - start_x) / 2)
    first_x = start_x + source_side * reach
    second_x = end_x + target_side * reach

    return f"M{start_x} {start_y:.1f} C{first_x:.1f} {start_y:.1f} {second_x:.1f} {end_y:.1f} {end_x} {end_y:.1f}"


def make_wire_node(node: WireNode, /) -> str:

    center_x = node.x + node.width / 2
    label = html.escape(node.label)
    if node.sub:
        text = f'<text class="wire-name" x="{center_x}" y="{node.y + 22}" text-anchor="middle">{label}</text><text class="wire-sub" x="{center_x}" y="{node.y + 40}" text-anchor="middle">{html.escape(node.sub)}</text>'
    else:
        text = f'<text class="wire-skill" x="{center_x}" y="{node.y + node.height / 2 + 4}" text-anchor="middle">{label}</text>'
    rect = f'<rect x="{node.x}" y="{node.y}" width="{node.width}" height="{node.height}" rx="7"/>'

    return f'<g class="wire-node is-{node.tone}" data-wire-node="{html.escape(node.key)}" tabindex="0" role="button" aria-pressed="false" aria-label="{label}">{rect}{text}</g>'


def make_wire_legend() -> str:

    items = []
    for kind, label, is_on in WIRE_KINDS:
        swatch = f'<svg class="wire-swatch" width="40" height="12" viewBox="0 0 40 12" aria-hidden="true" focusable="false"><line class="wire-line is-{kind}" x1="2" y1="6" x2="38" y2="6"/></svg>'
        items.append(f'<li><button type="button" class="wire-toggle" data-wire-kind="{kind}" aria-pressed="{str(is_on).lower()}">{swatch}{html.escape(label)}</button></li>')

    return "\n".join(items)


def make_diagram(layout: Layout, /) -> str:

    facts = layout.facts
    nodes = get_wire_nodes(facts)
    edges = get_wire_edges(facts, nodes)
    ports = get_wire_ports(edges, nodes)
    height = max(node.y + node.height for node in nodes.values()) + WIRE_BOTTOM_MARGIN
    markers = "".join(f'<marker id="wire-head-{kind}" class="wire-head is-{kind}" viewBox="0 0 12 12" refX="11" refY="6" markerWidth="12" markerHeight="12" markerUnits="userSpaceOnUse" orient="auto"><path d="M1 1.5 L11 6 L1 10.5 z"/></marker>' for kind, _, _ in WIRE_KINDS)
    paths = "".join(
        f'<path class="wire-line is-{edge.kind}" data-wire-source="{html.escape(edge.source)}" data-wire-target="{html.escape(edge.target)}" data-wire-edge="{edge.kind}" marker-end="url(#wire-head-{edge.kind})" d="{make_wire_path(edge, index, nodes, ports)}"/>'
        for index, edge in enumerate(edges)
    )
    titles = "".join(f'<text class="wire-column" x="{WIRE_COLUMN_X[column] + WIRE_COLUMN_WIDTH[column] / 2}" y="28" text-anchor="middle">{title}</text>' for column, title in WIRE_COLUMN_TITLE.items())
    boxes = "".join(make_wire_node(node) for node in nodes.values())
    counts = {kind: sum(1 for edge in edges if edge.kind == kind) for kind, _, _ in WIRE_KINDS}
    description = f"{len(HOOK_WIRES)} hooks, the main session and {len(facts.agents)} agents, and {len(facts.skills)} skills, joined by {len(edges)} arrows: " + ", ".join(f"{counts[kind]} {label}" for kind, label, _ in WIRE_KINDS)

    return (
        '<div class="wire-body" data-wire>\n'
        f'<ul class="wire-legend" aria-label="Arrow kinds; each button shows or hides one kind">\n{make_wire_legend()}\n</ul>\n'
        '<p class="wire-status" data-wire-status role="status"></p>\n'
        '<div class="wire-scroll" tabindex="0" role="region" aria-label="Diagram of how hooks, agents and skills connect">\n'
        f'<svg class="wire-svg" viewBox="0 0 {WIRE_WIDTH} {height}" role="group" aria-label="{html.escape(description)}"><defs>{markers}</defs>{titles}<g class="wire-edges">{paths}</g><g class="wire-nodes">{boxes}</g></svg>\n'
        "</div>\n"
        "</div>"
    )


def get_site_page(key: str, /) -> tuple[str, str, str, str, tuple[str, ...]]:

    for page in SITE_PAGES:
        if page[0] == key:
            return page

    raise ValueError(f"the template names an unknown site page: {key}")


def make_site_head(key: str, facts: Facts, /) -> str:

    _, _, title, description, styles = get_site_page(key)
    full_title = title if key == "home" else f"{title} - Harness"
    extra = "".join(f'\n  <link rel="stylesheet" href="{name}">' for name in styles)

    return (
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"  <title>{html.escape(full_title)}</title>\n"
        f'  <meta name="description" content="{html.escape(description)}">\n'
        '  <link rel="preconnect" href="https://fonts.googleapis.com">\n'
        '  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
        '  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap">\n'
        f"{THEME_SCRIPT}\n"
        f'  <link rel="stylesheet" href="style.css?v={facts.values["style_hash"]}">{extra}'
    )


def make_site_bar(key: str, /) -> str:

    links = []
    for page_key, href, title, _, _ in SITE_PAGES:
        current = ' aria-current="page"' if page_key == key else ""
        links.append(f'<li><a class="site-link" href="{href}"{current}>{html.escape(title)}</a></li>')
    items = "\n        ".join(links)

    return (
        '<div class="site-bar">\n'
        '      <a class="site-brand" href="index.html">Harness</a>\n'
        '      <div class="site-tools">\n'
        f'      <nav aria-label="Pages"><ul class="site-nav">\n        {items}\n      </ul></nav>\n'
        '      <button type="button" class="theme-switch" role="switch" aria-checked="false" data-theme-toggle>\n'
        '        <span class="theme-switch-track" aria-hidden="true"><span class="theme-switch-thumb"></span></span>\n'
        '        <span class="theme-switch-label">Dark</span>\n'
        "      </button>\n"
        "      </div>\n"
        "    </div>"
    )


def make_site_footer(key: str, /) -> str:

    get_site_page(key)

    return (
        '<footer class="site-footer">\n'
        "      <span>Harness: agents, skills and hooks for coding agents.</span>\n"
        f'      <a href="{SITE_REPO}">Source on GitHub</a>\n'
        "    </footer>"
    )


def make_slot(slot: Slot, layout: Layout | None, facts: Facts, /) -> str:

    match slot.name:
        case "site-head" if slot.arguments:
            return make_site_head(slot.arguments[0], facts)
        case "site-bar" if slot.arguments:
            return make_site_bar(slot.arguments[0])
        case "site-footer" if slot.arguments:
            return make_site_footer(slot.arguments[0])
        case "pyramid" if layout:
            return make_pyramid(layout)
        case "panels" if layout:
            return make_panels(layout)
        case "diagram" if layout:
            return make_diagram(layout)
        case "install-command" | "install-copy" if slot.arguments and slot.arguments[0] in INSTALL_COMMANDS | UNINSTALL_COMMANDS:
            command = (INSTALL_COMMANDS | UNINSTALL_COMMANDS)[slot.arguments[0]]
            return make_shell(command) if slot.name == "install-command" else html.escape(command)
        case _:
            raise ValueError(f"the template holds an unknown slot: {slot.name}")




def get_fact(values: dict[str, str], name: str, /) -> str:

    if name not in values:
        raise ValueError(f"the template names an unknown fact: {{{{{name}}}}}")

    return html.escape(values[name], quote=False)


def make_layout(slots: list[Slot], facts: Facts, /) -> Layout:

    check_places(facts)
    names = [slot.name for slot in slots]
    has_map = any(name in SINGLE_SLOTS for name in names)
    wrong = [name for name in SINGLE_SLOTS if has_map and names.count(name) != 1]
    if wrong or names.count("diagram") > 1:
        raise ValueError(f"the template must hold each of {', '.join(SINGLE_SLOTS)} once, and the diagram at most once")

    return Layout(facts, get_level_hooks(facts.hooks))


def make_page(template: str, facts: Facts, /) -> str:

    with_facts = FACT.sub(lambda match: get_fact(facts.values, match.group(1)), template)
    slots = [Slot(match.group(1), tuple(match.group(2).split())) for match in SLOT.finditer(with_facts)]
    layout = make_layout(slots, facts) if any(slot.name in (*SINGLE_SLOTS, "diagram") for slot in slots) else None
    bare = SLOT.sub("", with_facts)
    for leftover in ("[[@", "{{"):
        if leftover in bare:
            raise ValueError(f"the template holds a marker the build cannot read, near {bare[bare.index(leftover) :][:60]!r}")
    page = SLOT.sub(lambda match: make_slot(Slot(match.group(1), tuple(match.group(2).split())), layout, facts), with_facts)

    return page


def get_difference(committed: str, fresh: str, /) -> str:

    committed_lines, fresh_lines = committed.splitlines(), fresh.splitlines()
    for number, (old, new) in enumerate(zip(committed_lines, fresh_lines, strict=False), start=1):
        if old != new:
            first = next((index for index, (a, b) in enumerate(zip(old, new, strict=False)) if a != b), min(len(old), len(new)))
            start = max(0, first - SNIPPET_LEAD)
            return f"line {number} reads {old[start : start + SNIPPET].strip()!r} there and {new[start : start + SNIPPET].strip()!r} in a fresh build"

    return f"it has {len(committed_lines)} lines and a fresh build {len(fresh_lines)}"


def build_band_view(root: Path) -> None:
    bun = shutil.which("bun")
    if bun is None:
        raise ValueError("bun is missing, and docs/band-view.js is bundled with it: curl -fsSL https://bun.sh/install | bash")
    completed = subprocess.run([bun, "run", str(root / BAND_VIEW_BUILDER)], cwd=root, check=False)
    if completed.returncode != 0:
        raise ValueError(f"bun failed with exit {completed.returncode} while bundling {BAND_VIEW_BUILDER}")
    if not (root / BAND_VIEW_BUNDLE).is_file():
        raise ValueError(f"bun ran but {BAND_VIEW_BUNDLE} was not written")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the plugin map page.")
    parser.add_argument("--root", type=Path, default=ROOT, help="the repository to read, whose docs/index.html is the page (default: this one)")
    parser.add_argument("--check", action="store_true", help="write nothing; exit 1 when the committed page differs from a fresh build")
    arguments = parser.parse_args()
    sys.dont_write_bytecode = True
    root = arguments.root.resolve()

    try:
        facts = get_facts(root)
        check_port_notes(root)
        pages = [(page, make_page((root / template).read_text(encoding="utf-8"), facts)) for template, page in PAGES]
    except (ValueError, OSError, SyntaxError, ImportError) as error:
        print(f"build_map: {error}", file=sys.stderr)
        return 1
    if not arguments.check:
        try:
            build_band_view(root)
        except ValueError as error:
            print(f"build_map: {error}", file=sys.stderr)
            return 1
        for page, text in pages:
            (root / page).write_text(text, encoding="utf-8", newline="\n")
        counts = ", ".join(f"{facts.values[key]} {key}" for key in ("agents", "skills", "hooks"))
        print(f"wrote {', '.join(str(page) for page, _ in pages)}: {counts}")
        return 0
    is_fresh = True
    for page, text in pages:
        if not (root / page).is_file():
            print(f"{page} is missing; run make map", file=sys.stderr)
            is_fresh = False
            continue
        committed = (root / page).read_text(encoding="utf-8")
        if committed != text:
            print(f"{page} is stale: {get_difference(committed, text)}; run make map", file=sys.stderr)
            is_fresh = False

    return 0 if is_fresh else 1


if __name__ == "__main__":
    sys.exit(main())
