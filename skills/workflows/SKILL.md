---
name: workflows
description: Load when framing a job. Picks the size tier (small, medium, large) with its steps, the job shape (scout fan-out, bug fix, spec-first feature, visual build, spike, parallel build, hillclimb), and between parallel Agent calls and the Workflow tool.
---

# Size tiers and job shapes

Pick the tier, then the shape. This skill holds the steps only. Who does what, the brief and how agents run are in
`harness:orchestrator`. A **unit** is one change that one worker can finish in the files its brief names.

## Size tiers

| Tier | Is | Steps |
|---|---|---|
| Small | one file, no public contract | one worker, the gates |
| Medium | one unit across several files, no public contract | read-back, one worker, run the product, the gates, one reviewer |
| Large | several units, or any public contract | the numbered steps below |

Large:

1. Read-back for the round.
2. A spec, written by a worker from the main session's decisions, then a cold read of it (`harness:spec`).
3. One worker scripts everything mechanical.
4. The shared plumbing and each serial step, one worker each; then the independent units (Parallel build below).
5. Run the product: a smoke test first, then the gates.
6. One reviewer reads the whole diff, once, at the end (`harness:review`); workers apply the fixes.
7. The full test, in the background when it is long.

The gates are the project's checks, named in its `AGENTS.md`. The product runs before any review, and polish waits
until it runs.

## Scout fan-out: settle facts

Use when the job rests on facts nobody has checked. A fact one `rg` or one read settles is read by the main session,
without a scout.

1. One `scout` per question, all in one message. Each answers one narrow question with `path:line` evidence
   (`harness:evidence`). Cut the fan-out along an area, or along a kind of problem across a wider area (redefined
   helpers, false comments, dead code, docs against code). A cell (`harness:review`) is one scout's slice; a **wave** is
   the cells launched in one message, never over files another agent is editing. The brief is the question, the files
   and a ready grep. A question about a syntax pattern (every call, every decorator) is a parse of the syntax tree,
   never a regex.
2. Check each answer against the tree before using it. Two scouts that disagree are re-asked with the other's claim.
   Merge duplicates and hand the owner only the checked claims and how many were false.
3. Write the settled facts into the brief or the spec.

## Bug fix: a failing test first

1. A bug claim is probed before any fix (`harness:evidence`).
2. Write a test that fails for the reported cause, and run it.
3. Fix the code with the test unchanged.
4. Gates. The test stays.

## Spec-first feature

1. The spec (`harness:spec`): goal, non-goals, decisions, files, judges.
2. A cold read of the spec (`harness:spec`); settle the differences.
3. Build against the judges, run the product, then one reviewer reads against the spec.

## Visual or interactive build

A game, page, dashboard or UI: offer mocks and choose the look before any build: `references/explore.md`.

## Spike

Use when the way is unknown.

1. Build it in `/tmp/harness/<project>/`, loosely.
2. Prove it works with a judge (`harness:testing`); show the judge fails under a deliberate bug.
3. Freeze the judge as a test in the project, and record the judge file's sha256 (`sha256sum <file>`) in the report
   at the freeze.
4. Clean the code into place with the judge unchanged. At the end of clean-up compare the file's sha256 with the
   recorded one; a difference is a breach: no commit happens between freeze and clean-up, so git cannot show a change.
5. A reviewer confirms behaviour did not change: same judge, same output on the same inputs.

## Parallel build

Use when units are independent.

1. Contract: one file naming each unit, its files, the names shared between units, the judges.
2. A cold read of the contract (`harness:spec`).
3. Disjoint files: no path appears in two units. A change needed in another unit's file is reported, not made.
4. Split by work, not by topic: many fixes in one file, a rewrite and a measurement are three units. Start each unit as
   soon as what it needs exists, the slowest first and on its own files, and check finished units while others build.
5. Check each unit's judges.
6. Integrate: one worker wires the units together and owns the shared files.
7. Run the product and the full check, then one reviewer reads the whole diff.

## Hillclimb

Use when a metric can judge each change: one change, one measurement, keep or revert, until a stop predicate holds.
Steps and the log: `references/hillclimb.md`.

## Whole-repo self-audit

A sweep of a repo's rules, docs and checks against each other: `harness:review` (its sweep reference).

## Parallel Agent calls or the Workflow tool

- Parallel Agent calls: a known set of jobs whose results you read yourself.
- The Workflow tool: control flow that must be deterministic (a loop, a fan-out over a list found at run time, a
  verify stage per item). It needs the owner's explicit opt-in; never start one unasked. Its script's shape:
  `references/dynamic.md`.
- Hybrid: scout the work list first with plain calls, then pass it to the workflow as `args`.
