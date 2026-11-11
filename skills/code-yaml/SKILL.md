---
name: code-yaml
description: YAML traps and safe pipelines - typed scalars, quoting, indentation, anchors, plus rules for Harness.io pipelines, GitHub Actions and pre-commit configs. Load before writing, moving or reviewing any .yaml or .yml file.
---

# YAML

No comments or docstrings: `harness:code` (a YAML comment is a comment too). CI file basics: the last section.

## Traps

| Trap | Rule |
|---|---|
| YAML 1.1 parsers (PyYAML) read `yes`, `no`, `on`, `off` as booleans (the Norway problem: `NO` for a country code); YAML 1.2 parsers only `true` and `false` | Quote such strings either way: `"no"`, `"on"` |
| `3.10` is the float 3.1; `1.20` is 1.2 | Quote versions: `"3.10"` |
| `0755` is octal, `08` may be a string, `1e3` a float, `~` and `null` are null, `12:30` a sexagesimal number | Quote them when they are strings; write file modes as quoted strings where the tool takes strings |
| Leading zeros (`007`) lose the zeros | Quote the identifier |
| `: ` or ` #` inside a plain scalar ends or splits it; a leading `*`, `&`, `!`, `%`, `@`, `` ` `` starts a tag, anchor or alias | Quote the value (double quotes allow escapes, single quotes do not) |
| Tabs | Spaces only |
| Mixed indent | One width (two spaces) in the whole file; a list under a key is indented the same way throughout |
| Duplicate keys: most parsers keep the last one silently | Never repeat a key in one mapping |
| Anchors and aliases (`&a`, `*a`) work only within one file; GitHub Actions supports anchors since 2025-09-18 but not merge keys (`<<:`) | Use them only where the tool accepts them; otherwise repeat the value or use a template |

Block scalars:

| Form | Newlines | Use |
|---|---|---|
| `\|` | kept | scripts, multi-line text |
| `>` | folded to spaces | long single-line text |
| `\|-` / `>-` | final newline stripped | when the trailing newline matters |
| `\|+` / `>+` | all trailing newlines kept | rare |

Keep a script in a `run:` block short; a long one is a file under `scripts/` (`harness:code-shell`).

## Check

- `yamllint` on every file, with a repo `.yamllint` config.
- The tool's own validator as well: `actionlint` for GitHub Actions, `pre-commit validate-config` for
  `.pre-commit-config.yaml`, the Harness pipeline schema for Harness YAML. yamllint knows syntax, not meaning.

## Harness.io pipelines and templates

- Pipelines and templates are versioned (a template has a `versionLabel`); reference a template by an explicit version,
  never "stable" by accident.
- Runtime inputs are `<+input>.default(x)` or `<+input>.selectOneFrom(a,b)` where the value set is known; `.allowedValues` is deprecated.
- Secrets by reference only: `<+secrets.getValue("id")>`, the secret's identifier, not its display name. Never an inline token, password or key.
- Stages small and single-purpose (build, test, deploy); share steps through step-group or step templates.
- An approval stage or step comes before every production deploy.

## GitHub Actions

- SHA pins, `permissions:` and `concurrency:`: CI file basics, below.
- Never put `${{ }}` of untrusted input (`github.event.*.title`, `body`, branch names, `head_ref`) inside `run:`:
  it is script injection. Pass it through `env:` and use the shell variable.
- `timeout-minutes` on each job.

## .pre-commit-config.yaml

- Every `rev:` is a tag or a SHA, never a branch such as `main`.
- Update on purpose with `pre-commit autoupdate`, and review the diff; no automatic bump without review.
- Hooks must be fast; a slow one runs at `stages: [pre-push]` or in CI.
- Before the commit that adds a hook, run `pre-commit run --all-files` and fix or accept what it reports.

## What no tool checks

Whether a quoted value is needed for the tool that reads it, whether a secret reference points at the right scope, and
whether a pinned SHA belongs to the release you meant.

## CI file basics

- Run the project's own check target (`make check`), so CI and a laptop agree; no second copy of the commands.
- Pin every third-party action to a full commit SHA, with the tag in a trailing comment (`@<sha> # v4.1.0`), which Dependabot and Renovate read.
- Give the workflow the least permission it needs (`permissions:` at the top, read-only by default).
- No secret is printed: no `echo` of one, no `set -x` near one, no secret in an argument that logs.
- A slow job caches what is slow and cancels a superseded run (`concurrency`):

  ```yaml
  permissions:
    contents: read
  concurrency:
    group: ${{ github.workflow }}-${{ github.ref }}
    cancel-in-progress: true
  ```

- `actions/checkout` takes `persist-credentials: false` unless the job pushes; never run untrusted PR code under
  `pull_request_target`.
