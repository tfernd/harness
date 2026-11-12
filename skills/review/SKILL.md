---
name: review
description: How a unit, design, branch or pull request is reviewed against its spec - order, severities A to C, finding form, lenses, a layout survey; the worker's steps for fixing its own failing test or gate; how to find a bug's cause when it is not known (reproduce, hypotheses, bisect); and the whole-repo sweep. Load to review, to fix a failure, to debug, or to sweep a repo before a release.
---

# Reviewing

A reviewer reads code against its spec or brief. It never edits, is never the author, does one round and does not
rewrite. A report's own claims are checked by rerunning its Judge, not by review. A **cell** is one scout's
or reviewer's slice of a fan-out (a folder, or a kind of problem across files). Fixing a failure is the worker's job,
not the reviewer's: see the last section.

## Project review rules

Read first the "Review rules" section of the project's `AGENTS.md`, if it has one: what counts as A there, paths and
classes to skip (what CI already enforces), an "always check" list, and accepted issues. Detail: `references/rules.md`.

## Order

1. **Spec:** each decision and non-goal of the spec or brief, found in the code or found missing. A change in a file the brief
   does not name is a finding.
2. **Correctness:** a wrong result or crash for an input inside the contract. Work two or three tiny inputs by hand: the
   empty one, one element, the largest allowed, one of each sign or kind. Resource use far past what the data needs.
   After a layout change, every old guard re-derived.
3. **Tests:** a required judge without a case; a test no plausible bug fails (true by construction, a duplicate, an
   oracle defined from the code under test); a tunable constant no test defends (`harness:testing`).
4. **Layout and style:** the project's rules and the style tools they name (the `code-*` skills and the project's
   gates). A "pure move" is checked by diffing the moved code at its old and new home with comments stripped.
   A misleading, generic or abbreviated name, or a comment standing in for one, is a B finding (`harness:code`).
5. **Docs:** a README or docs section false of the code.

## Severities

- **A:** a wrong result, a crash, a broken contract, a decision of the spec not met.
- **B:** a missing or futile test, a breach of layout or style the unit introduced, resource use past the budget. A and
  B block acceptance.
- **C:** wording and taste. Never blocks.
- A review reports A only unless its brief asks for B or C; a brief for a unit that must meet the layout and test rules
  asks for B.
- A breach already present before the unit is **inherited**: listed with its rule, never blocking.

## Dropped by kind

- A finding that is only style, only a diagnostic a tool already prints, or only clean-up is dropped unless the brief asks for B or C.
- A claim about behaviour cites `path:line`; a guess from a name is unsure.

## Converging

- After the first pass, review only the diff since the last review.
- Name the class of a bug (for example "an unchecked path join") and list every instance, so one fix covers all.
- A review of a fix asks two more questions, each answered with an input: can the fix be bypassed, and does a variant
  of the bug remain.
- A unit that comes back with the same class of fault again is not converging: the main session stops and rethinks the
  approach with the owner.

## A finding

One entry: `path:line` with the line's text (lines move), the severity, the command that shows it with its output (or why
no test would catch it), a one-line fix. Findings are sorted A, B, C. A finding survives only with that command and
output; a suspicion without them is reported as unsure, not as a finding: unsure items go in a separate list after C.
The output must show the stated cause failing, not only that something fails. Rerun each finding's command on the
current tree just before reporting; one that no longer shows is reported as fixed, not as a finding.
"No findings" is a valid result; never pad a review to look thorough. The main session reruns a finding's command
before relaying it (`harness:orchestrator`, its accept reference).

## Lenses a brief may add (on its `Role:` line, for example `Role: reviewer, lens: Interface`)

- **Maths:** for each claim of correctness in all cases, an optimality claim or a "never worse" claim, the proof, the
  input that breaks it, and whether the code does what the proof assumes (order of operations, precision, ties, boundary
  values).
- **Concurrency:** shared state, ordering, a resource released on every path, a retry that repeats a side effect.
- **Interface:** what a caller can now do that it could not, an old caller that breaks, a name that lies.
- **Adversarial:** try to break the change with real inputs; detail in the adversary and matrix reference (`references/holes.md`).
- **Holes:** what the change promises that nothing checks; detail in the lens reference (`references/lenses.md`).
- **Drift:** which docs, examples or counts the change makes false; detail in the lens reference (`references/lenses.md`).
- **Security:** untrusted input reaching a shell, path, query or template; a secret in a log. Checklist and what not to report: `references/security.md`.

## The layout survey

After a big job, with no unit in progress, read-only agents each take a cell (a folder); nothing is edited. Per cell, read the
outline (`harness:evidence`) and run the style tools. Every
type, function and constant sits in the module whose job it is: used only elsewhere, or a job another module names, is a
move; so are a second job in a module and near-duplicates. Return a move list (name, `path:line` from, module to,
rule), then splits and merges.

## A branch or a pull request

One reviewer at the end reads the whole branch or pull request against its description, spec or issue, in the same order
and with the same findings. It reports and never posts comments, approves or merges: the owner decides what goes on the
pull request. Scope, run, read order and checklist: `references/branch.md`.

## Fixing a failure (the worker's job)

For the worker or author fixing its own failing test or gate; a reviewer only reports.

1. **Reproduce** with the smallest case (one test id, one input); one you cannot reproduce is reported.
2. **Read the failure** (summary and last frames; one error at one line is one cause) and **find the cause** (the line
   and the input; probe if reading cannot settle it) before changing code.
3. **Fix it in the unit that made it,** not where it shows. Never loosen a test, bound or tolerance, never guard
   downstream of the bug. A failure in a file your brief does not name is reported, not fixed.
4. **Grep the callers,** verify again once. A failed call is split, never retried unchanged.

A third failing run of the judge stops the worker: it reports what fails, the cause and what it tried. Two failed fixes
on one hypothesis end the work too (`references/debug.md`).

## Finding a cause not yet known

Reproduce, one hypothesis at a time, bisect, fix the cause with a test that failed first: `references/debug.md`.

## Sweeping a repo against itself

A whole-repo self-audit (rules, docs, config and checks against each other), before a release or when the same problem comes back: `references/sweep.md`.
