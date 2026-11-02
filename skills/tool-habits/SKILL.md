---
name: tool-habits
description: How to make tool calls cheap and right - one script per job, edits that assert, the whole check chain in one call, reads, quoting, long runs, refusals. The hooks put it in every session and sub-agent at start; reload it before a run of shell work.
---

# Tool habits

Use few tool turns; each one costs the owner time. Send independent calls together in one message and wait only when a
call needs the previous result. No clock limits you, only turns: run a long check in the background, since waiting for it
costs no turn.

## Read

- Several files, or a file and its matches, in one script that prints only what you need; not a run of `cat`, `sed -n`,
  `grep` and `ls`. Locate and read in one call: print each match with three lines around it.
- One file: the Read tool with `offset` and `limit`. Search: Grep and Glob. Without them, `rg` and `find` through Bash.
- Do not read an unchanged file again or rerun an unchanged command.

## Edit and check in one call

- One exact change: the Edit tool. A new file: the Write tool. Several changes, or the last edit of a unit: one script.
- The script asserts that each target occurs once, so a missing text fails loudly and never edits nothing in silence.
- A failed step must stop the rest: join with `&&`, never `;`. A failed edit must not feed a test, a build or a commit.
- One-off Python in a tool call takes no PEP 723 header and no dependencies: `python3 -` and the standard library.
- Before editing a kind of file, load its language skill. A hook only sees the Edit and Write tools, so a script is on you.

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
    ("# end of cases\n", """def test_load_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load(tmp_path / "nope")

# end of cases
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
- Read the output before saying "done". Without `pipefail`, a pipe into `tail` hides a test's exit code. Do not end a
  check in `|| true` or `|| echo`, and do not print `echo ----` separators.
- Say what ran with its exit code, and what did not run and why. "Done" with no gate named is a claim, not a result.

## Clean

- Keep probes and one-off output in the project's scratch folder when it names one. Delete nothing yourself: the guard
  refuses a delete, so leave those files for the owner.
- Format only the files you changed. Leave no probe, debug print or commented-out code in a file you edit.

## Shell

- Use absolute paths; a `cd` may not carry to the next call.
- Quote every glob: zsh refuses one that matches nothing. Read exit codes from `$pipestatus` in zsh.
- A long run goes in the background. Never poll with `sleep` in a loop.

## When a call is refused

- Read the reason and change what the command does, or use the tool it names. A command with the same effect in other
  words is refused again and costs a turn.
