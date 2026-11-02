---
name: testing
description: What makes a judge (test, gate or check) good, how to prove a new judge can fail with a deliberate-bug control, and the facts that keep tests cheap and true. Load before writing or reviewing tests, or before trusting a passing run.
---

# Testing

A judge is any check that decides done: a test, a gate, a script. It is worth keeping only if it can fail.

## What makes a good test

- **It fails on a plausible bug,** named before writing it (a swapped argument, a lost sign, an off-by-one, a missing
  guard). A test you cannot name a bug for goes. Keep few tests, each asserting strictly.
- **One property,** named in the test's name and its one-line docstring. No test of a private helper, of an ordinary
  input check of a public entry, or of a property another test implies. What defines the public contract is tested.
- **An oracle by a different route:** comparing a function with another defined from it (an encoder against its own
  decoder) checks nothing. Use an independent computation: a plain loop, a trusted library, hand-built expected bytes
  or a hand-worked small case.
- **Never true by construction:** an inequality that also holds when the feature is missing (a `<=` met by a fallback
  to the worse method) is asserted strictly, or the equality that is the claim is.
- **A judge of a guard runs the guarded branch.** One that clears a cache also runs the warm path; one that warms up
  before it measures also has a cold case, or says in its docstring that the cold path is not judged. Example: a judge of `if cache_is_full: evict()` fills the
  cache past its limit and asserts the evicted entry is gone; a judge that only inserts one item never runs the branch.
- **Named edge cases,** each its own case: empty, one element, the boundary values of the type or range (minimum,
  maximum, zero, a value just past a limit), one of each sign or kind.
- **Tunable constants defended:** a constant someone could change for speed (a chunk size, a tolerance, a timeout) has a
  test that runs the real value and fails when the value breaks a property. One no test can defend is marked in the code
  and listed as open work.
- **Tolerances are measured:** a bound is measured at the test's own sizes and seeds before it is asserted, and its
  constant says what it counts and its margin. Never loosen one to make a run pass.
- **Deterministic:** seeded inputs, no clock, no network, no order dependence, no test that reads another's output.

## The control: a new judge is shown to fail

A judge that has never failed has not been shown to work. Before a new judge is accepted:

1. **Name the bug** the judge is for, and say which result the bug changes before running anything.
2. **Plant it in a copy,** never in the real source: copy the code under test into the scratch folder, apply the bug
   there, and point the judge at the copy (a path setting or an environment variable the project documents; with none, copy the module and import the copy by
   path, and if that is impossible report it under Open). A test that spawns a subprocess must pass the copy's path
   to it too.
3. **Run the judge:** it must fail, and fail on the bug's own assertion. Record the command and the failing line.
4. **Run it on the real source:** it must pass.

Ways a control proves nothing:

- It fails nothing: it ran the real source, or changed no value the judge reads.
- It breaks the import or setup, so every test fails for another reason.
- It degrades every case alike, so an order or a ratio cancels: aim it at one side.
- It changes something the judge does not read (a tie-break changes a choice, not a sum, so a sum judge cannot see it).

A judge of a hook, gate or script is shown the same way: plant the bug in a copy of that script and run its cases.

## Cheap and true

- A test's cost follows its number of heavy calls, not the size of the input. Tests that read the same default input
  share one cached result and never write into it.
- A slow or resource-hungry test carries the project's marker for the full tier, so the default run stays short.
- A case that skips says why and is counted: a silent skip is a pass nobody earned.
- A fixture is shared through the project's conftest; a helper module a test cannot import is a layout fact to probe,
  not to guess.
- An exact claim is compared for equality; a float claim has a measured relative bound.
- A test of a script that reads its environment clears those variables first, since the runner may set them.
- A run that cannot happen here (a missing tool or device) is listed under Not proven with the command for the owner,
  never replaced by a looser check.
- A passing run counts only for the code it ran. After a change, rerun; a run from before it is not evidence.
- More tips for writing a judge: `references/judge-tips.md`.

## Where judges come from

The spec names them per unit (`harness:spec`); a new kind of input joins the project's existing grid of cases rather
than getting its own file; the auditor re-runs them (`harness:audit`); the reviewer checks they could fail
(`harness:review`).
