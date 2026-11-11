# Writing a skill

A skill is read by an agent in the middle of a job. It must be short, general and checkable.

## Form

- `skills/<name>/SKILL.md`, `name` equal to the folder. Frontmatter holds `name` and `description` only.
- **Description:** what the skill gives, then when to load it ("Load
  before ..."). The description is the only text an agent sees when deciding; a vague one means a skill never loads.
- **Body:** at most 150 lines, a title, short sections, tables for lookups, steps for procedures. Detail that only
  some readers need goes in `references/<file>`, named from the body so a reader knows when to open it.
- A `references/<file>` names only the skill's own folder.
- Write for an agent with the skill and nothing else: no "as discussed", no history of how the rule came about.

## Content

- **No project domain.** A skill is a general starter, never one repo's taste. Names of people, machines, private
  projects or domains do not belong in a public one; a project's own rules go in its `AGENTS.md`.
- **One home per fact.** State a fact once; elsewhere point to it by its full skill name (for example `harness:testing`). Two copies drift apart.
  Before writing, search the other skills for the fact; if it exists, point to it.
- **Rules a checker can test,** in the imperative, each with its reason when the reason is not obvious.
- **A "What no tool checks" section** closes a skill whose rules a tool only half checks: it names what the reader
  must judge by reading, so nobody trusts a green run for it.
- **Write short.** Cut a sentence that restates the heading. A table beats three paragraphs of options.

## Keeping it true

- **A rule that keeps failing becomes a hook.** If agents break the same rule twice with the skill loaded, text is the
  wrong tool: propose a check (`hook.md`).
  Then shorten the skill to the line the hook cannot enforce.
- **Test a skill cold:** give a fresh agent only the skill and a task, and list what it had to guess. Each guess is a missing line.
- When a skill grows past the limit, move detail to `references/` before cutting rules.
- The project's skill check (a script that reads frontmatter, lengths and every pointer) runs before pushing.

## What no tool checks

Whether the description makes an agent load the skill at the right moment, whether a rule is general or one repo's
habit in disguise, and whether the body is short because it is clear or because it left something out.
