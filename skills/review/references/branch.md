# Reviewing a branch or a pull request

The same review as `harness:review`, over a whole branch. One reviewer, at the end, after the product has run.

## Scope

- The base: `BASE=$(git merge-base origin/main HEAD)` (the branch the work targets).
- The size: `git diff --stat BASE...HEAD`; the commits: `git log --oneline BASE..HEAD`.
- A pull request: `gh pr view N` (description, linked issue, state) and `gh pr diff N`.
- The spec or issue the description links is read first; the diff is judged against it, not against the title.

## Run

- Read the head with `git show REF:path` and `git diff BASE...REF`. To run its tests, ask the main session for a
  worktree; a reviewer never creates one.
- Run the project's tests and gates on the head, and note the count of tests that ran.
- CI: `gh pr checks N`. A red check is a finding with its log line; a missing check is noted.

## Read order

1. Tests first: what the change claims to do, and whether each case could fail.
2. Public contracts: changed signatures, flags, file formats, settings keys, messages.
3. The rest of the diff, file by file.

## Checklist

- The behaviour matches the description and the spec or issue; anything extra or missing is a finding.
- Every changed public name has its callers updated (`rg` for the old name over source, tests, docs, scripts).
- New code has a test that could fail (`harness:testing`).
- No secret, and no generated or build file, in the diff.
- Commit messages follow `harness:git-commit`.
- The written standards: the project's `AGENTS.md` and the `code-*` skills for the languages in the diff.

## Findings

Use the finding form and severities of `harness:review`: `path:line` with the line's text, severity A to C, the command
and its output, a one-line fix; A first; unsure items last. Add the pull request number and the head commit the review
read.

## What the reviewer never does

It does not post comments, approve, request changes or merge, on any host. It reports to the main session, which relays
the checked findings to the owner; the owner decides what goes on the pull request.
