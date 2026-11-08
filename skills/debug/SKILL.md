---
name: debug
description: How to find a bug's cause - reproduce, one hypothesis at a time, bisect, read the real error, fix the cause with a test that failed first. Load when something fails and the cause is not yet known, or before a second attempt at a fix.
---

# Debugging

Finding the cause. The job shape and the order "failing test, fix, gates" are in `harness:workflows` (Bug fix); the
claim ladder is `harness:evidence`. This skill is what happens before the test can be written.

## Reproduce first

- Get the failure to happen on demand before any theory. Keep the exact command, the input and the environment that
  fail; paste the command into the report.
- Shrink the reproduction: the fewest lines, the smallest input, one test instead of the suite. A reproduction that
  passes sometimes is not done: find what varies (order, time, concurrency, environment, a cache) and pin it.
- A failure you cannot reproduce is reported as such, with what you tried. It is not fixed by a guess.

## Read before you reason

- Read the whole error: the message, the first frame in the project's own code, and the last frame. The first line of
  a traceback is rarely the whole story; a wrapped error has a cause further down.
- Print the actual values at the failing line (inputs, types, lengths, the path really opened) before saying what they
  must be. Remove the print when done.
- Check what changed: `git log -p` and `git diff` over the files in the trace, and the lockfile and tool versions.

## One hypothesis at a time

- Write the hypothesis as one sentence, and beside it the observation that would refute it. A hypothesis with no such
  observation is not testable: rewrite it.
- Run the probe that can refute it, the smallest one. Record the result: refuted or standing.
- Change one thing between two runs. Two changes at once teach nothing.
- A refuted hypothesis is dropped, not patched to survive. Start the next from the new observation.

## Narrow by bisecting

- Over history: `git bisect start <bad> <good>` then `git bisect run <the reproduction command>`; the command must
  exit 0 when the commit is good, 1 to 127 (not 125) when it is bad, and 125 when it cannot be tested. End with `git bisect reset`.
- Over input: halve the input until the smallest failing piece remains.
- Over layers: test the boundary between two layers (what the caller sends, what the callee receives). The bug is on
  the side where the value first goes wrong.
- Over code: disable half of a pipeline or config and see which half still fails.

## Fix the cause

- The cause is the earliest point where a value or a state leaves its contract, not the line that raised.
- Write the test that fails for that cause and run it to see it fail for that reason (`harness:testing`). Fix with the
  test unchanged. A test that passes before the fix proves nothing.
- Then look for the same cause elsewhere: grep for the same call, pattern or assumption, and fix or report each.
- Do not add a catch, a default, a retry or a sleep to silence the failure unless the cause is that missing handling.

## A symptom patch is said to be one

- If the fix hides the failure without removing its cause (a guard against the bad value, a retry, a skip), the report
  says "symptom patch", names the cause not removed and says why.
- A test marked skipped or expected to fail is a symptom patch, never a fix.

## Stop after two

- Two failed fixes on one hypothesis stop the work. Report: the reproduction command, each hypothesis with its
  probe and result, what was tried, and what is still unknown.
- Do not try a third variant of the same idea. Name the next hypothesis, or hand back with the evidence collected.

## What no tool checks

Whether the test fails for the real cause rather than for a nearby one: undo the fix and read the failure message
(`harness:review`, a failing gate). Whether the hypothesis list is honest is for the reader of the report.
