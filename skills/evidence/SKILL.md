---
name: evidence
description: How a fact is settled and an area understood - the evidence ladder, the marks READ, DERIVED, PROBED, the outline-first read and the scout's narrow answer. Load before answering a question of fact, before changing code you have not read in this run, or before launching scouts.
---

# Evidence

A claim counts only with its evidence; climb only as far as the question needs.

## The ladder and the marks

1. **Read** the code and the docs, `path:line` for every claim. Code beats docs; docs beat the plan (report a clash).
2. **Read the installed library's source** for a library claim, never upstream or memory. Name the version.
3. **Probe** only what reading cannot settle: the exact expression, operand order, type and environment of the claim.
   A probe uses the smallest input that shows it and runs nothing exhaustive.

- **READ** `path:line`: seen in the code or a doc, not run. Quote the line's text with it; line numbers go stale.
- **DERIVED**: worked out from read facts; say from which.
- **PROBED** `<command>`, exit `<code>`: run, with the output that shows it.

A claim about how Claude Code or a model behaves names where it was checked: a doc URL or the probe command.

Agreement between agents is not evidence: two agents can read the same wrong line. A bug is a suspect until an input
inside the code's contract shows it. A cause told to the owner is probed first. Test the property you mean, not a proxy
that matches today's inputs.

## Understanding an area before a change

1. **Outline,** one call over the area's files: definitions (`grep -n '^def \|^class \|^function \|^export '`, or the
   language's equivalent) and `wc -l`.
2. **Entry points:** the public functions the change touches, and the dispatch that reaches them.
3. **Callers:** grep each function you change over source, tests and scripts; a new signature changes every caller.
4. **Judges:** the tests that cover the area and the inputs they iterate.
5. **Bodies:** only what the change needs, several ranges per call, independent calls in one message. Read a long file
   in pages of about 500 lines.
6. **The map** in your report: functions you change, callers, judging tests, helpers to reuse.

## Answering as a scout

ONE narrow question, fast, no file written; stop when you can answer. Bash only reads (`cat`, `sed -n`, `grep`, `find`,
`wc`, `git show|log|diff`); name the folders for `find`. Report the answer first, then `path:line` evidence with the
line's text, at most 10 findings each marked sure or unsure, and what you did not check.

## For the orchestrator

- Cut a fan-out along an area, or along a kind of problem across a wider area (redefined helpers, false comments, dead
  code, docs against code). One cell per agent, at most 20 per wave, never over files another agent is editing.
- The brief is short: the question, the files and callers, a ready grep, "report; build and test nothing", a time
  limit. A question about a syntax pattern (every call, every decorator) is a parse of the syntax tree, never a regex.
- After: merge duplicates, check every claim yourself, hand the owner only the checked ones and how many were false.
- How to shape the whole job: `harness:workflows`.
