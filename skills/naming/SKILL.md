---
name: naming
description: The one home for naming rules - a name says what a thing holds or does, so code needs no comment. Load before writing, renaming or reviewing any function, variable, constant, file, key or target, and when a comment is tempted.
---

# Naming

Code is read by agents that trust a name and do not reread the body. A misleading or empty name is a bug. The name
carries the meaning, so a comment or docstring (`harness:comments`) means the name is wrong: rename first.
Casing and idiom per language: `references/languages.md`.

## Functions

| Rule | Bad | Good |
|---|---|---|
| A verb phrase saying what it does or returns | `check_weights()` | `is_finite_and_non_zero(weights)`, `raise_if_not_finite(weights)` |
| A predicate reads as a yes/no question: `is_`, `has_`, `can_` | `valid(user)` | `has_email(user)` |
| The name shows every side effect | `get_config()` that also writes a file | `read_config()` and `write_default_config()` |

## Variables and constants

| Rule | Bad | Good |
|---|---|---|
| Says what it holds | `data`, `result`, `tmp`, `x` | `unpaid_invoices`, `parsed_row` |
| Carries its unit | `timeout = 30` | `timeout_seconds = 30` |
| A collection is plural | `user_list`, `file` for many | `users`, `files` |
| No abbreviations | `cfg`, `btn`, `res` | `config`, `button`, `response` |
| No negatives | `is_not_disabled` | `is_enabled` |

Generic words never stand alone: `data`, `info`, `result`, `tmp`, `value`, `item`, `handle`, `process`, `manager`,
`util`, `helper`, `x`. Add what makes them specific (`item` becomes `cart_item`), or drop the word.

## Across a codebase

- One word per concept. If `fetch` reads from the network, `get` computes and `load` reads a file, each keeps that
  meaning everywhere; never `fetch_user` beside `get_order` for the same act. Grep the project's verb before choosing.
- Use the domain's own words, as its owners say them, not a synonym of your own.
- Names that grep: distinct enough that a search finds every use and nothing else. Avoid a name that is a substring
  of many others, and keep a literal key (a column, a CSS class, a config key) spelled the same at each use.

## Compound expressions

Split a long condition into named parts. A name longer than the expression it replaces is fine.

```python
x = a > 0 and b != "" and c in allowed

is_positive = a > 0
has_label = b != ""
is_allowed = c in allowed
is_valid = is_positive and has_label and is_allowed
```

## Renaming

- Rename when the meaning changes. A function that now also deletes is renamed in the same change.
- Update every caller, test and doc (grep the old name); leave no old name behind.
- A rename alone is a refactor (`harness:refactor`): no behaviour change in the same commit.

## What no tool checks

Whether a name is true to the body, whether two names mean one concept, and whether a domain word is the owners'.
A linter checks casing and length at most; the reviewer reads for the rest (`harness:review`).
