---
name: code-shell
description: Shell script rules for bash - when shell fits, strict mode, quoting, arrays, bash against zsh differences, no parsing ls, mktemp and trap, shellcheck and shfmt. Load before writing, moving or reviewing any .sh file or a script of more than a few lines.
---

# Shell

Comments: `harness:comments`. One-off commands in a tool call: `harness:tool-habits`.

## When shell fits

- Shell fits for gluing programs: run a command, pipe, test an exit code, set an environment, move files.
- Move to a script in another language when the script needs any of: arrays of records or maps, JSON or other
  structured data, arithmetic beyond integers, more than about 100 lines, a branch you cannot read in one screen, or
  tests of its own logic.
- A script in the repo that others run has a `#!/usr/bin/env bash` first line, the executable bit, and a header
  comment of 1 to 3 lines saying its job and its usage.

## Strict mode

- A saved script starts with `set -euo pipefail` after the shebang. `-e` stops on a failed command, `-u` on an unset
  variable, `pipefail` on a failure inside a pipe.
- `set -e` does not fire inside an `if` condition, on the left of `&&` or `||`, or in a function called from one. Test
  `$?` or use `|| exit` where a failure must stop the script.
- An expected failure is written out: `grep -q x file || true`, or `if ! cmd; then ...; fi`. Never a blanket
  `set +e`.
- Under `pipefail`, `cmd | grep -q x` and `cmd | head -n 1` can fail with SIGPIPE (141); capture first
  (`out="$(cmd)"; grep -q x <<<"$out"`).
- `cd` can fail: `cd "$dir" || exit 1`. A script that must run from anywhere resolves its own folder once:
  `here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"`.

## Quoting and lists

- Quote every expansion: `"$var"`, `"$(cmd)"`, `"${arr[@]}"`; pass arguments on with `"$@"`, never `$*`. Use `[[ ]]`,
  not `[ ]`, and `$(...)`, not backticks.
- A list of files is an array, not a string: `files=(./*.txt)`, then `"${files[@]}"`. Check an empty glob with
  `shopt -s nullglob`, or test the array length.
- Start a path from `./` or use `--` before it when it comes from outside: a name that begins with `-` is read as an
  option.
- Read lines with `while IFS= read -r line; do ...; done < file`. For names that may hold spaces or newlines, use
  `find ... -print0` with `read -r -d ''` or `xargs -0`.

## No parsing ls

- `ls` output is for people. Use a glob, `find`, or `stat` for a field. `for f in $(ls)` splits on spaces and breaks
  on every odd name.

## Bash against zsh

An interactive shell may be zsh while the script runs under bash, so a line that works at the prompt can fail in the
script, and the other way round. Check the shebang before trusting a line.

| Matter | bash | zsh |
|---|---|---|
| Unquoted `$var` | splits on whitespace, then globs | no splitting, no glob (unless `setopt SH_WORD_SPLIT`) |
| Glob with no match | passes the pattern as text | stops with "no matches found" |
| Exit codes of a pipe | `${PIPESTATUS[@]}` | `$pipestatus` (lowercase) |
| Array index | starts at 0 | starts at 1 |
| `read -p "text"` | prompt | `-p` reads from a coprocess; use `read "?text"` |

- Write for bash in a saved script and do not rely on a zsh behaviour. In a tool call under zsh, quote every glob and
  read `$pipestatus`.

## Temporary files and cleanup

- Make a temporary file or folder with `mktemp` / `mktemp -d`, never with a fixed name or `$$`. A project's scratch
  folder, when it names one, is the place for throwaway files, so pass `--tmpdir` or a template inside it.
- Register cleanup first: `tmp="$(mktemp -d)"; trap 'rm -rf -- "$tmp"' EXIT`. `EXIT` fires on a normal end, on `exit`
  and on an error under `-e`.
- Do not delete in a script a path built from a variable that may be empty; `"${tmp:?}"` makes an empty value stop the
  script.

## Gates

- `shellcheck <file>` exits 0 with no finding, and `shfmt -d <file>` prints no diff (its flags, such as `-i 2`, are
  the project's). Run both on each changed script; `bash -n <file>` checks syntax only.
- A missing `shellcheck` or `shfmt` is reported as Not proven with the command that was tried, never as a pass.

Independent gates that must all run, each failure shown and the call still failing: the gate recipe of
`harness:tool-habits`.

## What no tool checks

Whether the job should be a script in another language, whether a variable is quoted where shellcheck cannot see it
(inside `eval` or `ssh` strings), and whether the cleanup covers every path out of the script.
