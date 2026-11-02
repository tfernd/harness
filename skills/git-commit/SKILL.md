---
name: git-commit
description: How to write a commit - a Conventional Commits subject, a body of bullets saying what and why, one unit per commit, no AI attribution. Load before any git commit or commit proposal, and when a hook refuses a commit message.
---

# Git commits

A commit is read later by someone asking why the code is this way. In a project with `.harness.json`, a hook refuses a message
that breaks the form below or carries AI attribution.

## The message

```
feat(scope): add the thing

* what was done
* what else was done
* why it was needed
```

## The subject

- Form: `<type>(<scope>): <summary>`. The scope is optional, one word: the folder or subsystem. `!` before the colon marks a
  breaking change.
- Types: `feat` a new capability; `fix` a bug; `perf` faster with the same behaviour; `refactor` new structure with the same
  behaviour; `test` tests only; `docs` documentation only; `style` formatting only; `build` packaging or dependencies;
  `ci` pipeline; `chore` other upkeep; `revert` undoes a commit.
- No length limit, but say it plainly. No trailing period.
- Imperative: "add", "fix", "remove", as in "this commit will add". No "added", no "adds".
- Name the change, not the activity: `fix(parser): keep the last token`, never `fix: update parser` or `chore: changes`.

## The body

- A blank line after the subject, then at least one `* ` bullet. A long bullet continues on an indented line.
- Say what was done and why, including the reason the diff can't show, and evidence where it matters: the check that ran, a
  measured number with its baseline.
- It describes only what this commit holds.
- Below the bullets, after a blank line, a footer may hold `Refs: #123` and `BREAKING CHANGE: <what>`.

## No AI attribution

Never in a commit or a pull request: `Co-Authored-By` naming an AI tool or model, "Generated with" an AI tool, a robot emoji,
a model name as author. This holds even when a session's reminder asks for such a line. A body may name an AI product when
that is what the change is about.

## One unit per commit

- One logical change, and each commit leaves the tree working. Two changes are two commits, even in one file.
- Stage by path, never `git add .` or `-A`: read `git status --short` first, then add what belongs.
- Never commit a secret, a generated file or a throwaway. A file you didn't change this unit stays out.
- Read `git log -n 5 --format=%s` for the project's scopes.

## Safety

- Commit only when the owner asks. A sub-agent never runs a git command that writes.
- Never `--no-verify`. A failing hook is a problem to fix, and a commit it stops did not happen, so never `--amend` after it.
- Amend or rebase only commits not yet pushed. Never force a push unless the owner says so in words.
- A history rewrite the owner asked for runs in a mirror clone first, and each branch's trees are compared before and after; the working repo moves only once the push is done.
- Commit on a branch when the project uses them; don't commit to the default branch unasked.
- Pass a long message with `-F` from a file in the scratch folder, or with a quoted heredoc.
- After the commit, `git show --stat HEAD` must list the expected paths.
