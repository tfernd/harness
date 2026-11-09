---
name: accept
description: Load to accept a unit, to write its commit proposal, and before the closing status of a big job (Verdict, Done, Needs you, Next, Lessons, Agents): the proposal after each unit, the closing status after a batch. Main session only.
---

# Accept a unit

The main session accepts: it reads and judges, and makes the wiring, the fixes and the plan update itself.

## 1. Accepting a unit

1. Read the diff of the write set, new files included, and the report's Not proven and Problems. A change outside
   the write set is sent back, not kept.
2. Future-reader test: would a fresh agent reading this cold find it easier or harder? Names say what a thing is, docs
   are true of the code under them. If harder, the unit goes back to its writer.
3. Gates follow the unit's tier in `harness:workflows`. Small: the project's own checks alone. Medium and large: the
   product run, the checks, then one `reviewer` at the end of the round (`harness:review`); an `auditor`
   (`harness:audit`) only when a worker's report is the sole evidence of a claim. The main session reruns each finding's command and drops one whose output does not show it, then applies the rest
   and compares the test count and deleted files with the baseline. A gate that could not run is accepted only as "not
   run" and listed.
4. Update the plan: the unit's row leaves "Next", a decision it settled is recorded, a line it made
   false is deleted in the same proposal.
5. Write the proposal (section 2) before the next unit starts.

## 2. The commit proposal

The owner commits, or the main session when the owner asks (git rules: `harness:git-commit`).

- One accepted unit per proposal (it passed section 1); two units are two proposals. Read state with `git status --short -- <paths>`,
  `git diff -- <paths>` and `git log -n 5 --pretty=format:'%s'` for the subject style.
- Layout: `Paths:` (every file of the unit, one per line from the repository root, a removed tracked file marked
  `(removed)`; no folder, glob or `.`), a blank line, `Left out:` if a file is not the unit's, then `Message:`.
- Message: by `harness:git-commit`. A unit that works but is messy says `messy: <what>` in the body.
- After the commit, `git show --stat HEAD` must list the proposal's paths; a difference goes to the owner.

## 3. The closing status

Due after a turn that ran agents or edited many files, once no background agent is still running. A turn that ends while agents run is a progress note of a few lines with no status headings; a quick answer does not need it either. The Stop hook asks for the status when it is due, so never write it ahead of that.

Plain words first, then narrow tables, under these exact `##` headings in this order. Required: `## Verdict`,
`## Done`, `## Needs you`, `## Next`, `## Lessons`. The others are left out when empty.

1. `## Verdict`: one or two sentences: done, partly done or blocked, and the one thing that matters most.
2. `## Done`: table Item | Result (done, partly, failed) | Evidence (the proposal file, or the command and exit code).
   It lists every ask the owner made since the last status, each marked done or not with its evidence, so the owner need not ask
   "anything missing?"; the same list serves a checkpoint.
3. Optional: `## Decisions` (Decision | Reason | Alternative rejected | Taken by), so the owner can overrule one; `## Problems`
   (Problem | Fix | State), where a fix is a rule, hook or gate named by its file, never "be careful".
4. `## Agents`, required when the turn ran agents: one row per agent, its Task cell starting with the description it was
   given, and what happened to its problems (fixed in FILE, filed, rejected: why, or none); then a one-line model fit (was
   each model right for its task). The Stop hook only notes a section that misses an agent; it does not hold the turn.

   | Agent (role, model) | Task | Result | Quality 1-5 | What went wrong | Brief fix |
   |---|---|---|---|---|---|

   Quality is the auditor's `Grade: N/5` where there is one, else yours. Say when the agent's Verdict disagrees with it.
5. `## Needs you`: actions only the owner can take, each with what happens if they do nothing; "nothing" when empty.
6. Optional: `## Not verified` (what was skipped or only read); `## Numbers` (only those the verdict rests on, a signed percent
   against a named baseline with its command).
7. `## Next`: the one thing to do next, with its cost.
8. `## Lessons`: each lesson and the rule file written this turn. A Lessons section should show a rule-file change made in the
   turn; with none, the body of the `## Lessons` section is the single line `Lessons: none`. The Stop hook only notes a
   Lessons section that lacks a change; it does not hold the turn.

Rules: say what a thing does before its jargon. Report failures and bent rules as plainly as successes. Mark each claim
measured (ran, with the command) or read (seen, not run).
