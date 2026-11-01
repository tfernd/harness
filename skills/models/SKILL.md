---
name: models
description: Which Claude model each harness role runs on, what each of Haiku 5.5, Sonnet 5.5 and Opus 5.5 is suited to, and when a brief steps up. Load before choosing a model for an agent or brief, or when a role's model is questioned.
---

# Models

Documented facts below carry their URL. Measured facts live in `references/measured.md`; never present one as the other.
Model IDs: `claude-haiku-5-5`, `claude-sonnet-5-5`, `claude-opus-5-5`.

## Documented (official docs)

Source for the table: https://platform.claude.com/docs/en/about-claude/models/overview (fetched when this skill was written;
prices and the Fable id below are documented as of that fetch, so refetch before relying on them).

| | Haiku 5.5 | Sonnet 5.5 | Opus 5.5 |
|---|---|---|---|
| Docs' description | high-volume, latency-sensitive: classification, extraction, routing | best combination of speed and intelligence | long-running agentic coding and knowledge work |
| Latency | fastest | fast | moderate |
| Price per M tokens, in / out | from $0.10 / $0.50 | $2 / $10 | $4 / $20 |
| Default effort | `medium` | `high` | `medium` |
| Thinking | adaptive | adaptive | adaptive, always on |
| Context / max output | 1M / 128K | 1M / 128K | 1M / 128K |

- Pricing source for the Haiku long-prompt tier ($0.50 / $2.50 beyond 100K prompt tokens): the `claude-api` skill's cached
  model table, from the pricing page https://platform.claude.com/docs/en/about-claude/pricing.
- What limits each model is not published as a list of weaknesses. The docs give three relations, and only these are
  documented: speed falls and price rises from Haiku to Sonnet to Opus; Opus 5.5 is the starting point "for most
  workloads"; Fable 5.1 is the step above Opus when evals at `xhigh` or `max` effort still fall short
  (https://platform.claude.com/docs/en/about-claude/models/choosing-a-model).
- Effort is a lever within one model: "tuning effort is often a better lever than switching models" (same page).
  Haiku 5.5 is listed for "subagent tasks" in that page's selection matrix.
- The docs advise starting efficiency-first on Haiku and upgrading "only if necessary for specific capability gaps", or
  capability-first on Opus and lowering effort or model later (same page). Both need an eval of your own.

## Roles

This table is the single source of each role's model (`harness:orchestrator` points here). A role's model is set in
`agents/<name>.md` (`model:` is the alias `haiku` or `sonnet`); the worker default is Sonnet; no role defaults to Opus.

| Role | Model | Why |
|---|---|---|
| scout | haiku | one narrow fact with a quoted line; cheap and fast |
| runner | haiku | runs listed commands, edits nothing |
| cold-reader | sonnet | measured: Sonnet readers forced to quote lines had 0 of 43 false claims (see measured) |
| worker | sonnet | edits code inside a write set; wrong code costs more than the model price |
| reviewer | sonnet | reads code against its spec |
| auditor | sonnet | re-runs judges and marks report claims true or false |

The orchestrator itself (the main session) runs on the model the owner chose. A role below is a default, not a proof:
a role's choice is revisited when `harness:retro` shows its audit grades below its self-scores.

## When a brief steps up

A brief passes `model: opus` for one agent only on a named trigger, written in the brief:

1. The same unit came back twice with a failure whose retro cause is `the agent itself` and whose brief held no gap.
2. The unit is a design or a public contract with several valid answers, not an edit with a known shape.
3. The judge cannot be run by the agent, so only reasoning can catch the error.

A brief gap is never fixed by a bigger model: fix the brief (`harness:cold-read`). Step back down after the unit.
Lowering effort before changing model is the documented first lever; the session's effort is the owner's setting.

## Keeping this skill true

- An unmeasured default stays valid until a ledger table disagrees with it.
- Re-run `bin/harness-import` and the measured query `references/by_model.py` (usage in `references/measured.md`) after a large batch of reports.
- A measured claim needs its sample size and its confound; drop it when the sample is under 10 and nothing else backs it.
- Change a role's model only with a ledger table behind it, in the same edit as the agent file.
