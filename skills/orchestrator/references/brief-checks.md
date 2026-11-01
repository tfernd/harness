# Brief checks

Checks the main session makes before a brief goes out, and when it accepts, in addition to the lists in
`harness:orchestrator` (none repeats them). Each is one line.

## Framing

- Measure first: a method gets its result against a baseline before anything is built.
- The tool's worktree isolation may start from an older commit: make the worktree from the base branch and name its path
  in the brief.

## Briefs

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

## Accepting

- Accepting a new module includes wiring it where the project registers modules.
- An outline pass looks for misplaced names.
- A problem not resolved carries to the next status.
- "Not verified" lists every check that could not run.
