---
name: workflows
description: Load when framing a job. Picks the job shape (scout fan-out, bug fix, spec-first feature, spike, parallel build), the size tier (small, medium, large), and between parallel Agent calls and the Workflow tool, with how a dynamic workflow is shaped.
---

# Job shapes and size tiers

Pick the shape, then the tier. The main session follows `harness:orchestrator`; each step below goes to an agent.

## Size tiers

| Tier | Is | Steps |
|---|---|---|
| Small | one file, no public contract | worker, gates |
| Medium | one unit | read-back, brief, one cold read, worker, gates, review |
| Large | several units, or a public contract | read-back, spec, two cold readers, spec review, parallel workers, gates, audit, review and fix, integrate, audit, full test |

The read-back is one sentence of what stays and what goes (`harness:orchestrator`). The gates are the project's checks,
named in its `AGENTS.md`.

## Scout fan-out: settle facts

Use when the job rests on facts nobody has checked.

1. One `scout` per question, Haiku, all in one message. Each answers one narrow question with `path:line` evidence
   (`harness:evidence`).
2. Check each answer against the tree before using it. Two scouts that disagree are re-asked with the other's claim.
3. Write the settled facts into the brief or the spec.

## Bug fix: a failing test first

1. A worker writes a test that fails for the reported cause, runs it, and reports the failure text.
2. A different worker (or the same one, in a second brief) fixes the code with the test unchanged.
3. Gates; reviewer. The test stays.

A bug claim is probed before any fix (`harness:evidence`).

## Spec-first feature

1. Write the spec (`harness:spec`): goal, non-goals, decisions, write sets, judges.
2. Cold read of the spec as a brief (`harness:cold-read`); settle the differences.
3. Workers build against the judges. Reviewer reads against the spec (`harness:review`).

## Spike

Use when the way is unknown.

1. Build it in the scratch folder, loosely.
2. Prove it works with a judge (`harness:testing`); show the judge fails under a deliberate bug.
3. Freeze the judge as a test in the project, and record the judge file's sha256 (`sha256sum <file>`) in the report
   at the freeze.
4. Clean the code into place with the judge unchanged. At the end of clean-up compare the file's sha256 with the
   recorded one; a difference is a breach, since the owner commits and git cannot show it.
5. A reviewer confirms behaviour did not change: same judge, same output on the same inputs.

## Parallel build

Use when units are independent.

1. Contract: one file naming each unit, its write set, names shared between units, the judges.
2. Cold read of the contract (two readers on a large job).
3. Disjoint write sets: no path appears in two. A change needed outside a write set is reported, not made.
4. Workers run in one message, in the background.
5. Check each unit's judges; audit each report (`harness:audit`).
6. Integrate: one agent wires the units together and owns the shared files.
7. Audit again; run the full check through a `runner`.

## Parallel Agent calls or the Workflow tool

- Use parallel Agent calls for a known, small set of jobs (about 20 or fewer) whose results you read yourself.
- Use the Workflow tool for control flow that must be deterministic: a loop, a fan-out over a list found at run time,
  a verify stage per item. It needs the owner's explicit opt-in; never start one unasked.
- Hybrid: scout the work list first with plain calls, then pass it to the workflow as `args`.

## Parallel without waste

- Split by time, not by topic: a unit an agent cannot finish in 10 minutes is split before it goes out. Many fixes in one file, a rewrite and a measurement are three units.
- Every brief states a budget in minutes, and asks for a partial report when it runs out: done, not done, what is on disk. A stopped agent with no report leaves the main session guessing.
- At the budget, check the tree (run the judges) instead of waiting; work on disk counts.
- Never hold fast units for a slow one. Start each stage's units as soon as what they need exists; audit finished units while others still build.
- Give the slowest unit its own write set and start it first, so it does not gate the rest.
- A stronger model buys judgment, not speed: step up for a hard decision, not for a large job (`harness:models`).
- Tell the owner the expected time at launch, and say so as soon as a unit runs over.
- Brief every agent to read and edit in bulk with one Python call per step, and to test once when its unit is done.

## Shape of a dynamic workflow

Facts below are from the `workflow-authoring` skill (load it with the Skill tool before writing a script; it is not a
plugin skill).

- A script starts with `export const meta = {name, description, phases}`, a pure literal.
- Default to `pipeline(items, stage1, stage2)`: each item moves through its stages with no barrier. Use `parallel`
  (a barrier) only when a stage needs every earlier result: dedup, early exit, comparison between findings.
- One pipeline per item: find, then verify, then act.
- Adversarial verify: several skeptics per finding, each told to refute; keep the finding when a majority fails to.
  Give each a different lens (correctness, reproduction, impact) when the finding can fail in more than one way.
- Pass a `schema` to `agent()` for structured output; it returns the validated object. Without one it returns text.
- `agent()` returns null on a skipped or dead agent: filter with `.filter(Boolean)`.
- No `Date.now()` or `Math.random()` in the script; pass timestamps through `args`.
- Resume: relaunch with `{scriptPath, resumeFromRunId}`; the unchanged prefix of calls returns cached results.
- Log what a cap drops; never truncate silently.
- Worktree isolation only for agents that edit in parallel and would conflict.
