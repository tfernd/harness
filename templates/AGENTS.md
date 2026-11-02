# AGENTS.md
How every agent works here. What we build and what is open is in <plan file>. The main session loads
`harness:orchestrator` first. No dates and no history here: a fact that changes is edited in place.

## 1. The goal
<One or two sentences: what this project builds and the unit its results are measured in.>

## 2. The repository
- Layout: <folder: what lives there>.
- Off limits (read only if asked, never edited or imported): <paths, or "none">.

## 3. Writing code
- Before touching a file, load the skill `skill_gate` in `.harness.json` names for it; a hook checks edits, shell writes and commits.
- Run the project's lint, format and type checks before the report; their exit codes go in it.
- Checks, cited by name: the check gate `<command>` (run once; a third failing run stops you); the full gate
  `<command>`.
- A bug fix starts with a test that fails for the reported cause (`harness:workflows`).
- A failure in a file outside your write set is another agent's unfinished work: report it, never fix it.
- Budget every run: smallest case first; a long run writes one row per case as it finishes; a killed call is
  split, never retried unchanged.

## 4. Tests: the judges
Judges and the control rule: `harness:testing`. A new judge is shown to fail once under a deliberate bug.

## 5. Commands, files, git
- Never resolve, install or remove packages unless the owner says so.
- You change only your write set; anything else goes under Open in your report. Throwaway work goes in
  `<scratch folder>/TOPIC/`, never `/tmp`. `rm` works only inside the scratch folder; a tracked file goes with `git rm -q`.
- The owner commits, or the main session when asked. A sub-agent never runs a git command that writes.

## 6. The report
Every sub-agent ends with the `harness:report` report, claims marked READ, DERIVED or PROBED (`harness:evidence`).

## 7. Traps
- A line number in a brief goes stale while others edit: find it by its text.
- An exit code after a pipe is the last command's: read `${PIPESTATUS[@]}` (bash) or `$pipestatus` (zsh).

## 8. Working efficiently
Tool turns, reads, edits and checks: `harness:tool-habits`, which every session and sub-agent starts with.
