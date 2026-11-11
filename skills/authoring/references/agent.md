# Writing an agent

An agent is a role: a fixed tool set, model and skill set, and a short standing order. The brief gives it the task.

## The file

`agents/<name>.md`, frontmatter then a body.

| Field | Rule |
|---|---|
| `name` | Equal to the file name |
| `description` | When to use the role and when not; the main session reads it to choose |
| `tools` | The least the job needs: a reader gets read tools, a writer adds Edit and Write, `Skill` only if it loads skills |
| `model` | By role: the cheapest model that does the job (`harness:orchestrator`, Models) |
| `skills` | Preloaded skills, always including `report`, so every run ends in the report form |

`hooks`, `mcpServers` and `permissionMode` are ignored in a plugin agent: never use them. A rule an agent must follow
goes in the plugin's hooks, which apply to every agent.

## The body

Short, in the imperative, in three parts:

1. **What it does:** one sentence, the one thing the role is for.
2. **What it never does:** the limits that keep roles apart (a reader writes nothing; a worker stays inside its write
   set; no git or gh command that writes).
3. **What goes under Answer:** the content its report carries (files changed, probes with their commands, each judge with
   its exit code). The report form itself is `harness:report`.

Do not repeat what a preloaded skill says; point to it by its full skill name (for example `harness:report`).

## A new role is added to the project's role tables

One role appears in several lists. Add it to each, in the same change, or a gate or a page will not know it:

- the models table (`harness:orchestrator`, Models),
- the orchestrator's roles table (`harness:orchestrator`),
- the hook budget table (the default turns per role),
- the project's page or docs that list agents.

The exact files for this repo are in its `AGENTS.md`.

## What no tool checks

Whether the tool list is the least that works, and whether the role is distinct from an existing one. Before adding a
role, check that a brief to an existing role could not do the job.
