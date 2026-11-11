# Brief checks

The lists the main session uses before a brief goes out, and when it accepts. Each is one line.

## Lines the brief must hold

- A judge that may already fail says so. The agent runs it once first and reports a failure it did not cause as a
  problem with cause `other agent`.
- A brief that asks for a new judge names the deliberate bug that must fail it, read off the code (`harness:testing`).
- A brief that changes a public signature lists every caller, found by `rg`.
- The `Write set:` line holds only paths and globs (prose goes after a `;` or `:`), every file the job writes, tests and docs included: a hook refuses a sub-agent's Edit, Write or Bash write outside it, and the agent can only report the need.
- A brief says what the agent cannot do (permissions, read-only, no network), so it reports `blocked` with the reason
  instead of going quiet.
- A size limit states what it counts (file or report, frontmatter, fenced blocks) and which moves can reach it.

## Checklist before it goes out (the sender's, not text of the brief)

- Every fact comes from a file read or a report, never memory. A name, count or path is checked by `rg`; a line is given
  as its text; a number carries its command.
- Every "or" in the job is decided or asked of the owner; every command the job names exists and was run, or the brief
  says "measure only"; a limit is derived from its source, not typed again; a helper the job asks for is not already
  there (`rg` for one that does the same).
- Re-read the whole brief: no sentence contradicts another.
- The checks below add to this list.

## Also check

### Framing

- Measure first: a method gets its result against a baseline before anything is built.

### Briefs

- A write set naming a scratch subfolder: create it before the agent starts, since a shell `cd` into a missing folder trips the guard.
- A brief that runs a substring filter (`run_cases.py --only`) names the exact texts and how many items they match: a
  common word matches every hook and turns a narrow run into the full suite.
- A judge that runs tests also checks how many ran: a zero-test run exits 0 and passes for the wrong reason.
- A brief fits its turn budget: more steps than the budget can hold ends as a partial result, so split it before sending.
- An audit brief carries the author's report, so the grade can be compared with its Verdict.
- In a shared tree, a repo-wide judge fails on other agents' live files: scope it to the write set (`git diff --stat -- <files>`).
- The output file of a job is untracked, and no cache key hides the thing being varied.
- No text outside the write set names a helper the job removes.
- A brief that tightens a gate rule lists the files the rule newly flags; "green now" is checked just before the brief
  goes out.
- A brief that moves a path lists every grep hit, hidden folders included.
- A scripted move builds the new files in memory, writes them, and only then runs `git mv`.
- Two workers edit a shared file only with small anchored edits, each re-read right before it; the brief names the owner
  of a shared comment.
- A refactor brief says `Runs: none` and names a static check or a grep as its judge.
- A helper two trees will share goes in the write set.
- A brief that adds code states the file's line count against the limit.
- A counting judge ("one X per Y") says what it counts and whether rows with no backing file count.
- A brief that asks for one function or signature lists every new helper it allows.
- A visual or design-fix judge names how to set the theme it checks and carries the plan's numbered items to mark.
- A visual fix brief says what to do with a layout fault outside its items (an overflow, a cut-off popover): fix it or
  list it under Open.
- A page brief says whether the page must work opened from `file://`; a module script does not run there.
- A brief that asks for a browser render names the command that drives one here (`uv run --with playwright` and the
  system Chrome), and says that embedded text may hold the page template's own markers (`{{`).
- A page brief that adds a colour state asks for its contrast in both themes and on hover before the first full check,
  and says the full check runs once, last, and is never stopped to hand off sooner.
- A mock brief at a fixed width or column count gives the width budget (characters per line, px per group) and asks each
  text end to be checked against its neighbour's edge before the first render, so the first render fits.
- A mock brief says which controls are drawn shapes and which are real buttons, and whether a trace shows its states.
- A new name for a public repo (a folder, a plugin, a key) is run through `tests/check_leaks.py` before the brief goes
  out: a private word in it fails every file the agent writes.
- A layout judge is checked against the reference screenshot before the brief goes out: it must not assert a row or
  edge the reference does not have.

### Accepting

- Accepting a new module includes wiring it where the project registers modules.
- An outline pass looks for misplaced names.
- A problem not resolved carries to the next status.
- "Not proven" lists every check that could not run.
