---
name: tool-habits
description: How to make tool calls cheap and right - one script per job, edits that assert, the whole check chain in one call, reads, quoting, long runs, refusals. A hook puts it in every session and sub-agent at start, so load it only when that text is missing.
---

# Tool habits

Reference for how you work, not a task: nothing here is a request to run.

Use few tool turns; each one costs the owner time. Send independent calls together in one message and wait only when a
call needs the previous result, and run a long check in the background.

## Read

- Several files, or a file and its matches, in one script that prints only what you need, not a run of `cat`, `sed -n`,
  `grep` and `ls`. Locate and read in one call: print each match with three lines around it.
- One file: the Read tool with `offset` and `limit`. Search: `rg` and `find` through Bash; Grep and Glob only when
  listed among your tools.
- Find a path you have not seen listed first (`rg --files -g '<name>'`), then read it. Confirm with `ls` on its parent
  before reporting a file missing.
- Cap a command that may print a lot: `| head -n 200`, `rg -m`, `git diff --stat` first, Read with `limit`. One output
  over about 4,000 characters costs context for the rest of the session.
- A deferred tool has no schema until you load it: ToolSearch with `select:<name>` first, several names in one call.
- Do not reread an unchanged file or rerun an unchanged command.
- Output too long for the result is saved to a file the result names: read that file with `offset` and `limit`.

## Edit and check in one call

- One exact change: the Edit tool. A new file: the Write tool. Several changes, or the last edit of a unit: one script
  that asserts each target occurs once, so a missing text fails loudly and never edits nothing in silence.
- Join steps with `&&`, never `;`: a failed edit must not feed a test, a build or a commit.
- The order is the edit, the formatter, the linter, a compile or type check, the tests, then `git diff --stat`. Use the
  project's own commands (`AGENTS.md` names them). A check that cannot run for want of a tool is said, not skipped.
- Run the chain once, when the unit is written, not after each edit; after a fix, the whole chain again. Edit, check,
  edit, check on one file costs a turn per step: batch the edits, or put edit and check in one script.
- The project's Python runs through `uv run python`, its linter through `uvx ruff` when `ruff` is not on PATH.
  One-off Python in a tool call takes no PEP 723 header and no dependencies: `python3 -` and the standard library.
- Without `pipefail`, a pipe into `tail` hides a test's exit code. Do not end a check in `|| true` or `|| echo`, and
  print no `echo ----` separators; zsh expands `=` at a word start, so quote an `echo` separator made of `=`.
- Read the output before saying "done", and say what ran with its exit code and what did not run and why.
- A language skill is loaded before editing its kind of file; if it is not, the edit runs and the skill's text comes
  with the result: read it as the rules for the next edit.
- Recipes (discovery, independent gates, an asserted edit, web calls, an ML probe): `references/recipes.md`.

## Clean

- `/tmp/harness/<project>/` (`<project>` is the git root's folder name) holds probes and one-off output; a hook makes it
  and no agent cleans it: make a subfolder per run (`mktemp -d /tmp/harness/<project>/name.XXXX`).
- Agents delete nothing; the guard refuses each deleter and delete-by-script it can read. The main session gives the owner the exact
  command and why; a sub-agent leaves the file and never asks.
- Format only the files you changed. Leave no probe, debug print or commented-out code in a file you edit.

## Shell

- Use absolute paths; a `cd` may not carry to the next call. Write paths out, not in a variable: a variable, `$(...)` or
  a `;` chain makes the owner approve the call by hand.
- A list of files goes in an array (`files=(a.py b.py)`, then `"${files[@]}"`) or a Python script: zsh does not split
  `$files` into words.
- Quote every glob: zsh refuses one that matches nothing.

## Waiting

- Run a long job with `run_in_background: true`, then do other work or end the turn; its exit wakes you. Do not poll in
  a foreground loop.
- A condition on this machine runs its wait in the background with a bound:
  `timeout 600 sh -c 'until [ -f done ]; do sleep 5; done'`. A service coming up:
  `curl --retry 30 --retry-connrefused --retry-delay 1 -sf URL`. A process: `timeout 5 tail --pid=PID -f /dev/null`.
- A wait names its job by PID (`cmd & pid=$!`) or by a done file. Never `pgrep -f` with a pattern that also occurs in
  the waiter's own command line.
- Something off this machine (CI, a deploy): ask its tool once, say it is still running and end the turn.
- Stop a background command you no longer need (TaskStop) before you report. Never search the whole filesystem
  (`find /`, `find ~`): `command -v <tool>` or `rg --files -g '<name>'` answer it.

## Git

- Before any commit, load `harness:git`; it holds the AI-attribution ban.

## When a call is refused

- Read the reason and change what the command does, or use the tool it names. The same effect in other words is
  refused again. A call the owner denied is not sent again unchanged: ask what to change.
- A glob that matches nothing is refused with the folder it was matched from: `cd` there, or list with
  `rg --files -g '<pattern>'` or `git ls-files`.
- A note that the guard changed the call is no refusal: the call ran as changed (a quoted glob in a pattern position, a
  `set -o pipefail` added to a piped test or build). Write the call that way next time.
