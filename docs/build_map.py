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
# The events whose hooks run on a tool call, so their matcher names tools.
TOOL_EVENTS = frozenset({"PreToolUse", "PostToolUse"})
# A hooks.json command's script under `hooks/` and its first argument, if any.
HOOK_COMMAND = re.compile(r"hooks/([\w-]+\.py)\"?(?:\s+(\S+))?")
SLOT = re.compile(r"<!-- @([a-z-]+)([^>]*?) -->")
FACT = re.compile(r"\{\{(\w+)\}\}")
LIST_ITEM = re.compile(r"\s+- (.+)")
SENTENCE_END = re.compile(r"(?<=\.)\s+(?=[A-Z])")
# Where a skill's description stops being its summary: a spaced dash, a colon or a sentence end.
SUMMARY_END = re.compile(r" - |: |\. ")
# Characters of a skill summary before it is cut at a word; longer, it reads as a paragraph in a tooltip.
MAX_SUMMARY = 110
# Characters of each differing line the --check reason shows, from a little before the first changed character.
SNIPPET = 60
SNIPPET_LEAD = 20
# The slots the template must hold exactly once.
SINGLE_SLOTS = ("hooks-rest", "agents-rest", "agent-cards", "skills")


class Agent(NamedTuple):
    """One agent file's facts."""

    name: str
    model: str
    tools: tuple[str, ...]
    skills: tuple[str, ...]
    job: str  # the description's first sentence
    use: str  # its sentence on when to use the agent, empty when it has none


class Hook(NamedTuple):
    """One command of the hook list."""

    event: str
    matcher: str  # the tools it runs on, `|`-separated; empty for every tool
    script: str
    argument: str  # empty when the command passes none


class Facts(NamedTuple):
    """What the page shows from the repository."""

    agents: tuple[Agent, ...]
    skills: dict[str, str]  # keys are data: a skill's name to its summary
    hooks: tuple[Hook, ...]
    budgets: dict[str, int]  # keys are data: a role to its default turns, `*` for any other
    required: dict[str, list[str]]  # keys are data: a role to the lines its brief needs, `*` for any other
    values: dict[str, str]  # keys are data: a `{{fact}}` token's name to its text


class Slot(NamedTuple):
    """A `<!-- @name arguments -->` marker of the template."""

    name: str
    arguments: tuple[str, ...]


class Layout(NamedTuple):
    """Where each fact goes: the facts, the hooks each hook slot holds, the leftovers and the role shown first."""

    facts: Facts
    placed_hooks: dict[Slot, list[Hook]]
    rest_hooks: list[Hook]
    rest_agents: list[Agent]
    default_role: str


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


def get_summary(description: str, /) -> str:
    """A skill description's opening clause, cut at a word past MAX_SUMMARY characters."""

    clause = SUMMARY_END.split(description, maxsplit=1)[0].rstrip(".")
    if len(clause) <= MAX_SUMMARY:
        return clause

    return clause[:MAX_SUMMARY].rsplit(" ", 1)[0] + "…"


def get_skills(root: Path, /) -> dict[str, str]:  # keys are data
    """Every skill's name and summary, in folder name order."""

    skills = {}
    for path in sorted((root / "skills").glob("*/SKILL.md")):
        fields = read_frontmatter(path)
        skills[get_text(fields, "name", path)] = get_summary(get_text(fields, "description", path))

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


def get_repo_settings(root: Path, /) -> dict[str, str]:  # keys are data: fact token names
    """Whether this repository's own `.harness.json` turns on each optional rule the page names."""

    path = root / ".harness.json"
    if not path.is_file():
        return dict.fromkeys(("repo_commit", "repo_lock", "repo_packages", "repo_scratch", "repo_delegate"), "off")
    config = json.loads(path.read_text(encoding="utf-8"))
    guard = config.get("guard") or {}
    scratch = str(guard.get("scratch") or "").strip("./")

    return {
        "repo_commit": "off" if guard.get("commit_style") is False else "on",
        "repo_lock": "on" if guard.get("lock") else "off",
        "repo_packages": "on" if guard.get("ask_packages") or guard.get("deny_packages") else "off",
        "repo_scratch": f"{scratch}/" if scratch else "off",
        "repo_delegate": "on" if "delegate" in config else "off",
    }


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
        **get_repo_settings(root),
    }

    return Facts(agents, skills, hooks, budgets, required, {key: str(value) for key, value in values.items()})


# =========================================================================== #
# Rendering
# =========================================================================== #


def make_hook_pill(hook: Hook, /) -> str:
    """A hook's pill: its script and argument, a class per script and argument for its tone, its tools as a tooltip."""

    stem = hook.script.removesuffix(".py").replace("_", "-")
    classes = f"hook-pill hook-{stem}" + (f" hook-{stem}-{hook.argument}" if hook.argument else "")
    tools = ", ".join(hook.matcher.split("|")) if hook.matcher else "every tool"
    title = f' title="on {tools}"' if hook.event in TOOL_EVENTS else ""
    label = f"{hook.script} {hook.argument}".strip()

    return f'<span class="{html.escape(classes)}"{html.escape(title, quote=False)}>{html.escape(label)}</span>'


def make_rest_step(hooks: list[Hook], /) -> str:
    """A timeline step for the hooks no slot placed, empty when there are none."""

    if not hooks:
        return ""
    pills = "\n".join(f'<span class="hook-when">{html.escape(hook.event)}</span>{make_hook_pill(hook)}' for hook in hooks)

    return (
        '<li class="card timeline-step"><h3 class="timeline-title">Other hooks</h3>'
        '<p class="timeline-text">Hooks this map does not place in a step yet.</p>'
        f'<div class="hook-row">{pills}</div></li>'
    )


def make_agent_chip(agent: Agent, /, *, is_default: bool) -> str:
    """An agent's chip in its band: the button that shows its card."""

    name = html.escape(agent.name)

    return (
        f'<button type="button" class="crew-chip" data-choice="{name}" aria-pressed="{str(is_default).lower()}" '
        f'aria-controls="role-{name}">{name} <span class="crew-chip-model">{html.escape(agent.model)}</span></button>'
    )


def make_skill_chips(names: Iterable[str], skills: dict[str, str], /) -> str:
    """A chip per skill name with its summary as the tooltip; a name with no skill file is an error."""

    chips = []
    for name in names:
        if name not in skills:
            raise ValueError(f"the map names the skill {name!r}, which has no skills/{name}/SKILL.md")
        chips.append(f'<span class="skill-chip" title="{html.escape(skills[name])}">{html.escape(name)}</span>')

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


def make_skill_list(skills: dict[str, str], /) -> str:
    """The index of every skill: its name and summary."""

    return "\n".join(
        f'<div class="skill-entry"><dt><code>{html.escape(name)}</code></dt><dd class="skill-entry-text">{html.escape(summary)}</dd></div>'
        for name, summary in skills.items()
    )


def make_slot(slot: Slot, layout: Layout, /) -> str:
    """The markup that replaces one slot of the template."""

    match slot.name:
        case "hooks":
            return "\n".join(make_hook_pill(hook) for hook in layout.placed_hooks[slot])
        case "hooks-rest":
            return make_rest_step(layout.rest_hooks)
        case "agents":
            return make_agent_chips(slot, layout)
        case "agents-rest":
            return make_rest_band(layout)
        case "agent-cards":
            return "\n".join(make_agent_card(agent, layout.facts, is_default=agent.name == layout.default_role) for agent in layout.facts.agents)
        case "skills":
            return make_skill_list(layout.facts.skills)
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


def get_hook_slot(hook: Hook, slots: list[Slot], /) -> Slot | None:
    """The first hook slot of the hook's event that names one of its tools, else the first naming none, else None."""

    tools = set(hook.matcher.split("|"))
    same_event = [slot for slot in slots if slot.arguments[0] == hook.event]
    named = [slot for slot in same_event if len(slot.arguments) > 1 and tools & set(slot.arguments[1].split("|"))]
    plain = [slot for slot in same_event if len(slot.arguments) == 1]

    return next(iter(named + plain), None)


def make_layout(slots: list[Slot], facts: Facts, /) -> Layout:
    """Place each hook in its slot and find the agents no band names; a slot used wrongly is an error."""

    names = [slot.name for slot in slots]
    wrong = [name for name in SINGLE_SLOTS if names.count(name) != 1]
    hook_slots = [slot for slot in slots if slot.name == "hooks"]
    if wrong or any(not slot.arguments for slot in hook_slots) or len(set(hook_slots)) != len(hook_slots):
        raise ValueError(f"the template must hold each of {', '.join(SINGLE_SLOTS)} once and each hook slot once, with its event")

    placed: dict[Slot, list[Hook]] = {slot: [] for slot in hook_slots}
    rest_hooks = []
    for hook in facts.hooks:
        slot = get_hook_slot(hook, hook_slots)
        (placed[slot] if slot else rest_hooks).append(hook)
    banded = [name for slot in slots if slot.name == "agents" for name in slot.arguments]
    if len(set(banded)) != len(banded):
        raise ValueError("the template names an agent in two bands")
    rest_agents = [agent for agent in facts.agents if agent.name not in banded]
    agent_names = [agent.name for agent in facts.agents]
    default_role = DEFAULT_ROLE if DEFAULT_ROLE in agent_names else next(iter(agent_names), "")

    return Layout(facts, placed, rest_hooks, rest_agents, default_role)


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
        page = make_page((root / TEMPLATE).read_text(encoding="utf-8"), facts)
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
