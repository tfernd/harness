---
name: models
description: Which Claude model each harness role runs on, and when a brief steps a role up. Load before choosing a model for an agent or brief, or when a role's model is questioned.
---

# Models

Haiku is for narrow, mechanical work whose result a person or a script can check. Sonnet is for edits and judgement.
Opus is the step-up for design with several valid answers. Effort is a lever within one model; lower it before changing model.

## Roles

This table is the single source of each role's model (`harness:orchestrator` points here). A role's model is set in
`agents/<name>.md` (`model:` is the alias `haiku`, `sonnet` or `opus`); no role runs on Opus by default.

| Role | Model | Why |
|---|---|---|
| planner | sonnet | weighs options against the code it reads |
| cold-reader | sonnet | reads a brief and quotes a line per name |
| scout | haiku | one narrow fact with a quoted line |
| researcher | sonnet | weighs outside sources and separates documented from inferred |
| worker | sonnet | edits code inside a write set; wrong code costs more than the model |
| designer | sonnet | visual work inside a write set; Opus is the step-up for a hard case |
| releaser | sonnet | splits a diff into commit units and drafts the PR; the main session applies it |
| runner | haiku | runs listed commands, edits nothing |
| reviewer | sonnet | reads code against its spec |
| auditor | sonnet | re-runs judges and marks report claims true or false |

The orchestrator itself (the main session) runs on the model the owner chose. A role's model is a default, not a proof:
revisit it when the ledger shows it calling work `done` that audits grade low.

## When a brief changes a role's model

A brief steps a worker down to Haiku when every change is an exact rewrite with no judgement. It passes `model: opus` for
one agent only on a named trigger, written in the brief:

1. The same unit came back twice with a failure whose reported cause is `the agent itself` and whose brief held no gap.
2. The unit is a design or a public contract with several valid answers, not an edit with a known shape.
3. The judge cannot be run by the agent, so only reasoning can catch the error.

A brief gap is never fixed by a bigger model: fix the brief (`harness:cold-read`). Step back down after the unit.

## Keeping this skill true

- A measured claim needs its sample size and its confound; drop it when the sample is under 10 and nothing else backs it.
- Change a role's model only with a ledger table behind it, in the same edit as the agent file.
