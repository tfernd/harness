---
name: accept
description: Load to accept a unit, to write its commit proposal, and before the closing status of a big job (Verdict, Done, Needs you, Next, Lessons, Agents): the proposal after each unit, the closing status after a batch. Main session only.
---

# Accept a unit

The main session accepts: it reads and judges, and edits nothing. All wiring and the plan update go to a worker through
a brief.

## 1. Accepting a unit

1. Read the diff of the write set, new files included, and the report's COMPLIANCE and PROBLEMS MET. A change outside
   the write set is sent back, not kept.
2. Future-reader test: would a fresh agent reading this cold find it easier or harder? Names say what a thing is, docs
   are true of the code under them. If harder, the unit goes back to its writer.
3. Gates follow the unit's tier in `harness:workflows`. Small: the project's own checks alone. Medium: the checks and a
   `reviewer` (`harness:review`). Large: the checks, an `auditor` that re-runs the judges (`harness:audit`) and a
   `reviewer`. A finding goes back to the writer with the output. A gate that could not run is accepted only as "not
   run" and listed.
4. Update the plan, through a worker: the unit's row leaves "Next", a decision it settled is recorded, a line it made
   false is deleted in the same proposal.
5. Write the proposal (section 2) before the next unit starts.

## 2. The commit proposal

The owner commits, or the main session when the owner asks. A sub-agent never runs a git command that writes.

- One accepted unit per proposal (it passed section 1); two units are two proposals. Read state with `git status --short -- <paths>`,
  `git diff -- <paths>` and `git log -n 5 --pretty=format:'%s'` for the subject style.
- Layout: `Paths:` (every file of the unit, one per line from the repository root, a removed tracked file marked
  `(removed)`; no folder, glob or `.`), a blank line, `Left out:` if a file is not the unit's, then `Message:`.
- Message: Conventional Commits, `<type>(<scope>): <imperative summary>`. Types `feat`, `fix`, `perf`, `refactor`,
  `test`, `docs`, `chore`. One line, no trailing period, no vague verb (`update`, `change`).
- Body: why first, then what changed by subsystem, then evidence: each gate with its exit code, each measured number
  with its command. A unit that works but is messy says `messy: <what>`. It describes only the listed paths.
- Attribution lines follow the session's instruction; add none that the session did not give.
- A push is a plain push of the working branch, never forced.
- After the commit, `git show --stat HEAD` must list the proposal's paths; a difference goes to the owner.

## 3. The closing status

Due after a turn that ran agents or edited many files, once no background agent is still running (until then the turn is
a progress note). A quick answer does not need it.

Plain words first, then narrow tables, under these exact `##` headings in this order. Required: `## Verdict`,
`## Done`, `## Needs you`, `## Next`, `## Lessons`. The others are left out when empty.

1. `## Verdict`: one or two sentences: done, partly done or blocked, and the one thing that matters most.
2. `## Done`: table Item | Result (done, partly, failed) | Evidence (the proposal file, or the command and exit code).
3. Optional: `## Decisions` (Decision | Reason | Alternative rejected | Taken by), so the owner can overrule one; `## Problems`
   (Problem | Fix | State), where a fix is a rule, hook or gate named by its file, never "be careful".
4. Optional: `## Agents`: one row per agent run, and a one-line model fit (was each model right for its task).

   | Agent (role, model) | Task | Result | Quality 1-5 | What went wrong | Brief fix |
   |---|---|---|---|---|---|

   Quality is the auditor's `Grade: N/5` where there is one, else yours. Show the agent's own Task score beside it when
   they differ by 2 or more.
5. `## Needs you`: actions only the owner can take, each with what happens if they do nothing; "nothing" when empty.
6. Optional: `## Not verified` (what was skipped or only read); `## Numbers` (only those the verdict rests on, a signed percent
   against a named baseline with its command).
7. `## Next`: the one thing to do next, with its cost.
8. `## Lessons`: each lesson and the rule file written this turn. A Lessons section needs a rule-file change made in the
   turn; with none, the body of the `## Lessons` section is the single line `Lessons: none`.

Rules: say what a thing does before its jargon. Report failures and bent rules as plainly as successes. Mark each claim
measured (ran, with the command) or read (seen, not run).
