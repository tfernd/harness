#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# [tool.uv]
# exclude-newer = "7 days"
# ///
"""Build the Harness Map page from the repository's own files, so it changes when an agent, a skill or a hook does.

The template holds the layout and the hand-written prose; this script fills its `<!-- @slot -->` markers and `{{fact}}`
tokens from the agent files, the skills, the hook list, a few hook constants and the test files. Stdlib only.

uv run python docs/build_map.py [--root FOLDER] [--check]

`--check` writes nothing and exits 1 with a one-line reason when the committed page differs from a fresh build.
"""

from __future__ import annotations

import argparse
import ast
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
# The role whose card shows before a reader picks one; the first agent stands in when it is gone.
DEFAULT_ROLE = "worker"
# A hooks.json command's script under `hooks/` and its first argument, if any.
HOOK_COMMAND = re.compile(r"hooks/([\w-]+\.py)\"?(?:\s+(\S+))?")
SLOT = re.compile(r"<!-- @([a-z-]+)([^>]*?) -->")
FACT = re.compile(r"\{\{(\w+)\}\}")
LIST_ITEM = re.compile(r"\s+- (.+)")
SENTENCE_END = re.compile(r"(?<=\.)\s+(?=[A-Z])")
# Where a skill's job stops: a spaced dash, a colon or a sentence end.
SUMMARY_END = re.compile(r" - |: |\. ")
# Characters of a skill's job before it is cut at a word; longer, it reads as a paragraph in a tooltip.
MAX_SUMMARY = 170
# A first sentence shorter than this says too little to be the job, so the skill's "Load" sentence stands in for it.
MIN_JOB = 20
# A clause cut from the job's sentence shorter than this reads as a fragment, so the whole sentence is kept.
MIN_CLAUSE = 40
# The skill whose card shows before a reader picks one; the first skill of the first band stands in when it is gone.
DEFAULT_SKILL = "report"
# The bands of the skills section, in the README skills table's groups; a skill folder in no band stops the build.
SKILL_BANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Always on", ("tool-habits",)),
    ("Process", ("orchestrator", "workflows", "accept", "init", "report")),
    ("Quality", ("spec", "cold-read", "review", "audit", "evidence", "testing", "debug", "refactor")),
    ("Languages", ("code-python", "code-js", "code-html-css", "code-terraform", "code-shell")),
    ("Writing", ("comments", "git-commit")),
    ("Learning", ("models", "retro")),
)
# Characters of each differing line the --check reason shows, from a little before the first changed character.
SNIPPET = 60
SNIPPET_LEAD = 20
# The slots the template must hold exactly once.
SINGLE_SLOTS = ("agents-rest", "agent-cards", "skill-bands", "skill-cards")
RULE_HOOK = re.compile(r'<span class="rule-hook">([\w-]+\.py)</span>')
PORT_NOTES_MARKER = "<!-- port-notes -->"
# The words a port badge says for each state.
PORT_STATES = {
    "runs": "runs",
    "advisory": "advisory, warns but blocks nothing",
    "off": "not ported",
}


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
    required: dict[str, list[str]]  # keys are data: a role to the lines its brief needs, `*` for any other
    values: dict[str, str]  # keys are data: a `{{fact}}` token's name to its text


class Slot(NamedTuple):
    """A `<!-- @name arguments -->` marker of the template."""

    name: str
    arguments: tuple[str, ...]


class Layout(NamedTuple):
    """Where each fact goes: the facts, the agents no band names and the role and skill shown first."""

    facts: Facts
    rest_agents: list[Agent]
    default_role: str
    default_skill: str


class Port(NamedTuple):
    """A tool a hook is ported to: its key in port/harness_port.py, its label on the page and its glyph path."""

    key: str
    label: str
    glyph: str


class PortNote(NamedTuple):
    """A port fact the mapping cannot show: the state it sets for one hook script on one tool, and the README phrase it rests on."""

    script: str
    target: str
    state: str
    note: str
    phrase: str  # text that must appear in README.md, so the note cannot outlive its source


PORTS = (
    Port("claude", "Claude", "M6 1l1.4 3.6L11 6 7.4 7.4 6 11 4.6 7.4 1 6l3.6-1.4z"),
    Port("cortex", "Cortex", "M1 1h4v4H1zm6 0h4v4H7zM1 7h4v4H1zm6 0h4v4H7z"),
    Port("kiro", "Kiro", "M6 1l5 10H1z"),
)
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

    if others and len(others[0]) >= MIN_JOB:
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


def get_num_cases(path: Path, /) -> int:
    """How many cases the case runner runs: the lists its `every` joins, counted in the imported module."""

    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        match node:
            case ast.Assign(targets=[ast.Name(id="every")], value=ast.List(elts=elements)):
                names = [item.value.id for item in elements if isinstance(item, ast.Starred) and isinstance(item.value, ast.Name)]
    if not names:
        raise ValueError(f"{path.name} joins no case lists into `every`")
    module = import_path(path)

    return sum(len(getattr(module, name)) for name in names)


def get_facts(root: Path, /) -> Facts:
    """Everything the page shows, read from the repository at `root`."""

    hooks_folder = root / "hooks"
    turn = hooks_folder / "turn.py"
    report_gate = hooks_folder / "report_gate.py"
    agents = get_agents(root)
    skills = get_skills(root)
    hooks = get_hooks(root)
    budgets = get_constant(hooks_folder / "budget.py", "DEFAULT_BUDGET", dict)
    required = get_constant(hooks_folder / "brief_lint.py", "DEFAULT_REQUIRED", dict)
    budget_values = {f"budget_{'default' if role == '*' else role.replace('-', '_')}": turns for role, turns in budgets.items()}

    values = {
        "agents": len(agents),
        "skills": len(skills),
        "hooks": len({hook.script for hook in hooks}),
        "cases": get_num_cases(root / "tests" / "run_cases.py"),
        "mutants": len(get_constant(root / "tests" / "mutants.py", "MUTANTS", tuple)),
        "send_backs": get_constant(report_gate, "MAX_SEND_BACKS", int),
        "report_chars": get_constant(report_gate, "MAX_REPORT_CHARS", int),
        "max_blocks": get_constant(turn, "MAX_BLOCKS", int),
        "min_calls": get_constant(turn, "MIN_CALLS", int),
        "retro_items": get_constant(turn, "RETRO_ITEMS", int),
        "headings": ", ".join(get_constant(turn, "HEADINGS", tuple)),
        "brief_worker": ", ".join(required.get("worker", required.get("*", []))),
        **budget_values,
    }

    return Facts(agents, skills, hooks, budgets, required, {key: str(value) for key, value in values.items()})


# =========================================================================== #
# Rendering
# =========================================================================== #


def make_agent_chip(agent: Agent, /, *, is_default: bool) -> str:
    """An agent's chip in its band: the button that shows its card."""

    name = html.escape(agent.name)

    return (
        f'<button type="button" class="crew-chip" data-choice="{name}" aria-pressed="{str(is_default).lower()}" '
        f'aria-controls="role-{name}">{name} <span class="crew-chip-model">{html.escape(agent.model)}</span></button>'
    )


def make_skill_chips(names: Iterable[str], skills: dict[str, Skill], /) -> str:
    """A chip per skill name with its summary as the tooltip; a name with no skill file is an error."""

    chips = []
    for name in names:
        if name not in skills:
            raise ValueError(f"the map names the skill {name!r}, which has no skills/{name}/SKILL.md")
        chips.append(f'<span class="skill-chip" title="{html.escape(skills[name].job)}">{html.escape(name)}</span>')

    return "\n".join(chips)


def get_access(tools: tuple[str, ...], /) -> str:
    """What an agent's tools let it do, in a few words."""

    access = "edits files" if {"Edit", "Write"} & set(tools) else "read-only"

    return access + (", web" if {"WebFetch", "WebSearch"} & set(tools) else "")


def make_agent_card(agent: Agent, facts: Facts, /, *, is_default: bool) -> str:
    """An agent's card: model, budget, access, job, when to use it, the lines its brief needs, skills and tools."""

    name = html.escape(agent.name)
    turns = facts.budgets.get(agent.name, facts.budgets.get("*"))
    tags = "".join(
        f'<span class="tag">{html.escape(tag)}</span>' for tag in (agent.model, f"{turns} turns" if turns else "no budget", get_access(agent.tools))
    )
    brief_lines = facts.required.get(agent.name, facts.required.get("*", []))
    rows = [
        ("Brief needs", " ".join(f"<code>{html.escape(line)}</code>" for line in brief_lines)),
        ("Skills", make_skill_chips(agent.skills, facts.skills)),
        ("Tools", html.escape(", ".join(agent.tools))),
    ]
    facts_list = "\n".join(
        f'<div class="crew-card-fact"><dt class="crew-card-term">{term}</dt><dd class="crew-card-value">{value}</dd></div>'
        for term, value in rows
        if value
    )
    hidden = "" if is_default else " hidden"
    use = f'\n<p class="crew-card-use">{html.escape(agent.use)}</p>' if agent.use else ""

    return (
        f'<article class="card crew-card" id="role-{name}" data-choice-panel="{name}" aria-labelledby="role-{name}-name"{hidden}>\n'
        f'<div class="crew-card-head"><h3 class="crew-card-name" id="role-{name}-name">{name}</h3>{tags}</div>\n'
        f"<p>{html.escape(agent.job)}</p>{use}\n"
        f'<dl class="crew-card-facts">\n{facts_list}\n</dl>\n'
        "</article>"
    )


def make_agent_chips(slot: Slot, layout: Layout, /) -> str:
    """The chips of the agents a band's slot names; a name with no agent file is an error."""

    by_name = {agent.name: agent for agent in layout.facts.agents}
    missing = [name for name in slot.arguments if name not in by_name]
    if missing:
        raise ValueError(f"the template names agents with no file under agents/: {', '.join(missing)}")

    return "\n".join(make_agent_chip(by_name[name], is_default=name == layout.default_role) for name in slot.arguments)


def make_rest_band(layout: Layout, /) -> str:
    """A band for the agents no band names, empty when there are none."""

    if not layout.rest_agents:
        return ""
    chips = "\n".join(make_agent_chip(agent, is_default=agent.name == layout.default_role) for agent in layout.rest_agents)

    return f'<div class="crew-band"><span class="crew-band-name">Other</span><div class="crew-chips">{chips}</div></div>'


def make_skill_chip(name: str, /, *, is_default: bool) -> str:
    """A skill's chip in its band: the button that shows its card."""

    escaped = html.escape(name)

    return (
        f'<button type="button" class="crew-chip" data-choice="{escaped}" aria-pressed="{str(is_default).lower()}" '
        f'aria-controls="skill-{escaped}">{escaped}</button>'
    )


def make_skill_bands(layout: Layout, /) -> str:
    """One band of chips per entry of SKILL_BANDS."""

    return "\n".join(
        f'<div class="crew-band"><span class="crew-band-name">{html.escape(band)}</span><div class="crew-chips">'
        + "\n".join(make_skill_chip(name, is_default=name == layout.default_skill) for name in names)
        + "</div></div>"
        for band, names in SKILL_BANDS
    )


def make_skill_card(name: str, band: str, layout: Layout, /) -> str:
    """A skill's card: its band, its job, when to load it and the agents that preload it."""

    skill = layout.facts.skills[name]
    escaped = html.escape(name)
    preloaders = [agent.name for agent in layout.facts.agents if name in agent.skills]
    tags = "".join(f'<span class="tag">{html.escape(agent)}</span>' for agent in preloaders) or "none"
    hidden = "" if name == layout.default_skill else " hidden"
    when = f'<p class="crew-card-use">{html.escape(skill.when)}</p>\n' if skill.when else ""

    return (
        f'<article class="card crew-card" id="skill-{escaped}" data-choice-panel="{escaped}" aria-labelledby="skill-{escaped}-name"{hidden}>\n'
        f'<div class="crew-card-head"><h3 class="crew-card-name" id="skill-{escaped}-name">{escaped}</h3><span class="tag">{html.escape(band)}</span></div>\n'
        f"<p>{html.escape(skill.job)}</p>\n"
        f"{when}"
        '<dl class="crew-card-facts"><div class="crew-card-fact"><dt class="crew-card-term">Preloaded by</dt>'
        f'<dd class="crew-card-value">{tags}</dd></div></dl>\n'
        "</article>"
    )


def make_skill_cards(layout: Layout, /) -> str:
    """The card of every skill, in band order."""

    return "\n".join(make_skill_card(name, band, layout) for band, names in SKILL_BANDS for name in names)


def make_slot(slot: Slot, layout: Layout, /) -> str:
    """The markup that replaces one slot of the template."""

    match slot.name:
        case "agents":
            return make_agent_chips(slot, layout)
        case "agents-rest":
            return make_rest_band(layout)
        case "agent-cards":
            return "\n".join(make_agent_card(agent, layout.facts, is_default=agent.name == layout.default_role) for agent in layout.facts.agents)
        case "skill-bands":
            return make_skill_bands(layout)
        case "skill-cards":
            return make_skill_cards(layout)
        case "skill-chips":
            return make_skill_chips(slot.arguments, layout.facts.skills)
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


def check_skill_bands(skills: dict[str, Skill], /) -> None:
    """Every skill folder sits in exactly one band and every band entry has a folder; else the build stops."""

    banded = [name for _, names in SKILL_BANDS for name in names]
    unbanded = [name for name in skills if name not in banded]
    if unbanded:
        raise ValueError(f"skills/{unbanded[0]} is in no band of SKILL_BANDS in docs/build_map.py")
    missing = [name for name in banded if name not in skills]
    if missing:
        raise ValueError(f"SKILL_BANDS names the skill {missing[0]!r}, which has no skills/{missing[0]}/SKILL.md")
    if len(set(banded)) != len(banded):
        raise ValueError("SKILL_BANDS names a skill in two bands")


def check_hooks_shown(page: str, hooks: tuple[Hook, ...], /) -> None:
    """Every hook script is named in a rule row's badge; else the build stops."""

    for hook in hooks:
        if f'class="rule-hook">{hook.script}<' not in page:
            raise ValueError(f"hooks/{hook.script} is named on no rule row of the page")


def make_layout(slots: list[Slot], facts: Facts, /) -> Layout:
    """Find the agents no band names and check the skill bands; a slot used wrongly is an error."""

    check_skill_bands(facts.skills)
    names = [slot.name for slot in slots]
    wrong = [name for name in SINGLE_SLOTS if names.count(name) != 1]
    if wrong:
        raise ValueError(f"the template must hold each of {', '.join(SINGLE_SLOTS)} once")

    banded = [name for slot in slots if slot.name == "agents" for name in slot.arguments]
    if len(set(banded)) != len(banded):
        raise ValueError("the template names an agent in two bands")
    rest_agents = [agent for agent in facts.agents if agent.name not in banded]
    agent_names = [agent.name for agent in facts.agents]
    default_role = DEFAULT_ROLE if DEFAULT_ROLE in agent_names else next(iter(agent_names), "")

    default_skill = DEFAULT_SKILL if DEFAULT_SKILL in facts.skills else SKILL_BANDS[0][1][0]

    return Layout(facts, rest_agents, default_role, default_skill)


def get_port_states(root: Path, script: str, /) -> dict[str, str]:  # keys are data: the port keys
    """Each port's state for one hook script: runs or off, from hooks/hooks.json and harness_port's own conversion, then PORT_NOTES."""

    port = import_path(root / "port" / "harness_port.py")
    events = json.loads((root / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    marker = f"hooks/{script}"
    groups = [
        (event, group)
        for event, event_groups in events.items()
        for group in event_groups
        if any(marker in command["command"] for command in group["hooks"])
    ]
    if not groups:
        raise ValueError(f"{script} is on a rule row but has no hook in hooks/hooks.json")

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


def add_port_badges(page: str, root: Path, /) -> str:
    """The page with a badge group after each rule row's hook script, and the port-notes table at its marker."""

    readme_lines = (root / "README.md").read_text(encoding="utf-8").splitlines()
    labels = {port.key: port.label for port in PORTS}
    note_rows = []
    for note in PORT_NOTES:
        found = [number for number, line in enumerate(readme_lines, start=1) if note.phrase in line]
        if len(found) != 1:
            raise ValueError(f"README.md must hold the phrase {note.phrase!r} on one line, found it on {found}")
        note_rows.append(
            f"<tr><td><code>{html.escape(note.script)}</code></td><td>{labels[note.target]}</td>"
            f"<td>{PORT_STATES[note.state]}</td><td>{html.escape(note.note)}</td>"
            f"<td>README.md line {found[0]}</td></tr>"
        )
    if page.count(PORT_NOTES_MARKER) != 1:
        raise ValueError(f"the template must hold {PORT_NOTES_MARKER} once")
    table = (
        '<table class="port-notes"><caption>What the port cannot show</caption>'
        '<thead><tr><th scope="col">Hook</th><th scope="col">Tool</th><th scope="col">State</th>'
        '<th scope="col">Note</th><th scope="col">Source</th></tr></thead>'
        f"<tbody>{''.join(note_rows)}</tbody></table>"
    )

    states_by_script = {script: get_port_states(root, script) for script in set(RULE_HOOK.findall(page))}
    parts = []
    position = 0
    for match in RULE_HOOK.finditer(page):
        states = states_by_script[match.group(1)]
        badges = []
        for port in PORTS:
            state = states[port.key]
            text = f"{port.label}: {PORT_STATES[state]}"
            badges.append(
                f'<span class="port-badge" data-state="{state}"><svg viewBox="0 0 12 12" role="img" '
                f'aria-label="{text}"><title>{text}</title><path d="{port.glyph}"/></svg>{port.label}</span>'
            )
        parts.append(page[position : match.end()])
        parts.append(f'<span class="port-badges" role="group" aria-label="Ported to">{"".join(badges)}</span>')
        position = match.end()
    parts.append(page[position:])

    return "".join(parts).replace(PORT_NOTES_MARKER, table)


def make_page(template: str, facts: Facts, /) -> str:
    """The page: the template with its fact tokens and then its slots filled."""

    with_facts = FACT.sub(lambda match: get_fact(facts.values, match.group(1)), template)
    slots = [Slot(match.group(1), tuple(match.group(2).split())) for match in SLOT.finditer(with_facts)]
    layout = make_layout(slots, facts)
    page = SLOT.sub(lambda match: make_slot(Slot(match.group(1), tuple(match.group(2).split())), layout), with_facts)
    check_hooks_shown(page, facts.hooks)
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
        page = add_port_badges(make_page((root / TEMPLATE).read_text(encoding="utf-8"), facts), root)
    except (ValueError, OSError, SyntaxError, ImportError) as error:
        print(f"build_map: {error}", file=sys.stderr)
        return 1
    if not arguments.check:
        target.write_text(page, encoding="utf-8", newline="\n")
        counts = ", ".join(f"{facts.values[key]} {key}" for key in ("agents", "skills", "hooks", "cases", "mutants"))
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
