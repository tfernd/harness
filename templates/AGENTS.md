# AGENTS.md
How every agent works here. What we build and what is open is in <plan file>. The main session loads
`harness:orchestrator` first. No dates and no history here: a fact that changes is edited in place.

## 1. The goal
<One or two sentences: what this project builds and the unit its results are measured in.>

## 2. The repository
- Layout: <folder: what lives there>.
- Off limits (read only if asked, never edited or imported): <paths, or "none">.

## 3. Writing code
- Before touching a file, load the skill the `skill_gate` setting names for it; a hook checks edits, shell writes and commits.
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
  `__scratch__/TOPIC/`, never `/tmp`. `__scratch__/` is never cleaned: a fresh run takes a new folder name. Agents delete nothing (the guard refuses `rm`, `rmdir`, `unlink`, `shred`, `find -delete` and `git clean`): if a file must go, the main session gives the owner the command in the chat, with why, and the owner runs it; a sub-agent leaves it. A tracked file goes with `git rm -q`.
- The main session commits and pushes when the owner asks. A sub-agent never runs a git or gh command that writes.

## 6. The report
Every sub-agent ends with the `harness:report` report, claims marked READ, DERIVED or PROBED (`harness:evidence`).

## 7. Traps
- A line number in a brief goes stale while others edit: find it by its text.
- An exit code after a pipe is the last command's: read `${PIPESTATUS[@]}` (bash) or `$pipestatus` (zsh).

## 8. Rule enforcers
Every rule above has an enforcer; a rule with none is the first to be broken again.

| Rule | Enforced by (hook, test, lint, review, none) |
|---|---|
| <rule> | <enforcer> |

## 9. Review rules
<!-- Optional; the reviewer reads it first (`harness:review`). Delete the comment markers to use it.
- Severity A here: <what counts>.
- At most <5> C findings.
- Skip: <paths and classes CI already enforces>.
- Always check: <items>.
- Accepted issues, security included: <known issues the review does not report>.
-->

## 10. Working efficiently
Tool turns, reads, edits and checks: `harness:tool-habits`, which every session and sub-agent starts with.
