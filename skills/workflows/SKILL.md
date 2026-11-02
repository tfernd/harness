---
name: workflows
description: Load when framing a job. Picks the job shape (scout fan-out, bug fix, spec-first feature, spike, parallel build), the size tier (small, medium, large), and between parallel Agent calls and the Workflow tool, with a pointer to the shape of a dynamic workflow.
---

# Job shapes and size tiers

Pick the shape, then the tier. The main session follows `harness:orchestrator`: it does each step itself unless the
step names an agent or its cost rules say one pays.
A **unit** is one change that one worker can finish inside one write set.

## Size tiers

| Tier | Is | Steps |
|---|---|---|
| Small | one file, no public contract | edit, gates |
| Medium | one unit across 2 or more files, no public contract | read-back, edit (a script if repetitive), run it, gates, one reviewer |
| Large | several units, or any public contract | the numbered steps below |

Large steps, each with its owner:

1. Read-back and a budget for the round (main session).
2. Spec (main session), with one cold reader when a worker will build from it.
3. A script for everything mechanical (main session).
4. The plumbing and every serial step (main session); parallel workers only for units that are independent and large.
5. Run the product: a smoke test first, then the gates (main session).
6. One review of the whole diff, high severity only (reviewer), then each fix (main session).
7. Full test (main session, or a runner when it is long).

The read-back is one sentence of what stays and what goes (`harness:orchestrator`). The gates are the project's checks,
named in its `AGENTS.md`.

## Scout fan-out: settle facts

Use when the job rests on facts nobody has checked.

A fact one `rg` or one read settles is read here, without a scout.

1. One `scout` per question, Haiku, all in one message. Each answers one narrow question with `path:line` evidence
   (`harness:evidence`).
2. Check each answer against the tree before using it. Two scouts that disagree are re-asked with the other's claim.
3. Write the settled facts into the brief or the spec.

## Bug fix: a failing test first

1. Write a test that fails for the reported cause, and run it.
2. Fix the code with the test unchanged.
3. Gates. The test stays.

A bug claim is probed before any fix (`harness:evidence`).

## Spec-first feature

1. Write the spec (`harness:spec`): goal, non-goals, decisions, write sets, judges.
2. Cold read of the spec as a brief (`harness:cold-read`); settle the differences.
3. Build against the judges, with workers only where parallel pays. Run the product, then one reviewer reads against
   the spec (`harness:review`).

## Spike

Use when the way is unknown.

1. Build it in the scratch folder, loosely.
2. Prove it works with a judge (`harness:testing`); show the judge fails under a deliberate bug.
3. Freeze the judge as a test in the project, and record the judge file's sha256 (`sha256sum <file>`) in the report
   at the freeze.
4. Clean the code into place with the judge unchanged. At the end of clean-up compare the file's sha256 with the
   recorded one; a difference is a breach: no commit happens between freeze and clean-up, so git cannot show a change.
5. A reviewer confirms behaviour did not change: same judge, same output on the same inputs.

## Parallel build

Use when units are independent.

1. Contract: one file naming each unit, its write set, names shared between units, the judges.
2. Cold read of the contract.
3. Disjoint write sets: no path appears in two. A change needed outside a write set is reported, not made.
4. Workers run in one message, in the background.
5. Check each unit's judges.
6. Integrate: the main session wires the units together and owns the shared files.
7. Run the product and the full check, then one reviewer reads the whole diff.

## Parallel Agent calls or the Workflow tool

- Use parallel Agent calls for a known, small set of jobs (about 20 or fewer) whose results you read yourself.
- Use the Workflow tool for control flow that must be deterministic: a loop, a fan-out over a list found at run time,
  a verify stage per item. It needs the owner's explicit opt-in; never start one unasked.
- Hybrid: scout the work list first with plain calls, then pass it to the workflow as `args`.

## Parallel without waste

- Split by time, not by topic: a unit an agent cannot finish in 10 minutes is split before it goes out (this sizes work; the 10 minutes of
  `harness:orchestrator` are a stall check on a running agent). Many fixes in one file, a rewrite and a measurement are three units.
- Every brief states a budget in minutes, and asks for a partial report when it runs out: done, not done, what is on disk. A stopped agent with no report leaves the main session guessing.
- At the budget, check the tree (run the judges) instead of waiting; work on disk counts.
- Never hold fast units for a slow one. Start each stage's units as soon as what they need exists; audit finished units while others still build.
- Give the slowest unit its own write set and start it first, so it does not gate the rest.
- A stronger model buys judgment, not speed: step up for a hard decision, not for a large job (`harness:models`).
- Tell the owner the expected time and tokens at launch, and say so as soon as a unit runs over.

The shape of a dynamic workflow script: `references/dynamic.md`.
