---
name: release
description: How finished work is prepared for release - commit units, a PR body, CI workflow basics, reading a failed run. Never a force push; the owner decides push and merge. Load when splitting a diff, drafting a PR, writing CI files or reading CI results.
---

# Release

Preparing is a doer's job; applying it (commit, push, merge, tag) is the main session's, on the owner's word. A
sub-agent never runs a git or gh command that writes.

## Commit units

- One unit per commit, each usable alone. Form and the attribution ban: `harness:git-commit`.
- Split the diff by purpose, not by file count: a fix, a refactor and a doc change are three units even in one file set.
- The plan is a list in `__scratch__/`: for each unit the paths and the full message. A file in two units is split
  by hunk, and the plan says which hunks.
- Generated files go in the unit of their source, or in their own unit after it; never alone first.
- Order units so each passes the project's check by itself, where that is cheap to show.

## The pre-push check

Run the project's own check (named in `AGENTS.md`; often a `make check`) once, and quote its exit code. A failure stops
the plan: report it with the cause. Never skip, loosen or replace the check.

## The PR body

```
## What and why
<what changed, in plain words, and why it was needed>

## Checks run
- <command>: exit <code>

## Not proven
- <what was not run or shown, and why>
```

Every claim in it is backed by a command you ran. No AI attribution.

Draft the body in `__scratch__/`, offer it with the push question, and keep it there until the PR merges; then delete it.

## CI basics

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

## Reading a failed run

1. `gh run list --limit 5`, then `gh run view <id>` for the failing job.
2. `gh run view <id> --log-failed | head -n 200` for the lines that say why; the first error line, not the last.
3. Say whether the cause is the change, the workflow or the environment (a runner, a network call, a version), with
   the line that shows it. Reproduce it locally before proposing a fix.

## What the owner decides

- A force push is never part of a plan. If history must change, say so under Open and stop.
- Push, merge, tag and release are the owner's words, relayed by the main session.
- A review of the branch or PR before merge: `harness:review` (the branch and pull request steps).
