---
name: comments
description: Code carries no comments, docstrings or doc comments, in any language. Load before writing, moving or reviewing code in any language, and when a comment or docstring is tempted or found.
---

# No comments, no docstrings

Language rules: `harness:code-python`, `harness:code-js`, `harness:code-html-css`, `harness:code-terraform`,
`harness:code-shell`.

## The rule

- No comments, no docstrings, no doc comments (`/** */`, `///`). Names, types, small functions and tests carry the
  meaning. Needing a comment means the code should be clearer: rename, split, or type it.
- Never a comment about a change: no `# removed X`, `# was Y`, `# now uses Z`, `# moved to`, no commented-out code.
  The diff and the commit message say it.
- A missing branch raises with a message (`NotImplementedError`, `throw new Error`). Missing work goes in the
  project's plan file, never in a TODO comment.
- A constant's unit and meaning go in its name (`TIMEOUT_SECONDS`), and a test defends its value.

## What stays

Only text a machine reads: a shebang, an encoding line, a PEP 723 block, a license header the project requires, and a
directive a tool needs (`# type: ignore[...]` only where a language skill allows it, `// @ts-expect-error`,
`# shellcheck disable=`, `<!-- prettier-ignore -->`, `"use strict"`).

A docstring a program reads (`__doc__`, an argparse description) is replaced by a string literal in the code.

## Stripping

The harness plugin ships `bin/strip-comments` (Python, shell, JS, CSS, HTML): it removes comments and docstrings in
place, and `--check` lists what is left. A project can run it from a pre-commit hook.

## Proving a comments-only change

A change that only removes comments and docstrings must not change behaviour. Python: compare `ast.dump` of each file
before and after, docstrings stripped. JS and TS: the formatter's diff and `git diff` must touch comment lines only.

## What no tool checks

Whether a name says enough without a comment. The reviewer reads for it and asks "would the code be harder to read
without this name being clearer?".
