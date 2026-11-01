---
name: review
description: How one unit of code or a design is reviewed against its spec - the order, severities A to C, the finding form, optional lenses, a layout audit, and the steps of a fix. Load to review a unit, to audit layout, or to fix a failing test or gate.
---

# Reviewing

A reviewer reads code against its spec or brief. It never edits, is never the author, does one round and does not
rewrite. Audit is different: `harness:audit` tests a report's claims, review reads the code.

## Order

1. **Spec:** each decision and non-goal of the spec or brief, found in the code or found missing. A change outside the
   write set is a finding.
2. **Correctness:** a wrong result or crash for an input inside the contract. Work two or three tiny inputs by hand: the
   empty one, one element, the largest allowed, one of each sign or kind. Resource use far past what the data needs.
   After a layout change, every old guard re-derived.
3. **Tests:** a required judge without a case; a test no plausible bug fails (true by construction, a duplicate, an
   oracle defined from the code under test); a tunable constant no test defends (`harness:testing`).
4. **Layout and style:** the project's rules and the style tools they name (the `code-*` skills and the project's
   gates). A "pure move" is checked by diffing the moved code at its old and new home with comments stripped.
5. **Docs:** a comment, docstring or README section false of the code.

## Severities

- **A:** a wrong result, a crash, a broken contract, a decision of the spec not met.
- **B:** a missing or futile test, a breach of layout or style the unit introduced, resource use past the budget. A and
  B block acceptance.
- **C:** wording and taste. Never blocks.
- A breach already present before the unit is **inherited**: listed with its rule, never blocking.

## A finding

One entry: `path:line` with the line's text (lines move), the severity, the input or sequence that shows it (or why no
test would catch it), a one-line fix. Findings are sorted A, B, C. A suspicion without such an input is reported as
unsure, not as a finding. Agreement with another reviewer is not evidence (`harness:evidence`).

## Lenses a brief may add

- **Maths:** for each claim of correctness in all cases, an optimality claim or a "never worse" claim, the proof, the
  input that breaks it, and whether the code does what the proof assumes (order of operations, precision, ties, boundary
  values, a size that does not divide evenly).
- **Concurrency:** shared state, ordering, a resource released on every path, a retry that repeats a side effect.
- **Interface:** what a caller can now do that it could not, an old caller that breaks, a name that lies.
- **Security:** untrusted input reaching a shell, path, query or template; a secret in a log.

## The periodic layout audit

After a big job, with no unit in progress, read-only agents each take a folder; nothing is edited. Per cell, read the
outline (`grep -n '^def \|^class \|^function \|^export '` or the language's equivalent) and run the style tools. Every
type, function and constant sits in the module whose job it is: used only elsewhere, or a job another module names, is a
move; so are a second job in a module and near-duplicates. Return a move list (name, `path:line` from, module to,
rule), then splits and merges.

## Fixing a failure

1. **Reproduce** with the smallest case (one test id, one input); one you cannot reproduce is reported.
2. **Read the failure** (summary and last frames; one error at one line is one cause) and **find the cause** (the line
   and the input; probe if reading cannot settle it) before changing code.
3. **Fix it in the unit that made it,** not where it shows. Never loosen a test, bound or tolerance, never guard
   downstream of the bug. A failure outside your write set is reported, not fixed.
4. **Grep the callers,** verify again once. Stop after the third failing run and report what fails, the cause and what
   you tried. A failed call is split, never retried unchanged.
