---
name: authoring
description: How to write the plugin's own parts - a skill, a sub-agent file or a hook - form, one home per fact, least tools, fail open, the proof a rule needs, and what loads when. Load before adding, changing, shortening or reviewing a SKILL.md, an agents/*.md file or a hook in any plugin or project.
---

# Authoring

Open the file for the part you write; each is short and general.

| Part | Open | Holds |
|---|---|---|
| A skill (`skills/<name>/SKILL.md`) | `references/skill.md` | frontmatter, the description, the body, one home per fact, no project domain |
| A sub-agent (`agents/<name>.md`) | `references/agent.md` | frontmatter fields, least tools, model by role, the body, the table a new role joins |
| A hook (`hooks/`) | `references/hook.md` | events, fail open, the time budget, soft against hard, what counts as built |

A rule an agent keeps breaking with its skill loaded becomes a hook; shorten the skill to the line the hook cannot
enforce. Code in a hook follows the language skill (`harness:code-python`).

## What loads when

Text in front of an agent costs on every turn. Put a fact where its reader already looks, and nowhere else.

| When | Reader | What arrives | From |
|---|---|---|---|
| Session start | main session | a line to load `harness:orchestrator`, the ownership line, the `tool-habits` body, the setup line (search tools, shell, scratch folder) | `hooks/context.py` |
| Agent start | a harness role | its agent file and each skill in its `skills:` list, whole | `agents/<name>.md` |
| Agent start | every sub-agent | the `tool-habits` body without its Git section (a read-only role also loses the edit and clean sections) and the setup line; an agent that is no harness role also gets the report headings in one line | `hooks/context.py` |
| First edit of a kind of file, first commit | an agent that has not seen the skill | that skill's text, once | `hooks/skill_gate.py` |
| On demand | an agent with the Skill tool | a skill, chosen by its description; a `references/` file, read by path when the body names it | the agent |

So: a rule every agent needs goes in `tool-habits`; a rule one role needs goes in its agent file or a skill it
preloads; a rule the main session needs goes in `harness:orchestrator`; detail few readers need goes in a
`references/` file. A brief repeats none of these.
