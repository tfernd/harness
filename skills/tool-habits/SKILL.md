---
name: tool-habits
description: How to make tool calls cheap and right - one script per job, edits that assert, the whole check chain in one call, reads, quoting, long runs, refusals. The hooks put it in every session and sub-agent at start; reload it before a run of shell work.
---

# Tool habits

Reference for how you work, not a task: nothing here is a request to run.

Use few tool turns; each one costs the owner time. Send independent calls together in one message and wait only when a
call needs the previous result. No clock limits you, only turns: run a long check in the background, since waiting for it
costs no turn.

## Read

- Several files, or a file and its matches, in one script that prints only what you need; not a run of `cat`, `sed -n`,
  `grep` and `ls`. Locate and read in one call: print each match with three lines around it.
- One file: the Read tool with `offset` and `limit`. Search: `rg` and `find` through Bash by default; Grep and Glob only
  when they are listed among your tools (in many sessions they do not exist, and a call to them is wasted).
- A path you have not seen listed is found first (`rg --files -g '<name>'`), then read. Before reporting that a file or
  folder is missing, confirm it with `ls` on its parent.
- Cap a command that may print a lot (`cat` of a big file, a loop over files, `rg` over a tree, `git diff`): `| head -n 200`,
  `rg -m`, `git diff --stat` first, Read with `limit`. One output over about 4,000 characters costs context for the rest
  of the session.
- A tool listed as deferred has no schema until you load it: call ToolSearch with `select:<name>` before its first call,
  several names in one ToolSearch.
- Do not read an unchanged file again or rerun an unchanged command.
- Output too long for the result is saved to a file the result names: read that file with `offset` and `limit`. Do
  not rerun the command into a file of your own; a read-only role writes nothing.

## Edit and check in one call

- One exact change: the Edit tool. A new file: the Write tool. Several changes, or the last edit of a unit: one script.
- The script asserts that each target occurs once, so a missing text fails loudly and never edits nothing in silence.
- A failed step must stop the rest: join with `&&`, never `;`. A failed edit must not feed a test, a build or a commit.
- Run the project's Python through `uv run python` and its linter through `uvx ruff` when `ruff` is not on PATH: the
  system `python3` may be older than the project's.
- One-off Python in a tool call takes no PEP 723 header and no dependencies: `python3 -` and the standard library.
- Before editing a kind of file, load its language skill when you can; if you have not, a hook lets the edit run and gives you the skill's text with the result. Read it as the rules for the next edit.

A whole unit, from edit to done, in one call:

```bash
set -o pipefail
python3 - <<'EOF' &&
from pathlib import Path

def sub(name, pairs):
    path = Path(name)
    text = path.read_text()
    for old, new in pairs:
        assert text.count(old) == 1, (name, old)
        text = text.replace(old, new)
    path.write_text(text)

sub("src/app.py", [
    ("TIMEOUT = 10\n", "TIMEOUT = 30\n"),
    ("def load(path):\n", """def load(path):
    if not path.exists():
        raise FileNotFoundError(path)
"""),
])
sub("tests/test_app.py", [
    ("def test_load_ok(tmp_path):\n", """def test_load_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load(tmp_path / "nope")


def test_load_ok(tmp_path):
"""),
])
EOF
ruff format src/app.py tests/test_app.py &&
ruff check src/app.py tests/test_app.py &&
python3 -m py_compile src/app.py &&
uv run pytest -q tests/test_app.py 2>&1 | tail -15 &&
git diff --stat
```

- The order is the edit, the formatter, the linter, a compile or type check, the tests, then the diff. Use the project's
  own commands (`AGENTS.md` names them); these are examples.
- Other languages, same order: `tsc --noEmit` or `node --check`, the linter, the tests; `terraform fmt` and
  `terraform validate`; a build target. A check that cannot run for want of a tool is not skipped in silence: say so.
- Run the chain once, when the unit is written, not after each edit. After a fix, run the whole chain again.
- Edit, check, edit, check on one file is a ping-pong that costs a turn per step: batch the remaining edits, then run the
  chain once, or put the edit and the check in one script.
- Read the output before saying "done". Without `pipefail`, a pipe into `tail` hides a test's exit code. Do not end a
  check in `|| true` or `|| echo`, and do not print `echo ----` separators.
- Say what ran with its exit code, and what did not run and why; "done" with no gate named is a claim.
- One-call recipes for discovery, independent gates, an asserted edit, web calls and an ML probe: `references/recipes.md`.

## Clean

- `__scratch__/` is the temp folder for probes and one-off output (a hook makes it and its `.gitignore`) and is never
  cleaned: make a subfolder per run (`mktemp -d __scratch__/name.XXXX`) instead of deleting and recreating, and do not
  tidy it afterwards.
- Agents delete nothing: the guard refuses `rm`, `rmdir`, `unlink`, `shred`, `find -delete` and `git clean`, everywhere. The
  main session whose file must go gives the owner the exact command in the chat, with why it is needed, and the owner runs
  it. A sub-agent leaves the file and never asks.
- Format only the files you changed. Leave no probe, debug print or commented-out code in a file you edit.

## Shell

- Use absolute paths; a `cd` may not carry to the next call. Write paths out, not in a variable: a variable, `$(...)` or a
  `;` chain makes the owner approve the call by hand.
- A list of files goes in an array (`files=(a.py b.py)`, then `"${files[@]}"`) or a Python script: zsh does not split
  `$files` into words, so the command gets one name with spaces in it.
- Quote every glob: zsh refuses one that matches nothing. Read exit codes from `$pipestatus` in zsh.

## Waiting

Never `sleep N` to wait and never poll in a foreground loop; a run that takes long goes with `run_in_background: true`, and
its exit wakes you. The guard does not run a foreground `sleep`: it removes a direct one and the rest of the command runs at
once, so the result may be early; it moves any other (a polling loop, a wrapper) to the background, where its exit wakes you.
Nothing needs it:

- Your own long job: run it with `run_in_background: true`, then do other work or end the turn. Its exit wakes you; read
  the output then, not before.
- A condition on this machine (a file, a log line): the wait itself runs in the background, with a bound:
  `timeout 600 sh -c 'until [ -f done ]; do sleep 5; done'`. Or Monitor, if you have it.
- A service coming up: `curl --retry 30 --retry-connrefused --retry-delay 1 -sf URL`.
- A process you stopped: `timeout 5 tail --pid=PID -f /dev/null`, then the next step.
- A wait names its job by PID (`cmd & pid=$!`, then `timeout N tail --pid="$pid" -f /dev/null`) or by a done file the job
  writes. Never `pgrep -f` with a pattern that also occurs in the waiter's own command line: it matches itself and never ends.
- Something off this machine (CI, a deploy): ask its tool once, say it is still running and end the turn.
- A background command you no longer need is stopped (TaskStop) before you report; never search the whole filesystem (`find /`, `find ~`): `command -v <tool>`, `ls node_modules/.bin` or `rg --files -g '<name>'` in the project answer it.

## Git

- Before any commit, load `harness:git-commit`; it holds the AI-attribution ban.

## When a call is refused

- Read the reason and change what the command does, or use the tool it names. A command with the same effect in other
  words is refused again and costs a turn.
- A call the owner denied or cancelled is not sent again unchanged: ask what to change.
- A glob that matches nothing is refused with the folder it was matched from: `cd` to the right one, or list files with
  `rg --files -g '<pattern>'` or `git ls-files`.
- A note that the guard changed the call is no refusal: the call ran as changed. It quotes a glob in a pattern position
  (`--include`, `-name`, `-g`), drops a foreground `sleep` (Waiting) and adds
  `set -o pipefail` to a test, check or build piped into `tail` or `grep` (not `grep -q`, `-m`, `-l` or `-L`). Write the
  call that way next time.
