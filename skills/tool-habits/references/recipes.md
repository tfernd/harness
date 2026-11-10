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
mkdir -p __scratch__/gate && rc=0
for g in lint types test build; do
  if make "$g" >"__scratch__/gate/$g.log" 2>&1; then print -r -- "$g ok"
  else rc=1; print -r -- "$g FAILED"; tail -20 "__scratch__/gate/$g.log"; fi
done
(( rc == 0 ))
```

Gates that depend on each other (format, then lint, then test) chain with `&&` instead, as in the tool-habits body.

## A one-line edit: assert before and after

One exact change is the Edit tool. Several changes, or an edit joined to a check, use the Python edit form of the body
(`sub(...)` asserts each target occurs once). `sed -i` is for files under `__scratch__/` only: the guard refuses it
elsewhere.

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
saved under `__scratch__/` cannot import the project's packages, while a stdin script imports from the current folder.

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
