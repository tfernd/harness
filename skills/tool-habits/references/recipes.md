# One-call recipes

Each recipe is one tool call that does a whole job and fails loudly. Names and paths are examples; use the project's own.
All pass `zsh -n`. Measured in past sessions: a pipe into `tail` without `pipefail` hid 97 gate failures in 506 calls, a
gate loop that prints `$?` but exits 0 hid 97 more, and 1,239 reads returned over 15,000 characters uncapped.

## Discovery: locate, size, context, cap

One script instead of a run of `ls`, `grep` and `cat`. It prints each match with three lines around it and the file's
length, and stops at a cap while still counting.

```bash
set -o pipefail
python3 - <<'EOF'
import pathlib, re
pat, hits = re.compile(r"def load|TIMEOUT"), 0
for p in sorted(pathlib.Path("src").rglob("*.py")):
    lines = p.read_text(errors="replace").splitlines()
    for i, line in enumerate(lines):
        if pat.search(line) and (hits := hits + 1) <= 40:
            print(f"== {p}:{i + 1} ({len(lines)} lines)", *lines[max(0, i - 3):i + 4], sep="\n")
print(f"{hits} matches, {min(hits, 40)} shown")
EOF
```

## Independent gates or builds: run all, show only failures, exit non-zero

Every gate runs even after one fails; a passing gate prints one line, a failing one its log tail; the last line makes
the call's exit code honest.

```bash
set -o pipefail
mkdir -p /tmp/harness/<project>/gate && rc=0
for g in lint types test build; do
  if make "$g" >"/tmp/harness/<project>/gate/$g.log" 2>&1; then print -r -- "$g ok"
  else rc=1; print -r -- "$g FAILED"; tail -20 "/tmp/harness/<project>/gate/$g.log"; fi
done
(( rc == 0 ))
```

Gates that depend on each other (format, then lint, then test) chain with `&&` instead, as in the tool-habits body.

## A long check: keep the log, print the verdict

A check that prints thousands of lines goes to a file, and a slow one runs with `run_in_background: true` (the call is moved to the background at its timeout, 120 s by default, anyway). Make the folder first, then send this call in the background and end the turn with no further tool call: the exit wakes you. Never pipe it through a word filter: a test named "a failed agent ends failed" matches `fail`, and the summary line falls off the end.

```bash
set -o pipefail
make check >/tmp/harness/<project>/check/check.log 2>&1; rc=$?
echo "exit $rc" >>/tmp/harness/<project>/check/check.log
(( rc == 0 ))
```

When woken, print `tail -n 5` of the log; when it failed, read the file around the first failure with Read and `offset`, not the whole log. A quick check runs in the foreground with `tail -n 5` of the same file.

## A one-line edit: assert before and after

One exact change is the Edit tool. Several changes, or an edit joined to a check, use a script that asserts each target
occurs once, as below. `sed -i` is for files under `/tmp/harness/<project>/`: on a project file the guard lets it run
with a note.

```bash
set -o pipefail
python3 - <<'EOF' &&
from pathlib import Path

path = Path("src/core/shape.ts")
old = "export interface Span {"
text = path.read_text()
assert text.count(old) == 1, old
path.write_text(text.replace(old, "interface Span {"))
EOF
git diff --stat -- src/core/shape.ts &&
make check 2>&1 | tail -20
```

zsh trap: a line that starts with `! grep` after a `&&` on the line before is a parse error. Test a count instead.

## A scoped gate when others edit the tree

Format and lint only the files you changed. Run the type checker on the whole tree, read only the diagnostics in your
files, and count the rest. A failure in another file is another worker's live edit: report it, never fix it.

```bash
set -o pipefail
files=(src/a.py src/b.py)
uvx ruff format "${files[@]}" && uvx ruff check "${files[@]}" &&
uv run pyright 2>&1 | tee /tmp/harness/<project>/types.txt | rg -F -e src/a.py -e src/b.py
rg -c ' error' /tmp/harness/<project>/types.txt
```

## Compare with HEAD

A sub-agent runs no git write: `git stash`, `git worktree` and `git checkout` are refused. To run a check on HEAD's version, export the paths it needs into a fresh folder and run the check there, never in the tree.

Make the folder in one call:

```bash
mktemp -d /tmp/harness/<project>/head.XXXX
```

Then export the paths into the folder it printed, and run the check with that folder as its working directory:

```bash
git archive HEAD src/a.py | tar -x -C <that folder>
```

One file's committed text needs no folder: `git show HEAD:src/a.py` prints it, and `git diff --stat HEAD -- src/a.py` says how far the working copy has moved.

## A throwaway repository for a probe

A rule about commits, staging or history is probed in a repository of its own, never in the project's. Only the main session can make one (`git init` and `git commit` are git writes, refused from a sub-agent), so a brief whose judge needs one names a folder the main session prepared.

The commit rule holds there too: the message has the project's form and comes from a file written in an earlier call. First call, the Write tool: the message file at `/tmp/harness/<project>/probe-message.txt`. Second call:

```bash
mktemp -d /tmp/harness/<project>/repo.XXXX
```

Third call, with the folder it printed written out:

```bash
cd <that folder> && git init -q && print -r -- 'x = 1' > a.py && git add a.py &&
git -c user.name=probe -c user.email=probe@example.com commit -q -F /tmp/harness/<project>/probe-message.txt &&
git log --oneline
```

## Web and APIs: fail on HTTP errors, parse, cap

`curl -f` turns a 4xx or 5xx into a non-zero exit, so an error page never reaches the parser as data.

```bash
set -o pipefail
curl -fsS --max-time 10 -H 'Accept: application/json' "$URL" |
python3 -c 'import json, sys
d = json.load(sys.stdin)
print(type(d).__name__, len(d))
for row in (d if isinstance(d, list) else list(d.items()))[:20]: print(str(row)[:120])' &&
gh api "repos/$REPO/pulls?state=open" --jq '.[] | [.number, .title] | @tsv' | head -30
```

## An ML probe: project root, GPU snapshot, timeout, assert, capped tail

Run the probe through stdin from the project root: Python puts the folder of a script file on `sys.path`, so a probe
saved under `/tmp/harness/<project>/` cannot import the project's packages, while a stdin script imports from the current folder.

```bash
set -o pipefail
cd "$(git rev-parse --show-toplevel)" &&
nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv,noheader &&
timeout 300 uv run python - <<'EOF' 2>&1 | tail -30
import torch
from mypkg.model import build
m = build().to(0).eval()
with torch.no_grad():
    y = m(torch.randn(4, 3, 64, 64, device=0))
assert torch.isfinite(y).all(), "non-finite output"
print("shape", tuple(y.shape))
EOF
```

`.to(0)` puts the model on GPU 0. After an out-of-memory error, change the batch or the size before running again; the same command fails the same way.
