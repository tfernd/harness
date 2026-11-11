---
name: code
description: Rules for code in every language - no comments or docstrings, names that carry the meaning, no line wrapping, and (in a reference) how to refactor. Load before writing, moving, renaming or reviewing code in any language, and when a comment or a vague name is tempted.
---

# Code

Language rules: `harness:code-python`, `harness:code-js`, `harness:code-html-css`, `harness:code-terraform`,
`harness:code-shell`, `harness:code-sql`, `harness:code-yaml`, `harness:code-make`. Casing and idiom per language:
`references/languages.md`. Moving, renaming, splitting or merging code: `references/refactor.md`.

## No comments, no docstrings

- No comments, no docstrings, no doc comments (`/** */`, `///`). Names, types, small functions and tests carry the
  meaning. Needing a comment means the code should be clearer: rename (Naming below), split, or type it.
- Never a comment about a change: no `# removed X`, `# was Y`, `# now uses Z`, `# moved to`, no commented-out code.
  The diff and the commit message say it.
- A missing branch raises with a message (`NotImplementedError`, `throw new Error`). Missing work goes in the
  project's plan file, never in a TODO comment.
- A constant's unit and meaning go in its name (`TIMEOUT_SECONDS`), and a test defends its value.

## What stays

Only text a machine reads: a shebang, an encoding line, a PEP 723 block, a license header the project requires, and a
directive a tool needs (`# type: ignore[...]` only where a language skill allows it, `// @ts-expect-error`,
`# shellcheck disable=`, `<!-- prettier-ignore -->`, `"use strict"`), and the version comment after a pinned SHA (`uses: owner/action@<sha> # v4.1.0`), which Dependabot and Renovate read.

A docstring a program reads (`__doc__`, an argparse description) is replaced by a string literal in the code.

## No line wrapping

A signature, a call and a condition stay on one line, however long, so one grep returns the whole of it. A long
expression is split into named parts (Compound expressions below), never across lines.

## Naming

Code is read by agents that trust a name and do not reread the body. A misleading or empty name is a bug. The name
carries the meaning, so a comment or docstring means the name is wrong: rename first.

### Functions

| Rule | Bad | Good |
|---|---|---|
| A verb phrase saying what it does or returns | `check_weights()` | `is_finite_and_non_zero(weights)`, `raise_if_not_finite(weights)` |
| A predicate reads as a yes/no question: `is_`, `has_`, `can_` | `valid(user)` | `has_email(user)` |
| The name shows every side effect | `get_config()` that also writes a file | `read_config()` and `write_default_config()` |

### Variables and constants

| Rule | Bad | Good |
|---|---|---|
| Says what it holds | `data`, `result`, `tmp`, `x` | `unpaid_invoices`, `parsed_row` |
| Carries its unit | `timeout = 30` | `timeout_seconds = 30` |
| A collection is plural | `user_list`, `file` for many | `users`, `files` |
| No abbreviations | `cfg`, `btn`, `res` | `config`, `button`, `response` |
| No negatives | `is_not_disabled` | `is_enabled` |

Generic words never stand alone: `data`, `info`, `result`, `tmp`, `value`, `item`, `handle`, `process`, `manager`,
`util`, `helper`, `x`. Add what makes them specific (`item` becomes `cart_item`), or drop the word.

### Across a codebase

- One word per concept. If `fetch` reads from the network, `get` computes and `load` reads a file, each keeps that
  meaning everywhere; never `fetch_user` beside `get_order` for the same act. Grep the project's verb before choosing.
- Use the domain's own words, as its owners say them, not a synonym of your own.
- Names that grep: distinct enough that a search finds every use and nothing else. Avoid a name that is a substring
  of many others, and keep a literal key (a column, a CSS class, a config key) spelled the same at each use.

### Compound expressions

Split a long condition into named parts. A name longer than the expression it replaces is fine.

```python
x = a > 0 and b != "" and c in allowed

is_positive = a > 0
has_label = b != ""
is_allowed = c in allowed
is_valid = is_positive and has_label and is_allowed
```

### Renaming

- Rename when the meaning changes. A function that now also deletes is renamed in the same change.
- Update every caller, test and doc (grep the old name); leave no old name behind.
- A rename alone is a refactor (`references/refactor.md`): no behaviour change in the same commit.

## What no tool checks

Whether a name says enough without a comment ("would the code be harder to read without this name being clearer?"), whether a name is true to the body, whether two names mean one concept, and whether a domain word is the owners'.
A linter checks casing and length at most; the reviewer reads for the rest (`harness:review`).
