---
name: authoring
description: How to write the plugin's own parts - a skill, a sub-agent file or a hook - form, limits, one home per fact, least tools, fail open, and the proof a rule needs. Load before adding, changing, shortening or reviewing a SKILL.md, an agents/*.md file or a hook in any plugin or project.
---

# Authoring

Open the file for the part you write; each is short and general.

| Part | Open | Holds |
|---|---|---|
| A skill (`skills/<name>/SKILL.md`) | `references/skill.md` | frontmatter, the description, body limit, one home per fact, no project domain |
| A sub-agent (`agents/<name>.md`) | `references/agent.md` | frontmatter fields, least tools, model by role, the body, the tables a new role joins |
| A hook (`hooks/`) | `references/hook.md` | events, fail open, the time budget, soft against hard, what counts as built |

A rule an agent keeps breaking with its skill loaded becomes a hook; shorten the skill to the line the hook cannot
enforce. Code in a hook follows the language skill (`harness:code-python`).
