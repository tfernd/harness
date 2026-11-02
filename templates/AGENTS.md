# AGENTS.md
How every agent works here. What we build and what is open is in <plan file>. The main session loads
`harness:orchestrator` first. No dates and no history here: a fact that changes is edited in place.

## 1. The goal
<One or two sentences: what this project builds and the unit its results are measured in.>

## 2. The repository
- Layout: <folder: what lives there>.
- Off limits (read only if asked, never edited or imported): <paths, or "none">.

## 3. Writing code
- Before touching a file, load the skill its rule names (`.claude/rules/`).
- Checks, cited by name: the check gate `<command>` (run once; a third failing run stops you); the full gate
  `<command>`.
- A failure in a file outside your write set is another agent's unfinished work: report it, never fix it.
- Budget every run: smallest case first; a run over 2 minutes writes one row per case as it finishes; a killed call is
  split, never retried unchanged.

## 4. Tests: the judges
Judges and the control rule: `harness:testing`. A new judge is shown to fail once under a deliberate bug.

## 5. Commands, files, git
- Never resolve, install or remove packages unless the owner says so.
- Quote every glob. No command over 3 minutes, none that sleeps or polls.
- You change only your write set; anything else goes under OUTSIDE in your report. Throwaway work goes in
  `<scratch folder>/TOPIC/`, never `/tmp`. Never `rm`; a tracked file goes with `git rm -q`.
- The owner commits, or the main session when asked. A sub-agent never runs a git command that writes.

## 6. The report
Every sub-agent ends with the `harness:report` report, claims marked READ, DERIVED or PROBED (`harness:evidence`).

## 7. Traps
- A line number in a brief goes stale while others edit: find it by its text.
- An exit code after a pipe is the last command's: read `${PIPESTATUS[@]}` (bash) or `$pipestatus` (zsh).

## 8. Working efficiently
- Tool turns: the harness states the rule to every session and sub-agent at its start.
- Test once per unit, when it is done, not after each edit. When moving or migrating files, change first and test at the
  end. Run the smallest check that can fail, never the whole suite twice, and never a check to confirm what a tool
  already confirmed (a write that succeeded, a file just read).
- A check that takes over a minute runs once, in the background. A slow machine is a cost to the owner too.
