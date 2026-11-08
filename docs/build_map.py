#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""Build the Harness page from the repository's own files, so it changes when an agent, a skill or a hook does.

The template holds the layout and the hand-written prose; this script fills its `<!-- @slot -->` markers and `{{fact}}`
tokens from the agent files, the skills, the hook list, a few hook constants and the test files. Stdlib only.

uv run python docs/build_map.py [--root FOLDER] [--check]

`--check` writes nothing and exits 1 with a one-line reason when the committed page differs from a fresh build.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import html
import importlib.util
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from types import ModuleType
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = Path("docs") / "map.html.in"
PAGE = Path("docs") / "index.html"
# The hand-written stylesheet and script the page links; the page carries a hash of each so `--check` sees an edit.
ASSETS = (Path("docs") / "style.css", Path("docs") / "script.js")
# Hex digits of an asset's hash in its link.
FINGERPRINT_LENGTH = 10
# A hooks.json command's script under `hooks/` and its first argument, if any.
HOOK_COMMAND = re.compile(r"hooks/([\w-]+\.py)\"?(?:\s+(\S+))?")
SLOT = re.compile(r"<!-- @([a-z-]+)([^>]*?) -->")
FACT = re.compile(r"\{\{(\w+)\}\}")
LIST_ITEM = re.compile(r"\s+- (.+)")
SENTENCE_END = re.compile(r"(?<=\.)\s+(?=[A-Z])")
# Where a skill's job stops: a spaced dash, a colon or a sentence end.
SUMMARY_END = re.compile(r" - |: |\. ")
# Characters of a skill's job before it is cut at a word; longer, it reads as a paragraph in a popover.
MAX_SUMMARY = 170
# A first sentence shorter than this says too little to be the job, so the skill's "Load" sentence stands in for it.
MIN_JOB = 20
# A clause cut from the job's sentence shorter than this reads as a fragment, so the whole sentence is kept.
MIN_CLAUSE = 40
# Characters of each differing line the --check reason shows, from a little before the first changed character.
SNIPPET = 60
SNIPPET_LEAD = 20
# The slots the template must hold exactly once.
SINGLE_SLOTS = ("pyramid", "panels")
# The words a port's state reads as; a popover shows the words before the comma.
PORT_STATES = {
    "runs": "runs",
    "advisory": "advisory, warns but blocks nothing",
    "off": "not ported",
}
# The events whose hooks run on a tool call; their popover names the tools after the moment.
TOOL_EVENTS = ("PreToolUse", "PostToolUse")


class Agent(NamedTuple):
    """One agent file's facts."""

    name: str
    model: str
    tools: tuple[str, ...]
    skills: tuple[str, ...]
    job: str  # the description's first sentence
    use: str  # its sentence on when to use the agent, empty when it has none


class Skill(NamedTuple):
    """One skill's facts."""

    job: str  # what the description says it is for
    when: str  # the description's "Load" sentences, empty when it has none


class Hook(NamedTuple):
    """One command of the hook list."""

    event: str
    matcher: str  # the tools it runs on, `|`-separated; empty for every tool
    script: str
    argument: str  # empty when the command passes none


class Facts(NamedTuple):
    """What the page shows from the repository."""

    agents: tuple[Agent, ...]
    skills: dict[str, Skill]  # keys are data: a skill's name to its facts
    hooks: tuple[Hook, ...]
    budgets: dict[str, int]  # keys are data: a role to its default turns, `*` for any other
    ports: dict[str, dict[str, str]]  # keys are data: a hook script to each port's state
    values: dict[str, str]  # keys are data: a `{{fact}}` token's name to its text


class Slot(NamedTuple):
    """A `<!-- @name arguments -->` marker of the template."""

    name: str
    arguments: tuple[str, ...]


class Kind(NamedTuple):
    """A band of one panel: its name, the plain sentence its members share, and the members."""

    name: str
    text: str
    members: tuple[str, ...]


class Level(NamedTuple):
    """One step of the pyramid, from the hardest bind down."""

    key: str
    name: str
    short: str  # a few words on the pyramid
    text: str  # what happens at this level; `{fact}` fields take the page's facts
    can: str  # the phrase a hook's popover sentence uses after "Can"


class Event(NamedTuple):
    """A moment Claude Code runs hooks at."""

    key: str
    moment: str  # a hook popover's words; a tool event's tools follow them


class Rule(NamedTuple):
    """One rule: what it does in a few words, the level it binds at and the hook script that acts."""

    text: str
    level: str
    script: str


class Layout(NamedTuple):
    """The facts and the hook scripts each level's rules name."""

    facts: Facts
    level_hooks: dict[str, list[str]]  # keys are data: a level's key to its hook scripts, in rule order


class Port(NamedTuple):
    """A tool a hook is ported to: its key in port/harness_port.py and its label on the page."""

    key: str
    label: str


class PortNote(NamedTuple):
    """A port fact the mapping cannot show: the state it sets for one hook script on one tool, and the README phrase it rests on."""

    script: str
    target: str
    state: str
    note: str
    phrase: str  # text that must appear in README.md, so the note cannot outlive its source


# Each agent, skill and hook sits in one band of its panel; a file in no band stops the build.
AGENT_KINDS = (
    Kind("Thinkers", "Work out what to do; write no files.", ("planner", "cold-reader", "analyst")),
    Kind("Finders", "Look things up and answer with sources.", ("scout", "researcher")),
    Kind("Doers", "Change files or run commands inside their write set.", ("worker", "designer", "releaser", "runner")),
    Kind("Checkers", "Test someone else's work, claim by claim.", ("reviewer", "auditor")),
)
SKILL_KINDS = (
    Kind("Run the job", "Plan, brief, accept, set up.", ("orchestrator", "workflows", "models", "accept", "init")),
    Kind("Think", "Settle facts and causes first.", ("evidence", "debug", "spec", "cold-read")),
    Kind(
        "Build",
        "Write code, commits and pages.",
        ("code-python", "code-js", "code-html-css", "code-shell", "code-terraform", "refactor", "comments", "git-commit", "design", "release"),
    ),
    Kind("Check", "Judge work against its spec.", ("testing", "review", "audit")),
    Kind("Report and learn", "Close a job; turn lessons into rules.", ("report", "retro", "hook-authoring", "skill-authoring", "agent-authoring")),
    Kind("Habits", "Cheap tool calls, every session.", ("tool-habits",)),
)
HOOK_KINDS = (
    Kind("Guards", "Refuse a risky call before it runs.", ("guard.py", "commit_gate.py", "delegate.py", "budget.py")),
    Kind("Gates", "Check what crosses a hand-off.", ("brief_lint.py", "report_gate.py")),
    Kind("Teachers", "Add a note when it helps.", ("context.py", "skill_gate.py", "nudge.py")),
    Kind("Closers", "Hold the turn until it is recorded.", ("turn.py",)),
)
# What each hook script does, in plain words; a script with no entry stops the build.
HOOK_JOBS = {
    "guard.py": "Refuses deletes, history rewrites and wildcards the shell would get wrong; asks you before a package is added or removed.",
    "commit_gate.py": "Refuses a commit message out of form or crediting an AI, and a commit that drops tests without saying why.",
    "delegate.py": "Caps the main session's own edits in one turn, so a bigger change goes to a worker.",
    "budget.py": "Lets an agent past its turn budget do nothing but hand back its report, and tells the main session what each agent is doing.",
    "brief_lint.py": "Refuses an agent with no harness role, and adds a note when a brief lacks a line its role needs.",
    "report_gate.py": "Sends a report back when its form breaks or a claim is not backed by the agent's own calls.",
    "context.py": "Starts every session and agent with the tool habits and what it owes.",
    "skill_gate.py": "Hands an agent the rules for a kind of file before its first edit of one, and the commit rules before a commit.",
    "nudge.py": "Adds one line when an agent wastes tool turns, such as reading the same small file twice.",
    "turn.py": "Holds the main session's turn until it ends with a closing status, and says when a retro is due.",
}
LEVELS = (
    Level("stopped", "Stops the call", "never runs", "The call never runs; the agent is told which rule fired and what to do instead.", "stop the call"),
    Level("asks", "Asks you", "waits for your yes", "Claude Code pauses and asks you; your yes runs it.", "ask you first"),
    Level("sent-back", "Sent back", "report redone", "The report goes back to its agent, naming only the parts that are wrong, up to {send_backs} times.", "send the report back"),
    Level("turn", "Turn can't end", "until it is fixed", "The main session's turn does not end until it adds what is missing; it gets {max_blocks} tries.", "keep the turn open until it is fixed"),
    Level("reminder", "Reminds the model", "runs, with a note", "The call runs; one line of advice comes back with the result.", "remind the model"),
    Level("advice", "Advice", "read, not checked", "Text the model reads before a kind of work. Nothing checks it was followed; a reviewer or a retro catches what slips.", "give the model advice"),
    Level("written", "Written down", "your AGENTS.md", "Your project's own rules in AGENTS.md, written once by /harness:init; they bind as far as the model reads them.", "write the rule into AGENTS.md"),
)
# The brackets beside the pyramid, top to bottom: the style class, its title and a note. The page's CSS gives each its rows
# (hooks 1 to 4, hook notes 5, model 6 to 7), so they follow the order of LEVELS above.
BRACES = (
    ("hooks", "Hooks enforce", "the call waits"),
    ("reminder", "Hook notes", ""),
    ("model", "Model decides", "nothing checks"),
)
# The level every skill sits at, and the one that names a file of the project instead of a part of the plugin.
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
# Each rule the harness enforces or advises, the level it binds at and the hook script that acts; the pyramid's counts
# and each hook's levels come from this table, and a hook script with no rule here stops the build.
RULES = (
    Rule("Deleting files is refused, except named files inside the scratch folder", "stopped", "guard.py"),
    Rule("Rewriting shared history is refused", "stopped", "guard.py"),
    Rule("A wildcard the shell would get wrong is refused", "stopped", "guard.py"),
    Rule("An agent without a harness role is refused", "stopped", "brief_lint.py"),
    Rule("An agent past its turn budget can only hand back its report", "stopped", "budget.py"),
    Rule("A commit message out of form, or crediting an AI, is refused", "stopped", "commit_gate.py"),
    Rule("A commit that leaves fewer tests without saying why is refused", "stopped", "commit_gate.py"),
    Rule("The main session's edits past a few in one turn go to a worker", "stopped", "delegate.py"),
    Rule("Adding or removing packages asks you first", "asks", "guard.py"),
    Rule("A report needs its parts and a verdict", "sent-back", "report_gate.py"),
    Rule("Each claim of a report must match what the agent did", "sent-back", "report_gate.py"),
    Rule("A report stays short", "sent-back", "report_gate.py"),
    Rule("A long turn ends with a closing status", "turn", "turn.py"),
    Rule("A turn that ran agents names each one with its verdict", "turn", "turn.py"),
    Rule("A lesson changes a rule file, or the status says none", "turn", "turn.py"),
    Rule("A retro is due when feedback items wait", "turn", "turn.py"),
    Rule("The rules for a kind of file arrive before its first edit", "reminder", "skill_gate.py"),
    Rule("A brief missing a line its role needs gets a note", "reminder", "brief_lint.py"),
    Rule("Wasted reads and hidden failures get a note", "reminder", "nudge.py"),
    Rule("The main session gets a note of what each agent is doing", "reminder", "budget.py"),
    Rule("A blocking sleep is removed or moved to the background", "reminder", "guard.py"),
    Rule("A shell write outside the scratch folder gets a note", "reminder", "guard.py"),
    Rule("The main session editing files itself gets a note", "reminder", "delegate.py"),
    Rule("The tool habits go in front of every session and agent", "advice", "context.py"),
)
PORTS = (Port("claude", "Claude"), Port("cortex", "Cortex"), Port("kiro", "Kiro"))
PORT_NOTES = (
    PortNote("report_gate.py", "cortex", "advisory", "Cortex cannot block at SubagentStop", "the report gate blocks nothing (advisory)"),
    PortNote("guard.py", "kiro", "runs", 'an "ask" becomes a block', 'a guard "ask" becomes a block'),
    PortNote("guard.py", "cortex", "runs", 'an "ask" becomes a block', 'An "ask" becomes a block.'),
)


# =========================================================================== #
# Reading The Repository
# =========================================================================== #


def read_frontmatter(path: Path, /) -> dict[str, str | list[str]]:  # keys are data
    """The `key: value` lines and `- item` lists between a file's opening `---` and the next one."""

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
    """A frontmatter field that must be one line of text."""

    value = fields.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{path.name} has no `{key}:` line")

    return value


def get_items(fields: dict[str, str | list[str]], key: str, path: Path, /) -> list[str]:
    """A frontmatter list, empty when the key is absent."""

    value = fields.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"{path.name}: `{key}:` should be a list")

    return value


def get_agents(root: Path, /) -> tuple[Agent, ...]:
    """Every agent file's facts, in file name order."""

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
    """A skill's job and when to load it, split from its description's sentences.

    The job is the first sentence that is not a "Load" sentence, cut at its first clause when that clause is long enough.
    A description whose only other sentence is a few words long uses its "Load" sentence for the job and the rest as `when`.
    """

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


def get_skills(root: Path, /) -> dict[str, Skill]:  # keys are data
    """Every skill's name and facts, in folder name order."""

    skills = {}
    for path in sorted((root / "skills").glob("*/SKILL.md")):
        fields = read_frontmatter(path)
        skills[get_text(fields, "name", path)] = get_skill(get_text(fields, "description", path))

    return skills


def get_hooks(root: Path, /) -> tuple[Hook, ...]:
    """Every command of the hook list, in the file's order."""

    events = json.loads((root / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
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
    """The literal a module assigns to `name` at its top level, read without running the module."""

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
    """The module at `path`, run under a name of its own with its folder on the import path."""

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


def get_port_states(port: ModuleType, events: dict[str, list[dict]], script: str, /) -> dict[str, str]:  # keys are data: the port keys
    """Each port's state for one hook script: runs or off, from the hook list and harness_port's own conversion, then PORT_NOTES."""

    marker = f"hooks/{script}"
    groups = [
        (event, group)
        for event, event_groups in events.items()
        for group in event_groups
        if any(marker in command["command"] for command in group["hooks"])
    ]

    states = {"claude": "runs"}
    for target in ("cortex", "kiro"):
        converted = False
        for event, group in groups:
            plan = port.Plan()
            kiro_entries: list[dict] = []
            port.plan_hook_group(plan, target, event, group, kiro_entries)
            commands = [entry["action"]["command"] for entry in kiro_entries]
            for cortex_group in plan.cortex_hooks.get(event, []):
                commands.extend(hook["command"] for hook in cortex_group["hooks"])
            converted = converted or any(marker in command for command in commands)
        states[target] = "runs" if converted else "off"

    for note in PORT_NOTES:
        if note.script == script:
            states[note.target] = note.state

    return states


def get_ports(root: Path, scripts: Iterable[str], /) -> dict[str, dict[str, str]]:  # keys are data: hook scripts, then port keys
    """Each hook script's state on each port, with port/harness_port.py imported once."""

    port = import_path(root / "port" / "harness_port.py")
    events = json.loads((root / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]

    return {script: get_port_states(port, events, script) for script in scripts}


def get_fingerprint(path: Path, /) -> str:
    """A short hash of a hand-written asset, so the page's link to it goes stale when the file changes."""

    return hashlib.sha256(path.read_bytes()).hexdigest()[:FINGERPRINT_LENGTH]


def get_facts(root: Path, /) -> Facts:
    """Everything the page shows, read from the repository at `root`."""

    hooks_folder = root / "hooks"
    turn = hooks_folder / "turn.py"
    report_gate = hooks_folder / "report_gate.py"
    agents = get_agents(root)
    skills = get_skills(root)
    hooks = get_hooks(root)
    scripts = list(dict.fromkeys(hook.script for hook in hooks))
    budgets = get_constant(hooks_folder / "budget.py", "DEFAULT_BUDGET", dict)
    required = get_constant(hooks_folder / "brief_lint.py", "DEFAULT_REQUIRED", dict)
    budget_values = {f"budget_{'default' if role == '*' else role.replace('-', '_')}": turns for role, turns in budgets.items()}

    values = {
        "agents": len(agents),
        "skills": len(skills),
        "hooks": len(scripts),
        "send_backs": get_constant(report_gate, "MAX_SEND_BACKS", int),
        "report_chars": get_constant(report_gate, "MAX_REPORT_CHARS", int),
        "max_blocks": get_constant(turn, "MAX_BLOCKS", int),
        "min_calls": get_constant(turn, "MIN_CALLS", int),
        "retro_items": get_constant(turn, "RETRO_ITEMS", int),
        "headings": ", ".join(get_constant(turn, "HEADINGS", tuple)),
        "brief_worker": ", ".join(required.get("worker", required.get("*", []))),
        **budget_values,
        "style_hash": get_fingerprint(root / ASSETS[0]),
        "script_hash": get_fingerprint(root / ASSETS[1]),
    }

    return Facts(agents, skills, hooks, budgets, get_ports(root, scripts), {key: str(value) for key, value in values.items()})


# =========================================================================== #
# Checking The Places
# =========================================================================== #


def check_kinds(kinds: tuple[Kind, ...], names: Iterable[str], where: str, /) -> None:
    """Every name sits in exactly one kind and every member is a real name; else the build stops, naming `where`."""

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
    """Every agent, skill and hook has a band, every hook a job and every hook event words for its popover."""

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


def get_level_hooks(hooks: tuple[Hook, ...], /) -> dict[str, list[str]]:  # keys are data: level keys
    """The hook scripts the rules of each level name, in RULES order; a hook with no rule, or a rule naming an unknown level or script, stops the build."""

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
    """Every port note rests on a README phrase found on exactly one line; else the build stops."""

    readme_lines = (root / "README.md").read_text(encoding="utf-8").splitlines()
    for note in PORT_NOTES:
        found = [number for number, line in enumerate(readme_lines, start=1) if note.phrase in line]
        if len(found) != 1:
            raise ValueError(f"README.md must hold the phrase {note.phrase!r} on one line, found it on {found}")


# =========================================================================== #
# Rendering
# =========================================================================== #


def get_tip_id(panel: str, name: str, /) -> str:
    """The id of a chip's popover."""

    return f"tip-{panel}-{re.sub(r'[^a-z0-9-]', '-', name)}"


def get_hook_levels(layout: Layout, script: str, /) -> tuple[Level, ...]:
    """The levels a hook script acts at, hardest first."""

    return tuple(level for level in LEVELS if script in layout.level_hooks[level.key])


def get_access(tools: tuple[str, ...], /) -> str:
    """What an agent's tools let it do, in a few words."""

    access = "edits files" if {"Edit", "Write"} & set(tools) else "read-only"

    return access + ", web" if {"WebFetch", "WebSearch"} & set(tools) else access


def make_row(icon: str, term: str, value: str, /, *, is_markup: bool = False) -> str:
    """One icon row of a popover: the icon and `term`, then the value (escaped unless it is markup). An empty value makes no row."""

    if not value:
        return ""
    shown = value if is_markup else html.escape(value)
    icon_markup = f'<svg class="icon" width="14" height="14" aria-hidden="true"><use href="#i-{icon}"/></svg>'

    return f"<dt>{icon_markup}{html.escape(term)}</dt><dd>{shown}</dd>"


def make_chip(panel: str, name: str, job: str, rows: Iterable[str], /, *, levels: tuple[Level, ...] = ()) -> str:
    """One chip and its popover: a strip in the group's colour with its word and the name, the job, then the icon `rows`.

    `levels` are the levels the pyramid lights the chip for.
    """

    tip_id = get_tip_id(panel, name)
    escaped = html.escape(name)
    keys = " ".join(level.key for level in levels)
    data_levels = f' data-levels="{keys}"' if keys else ""

    return (
        f'<li class="chip-item"><button type="button" class="chip" data-item="{panel}:{escaped}"{data_levels} aria-describedby="{tip_id}">'
        f"{escaped}</button>"
        f'<div class="tip kind-{panel}" id="{tip_id}" role="tooltip" hidden>'
        f'<p class="tip-strip"><span class="tip-kind">{panel}</span><span class="tip-name">{escaped}</span></p>'
        f'<div class="tip-body"><p class="tip-job">{html.escape(job)}</p><dl class="tip-grid">{"".join(rows)}</dl></div></div></li>'
    )


def make_agent_chip(agent: Agent, facts: Facts, /) -> str:
    """An agent's chip: its name and job; the popover adds its model, access and budget, when to use it and its skills."""

    turns = facts.budgets.get(agent.name, facts.budgets.get("*"))
    rows = (
        make_row("model", "Model", agent.model),
        make_row("tools", "Tools", f"{get_access(agent.tools)}, {f'{turns} turns' if turns else 'no budget'}"),
        make_row("load", "Preloads", ", ".join(agent.skills)),
        make_row("when", "Use", agent.use),
    )

    return make_chip("agent", agent.name, agent.job, rows)


def make_skill_chip(name: str, layout: Layout, /) -> str:
    """A skill's chip; the popover adds its kind, the roles that preload it and when to load it."""

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

    return make_chip("skill", name, skill.job, rows, levels=levels)


def make_ports(states: dict[str, str], /) -> str:
    """A hook's port badges, each state in words as well as in its style."""

    badges = "".join(f'<span class="port" data-state="{states[port.key]}">{port.label} {PORT_STATES[states[port.key]].split(",")[0]}</span>' for port in PORTS)

    return f'<span class="ports">{badges}</span>'


def get_moments(script: str, hooks: tuple[Hook, ...], /) -> str:
    """When Claude Code runs a hook script, in plain words, in the hook list's order."""

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
    """One plain sentence on what a hook can do at its levels, hardest first; empty when it has none."""

    phrases = [level.can for level in LEVELS if level in levels]
    if not phrases:
        return ""
    if len(phrases) == 1:
        return f"Can {phrases[0]}."
    joiner = ", or " if len(phrases) > 2 else " or "

    return f"Can {', '.join(phrases[:-1])}{joiner}{phrases[-1]}."


def make_meter(levels: tuple[Level, ...], /) -> str:
    """A hook's levels as a meter, a segment per level a hook can act at and the ones it acts at lit, then one sentence on them."""

    keys = {level.key for level in levels}
    segments = "".join(
        f'<span class="meter-seg is-{level.key} is-on"></span>' if level.key in keys else '<span class="meter-seg"></span>'
        for level in LEVELS
        if level.key not in {SKILL_LEVEL, FILE_LEVEL}
    )
    sentence = get_enforcement_sentence(levels)

    return f'<span class="meter" aria-hidden="true">{segments}</span><span class="meter-sentence">{html.escape(sentence)}</span>'


def make_hook_chip(script: str, layout: Layout, /) -> str:
    """A hook's chip; the popover adds when it runs, its enforcement levels and its ports."""

    levels = get_hook_levels(layout, script)
    rows = (
        make_row("events", "Runs", get_moments(script, layout.facts.hooks)),
        make_row("levels", "Enforcement", make_meter(levels), is_markup=True),
        make_row("ports", "Ported", make_ports(layout.facts.ports[script]), is_markup=True),
    )

    return make_chip("hook", script, HOOK_JOBS[script], rows, levels=levels)


def make_panel(panel: str, title: str, kicker: str, bands: Iterable[tuple[Kind, list[str]]], /) -> str:
    """One panel: a band per kind, its name and sentence in the left column and its chips on the right."""

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
    """The three panels: agents, skills and hooks, each sorted by kind."""

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
    """How many panel parts a level lights, and a sentence naming them."""

    scripts = layout.level_hooks[level.key]
    names = ", ".join(scripts)
    if level.key == FILE_LEVEL:
        return 1, "Lights nothing on the right: AGENTS.md is your project's own file."
    if level.key == SKILL_LEVEL:
        num_skills = len(layout.facts.skills)
        return num_skills + len(scripts), f"Lights all {num_skills} skills" + (f" and {names}." if scripts else ".")

    return len(scripts), f"Lights {len(scripts)} hook{'' if len(scripts) == 1 else 's'}: {names}."


def make_pyramid(layout: Layout, /) -> str:
    """The pyramid, hardest bind on top: a bar per level with its count, brackets for who holds the levels, and the note each level shows when pointed at."""

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


def make_slot(slot: Slot, layout: Layout, /) -> str:
    """The markup that replaces one slot of the template."""

    match slot.name:
        case "pyramid":
            return make_pyramid(layout)
        case "panels":
            return make_panels(layout)
        case _:
            raise ValueError(f"the template holds an unknown slot: {slot.name}")


# =========================================================================== #
# Building The Page
# =========================================================================== #


def get_fact(values: dict[str, str], name: str, /) -> str:
    """A `{{fact}}` token's text, escaped for the page; an unknown name is an error."""

    if name not in values:
        raise ValueError(f"the template names an unknown fact: {{{{{name}}}}}")

    return html.escape(values[name], quote=False)


def make_layout(slots: list[Slot], facts: Facts, /) -> Layout:
    """Check the slots and every part's place, and find which hooks each level's rules name."""

    check_places(facts)
    names = [slot.name for slot in slots]
    wrong = [name for name in SINGLE_SLOTS if names.count(name) != 1]
    if wrong:
        raise ValueError(f"the template must hold each of {', '.join(SINGLE_SLOTS)} once")

    return Layout(facts, get_level_hooks(facts.hooks))


def make_page(template: str, facts: Facts, /) -> str:
    """The page: the template with its fact tokens and then its slots filled."""

    with_facts = FACT.sub(lambda match: get_fact(facts.values, match.group(1)), template)
    slots = [Slot(match.group(1), tuple(match.group(2).split())) for match in SLOT.finditer(with_facts)]
    layout = make_layout(slots, facts)
    page = SLOT.sub(lambda match: make_slot(Slot(match.group(1), tuple(match.group(2).split())), layout), with_facts)
    for leftover in ("<!-- @", "{{"):
        if leftover in page:
            raise ValueError(f"the template holds a marker the build cannot read, near {page[page.index(leftover) :][:60]!r}")

    return page


def get_difference(committed: str, fresh: str, /) -> str:
    """Where the committed page first differs from a fresh build, in a few words for one line."""

    committed_lines, fresh_lines = committed.splitlines(), fresh.splitlines()
    for number, (old, new) in enumerate(zip(committed_lines, fresh_lines, strict=False), start=1):
        if old != new:
            first = next((index for index, (a, b) in enumerate(zip(old, new, strict=False)) if a != b), min(len(old), len(new)))
            start = max(0, first - SNIPPET_LEAD)
            return f"line {number} reads {old[start : start + SNIPPET].strip()!r} there and {new[start : start + SNIPPET].strip()!r} in a fresh build"

    return f"it has {len(committed_lines)} lines and a fresh build {len(fresh_lines)}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="the repository to read, whose docs/index.html is the page (default: this one)")
    parser.add_argument("--check", action="store_true", help="write nothing; exit 1 when the committed page differs from a fresh build")
    arguments = parser.parse_args()
    # Importing the case runner must leave no bytecode cache in the repository.
    sys.dont_write_bytecode = True
    root = arguments.root.resolve()
    target = root / PAGE

    try:
        facts = get_facts(root)
        check_port_notes(root)
        page = make_page((root / TEMPLATE).read_text(encoding="utf-8"), facts)
    except (ValueError, OSError, SyntaxError, ImportError) as error:
        print(f"build_map: {error}", file=sys.stderr)
        return 1
    if not arguments.check:
        target.write_text(page, encoding="utf-8", newline="\n")
        counts = ", ".join(f"{facts.values[key]} {key}" for key in ("agents", "skills", "hooks"))
        print(f"wrote {PAGE}: {counts}")
        return 0
    if not target.is_file():
        print(f"{PAGE} is missing; run make map", file=sys.stderr)
        return 1
    committed = target.read_text(encoding="utf-8")
    if committed != page:
        print(f"{PAGE} is stale: {get_difference(committed, page)}; run make map", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
