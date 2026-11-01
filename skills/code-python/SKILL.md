---
name: code-python
description: Python style and checkable rules - names, signatures, types, function size, layout, dispatch, errors, the ruff and type-checker setup. Load before writing, moving or reviewing any .py file.
---

# Python

Comments and docstrings: `harness:comments`. Tests: `harness:testing`.

## Procedure

1. Read first, in bulk: the brief's inputs, the code you change, every caller (grep the name). Grep before writing a
   helper; import what exists.
2. Write the whole unit, code and tests, before running anything.
3. Self-review the diff: every caller updated, no old name left, types and shapes at every step, edge cases (empty,
   zero, one element, ties, a sign), each test would fail on a plausible bug.
4. Run the formatter and linter once, then the project's gate. Never weaken a check to pass it.

## Names

- Functions are verbs, one verb per kind of job, kept the same across the project: `get_*` computes a value, `make_*`
  builds an object from parts, `search_*` picks by a score. A project adds its own verbs for its own kinds of job.
- Data is a noun; a collection is plural for what each element is; a count is `num_<things>`; a candidate is
  `candidate_<x>`; the running winner is `best_<x>`.
- No single letters or clipped words (`n`, `tmp`, `res`, `cfg`). One word per idea, project-wide.
- Booleans read as a statement: `is_better`, `has_zero`. A non-trivial boolean expression is named.

## Signatures and types

- `from __future__ import annotations` first; then three import blocks (standard library, third party, relative).
- Type hints on every signature; no `Any` where a type exists.
- `/` after the positional inputs and `*` before options, so options are keyword-only.
- No default for a value the caller must decide (a device, a dtype, a size).
- A small closed set is a `Literal`, with the tuple of all its values beside it. A size that is not a finite set is
  an `int`, checked once where it enters.
- No `typing.cast` and no ignore comment of any checker (`# type: ignore`, `# noqa`, `# pyright:`). Narrow with
  `isinstance`, `assert`, `match` or a lookup table typed to the `Literal`.
- A fixed group of results is a `NamedTuple` or a frozen `dataclass`, never a `dict` and never optional fields filled
  by convention. A function returning a dict because its keys are data says so on its signature's closing line.
- No `.0` on a whole number unless it is a float on purpose.

## Functions

- One job each. The ruff complexity limit (`max-complexity = 9` in the starter config) fails a function that
  branches more: split it, never raise the limit.
- A function reads in phases separated by blank lines: checks, preparation, compute, return. Every intermediate has a
  name.
- Two functions that differ by one step become one with an optional parameter whose docstring says what `None` means,
  or a function-valued parameter.
- Checks (`ValueError`, `TypeError`) only at public entries, once, where input enters. Inside, plain `assert`.
- Dispatch over a closed set is one `match`; `case _: raise` only over an unchecked outside value. Ties go by order
  and the docstring says so.
- No `global`, no module-level mutable state. No `_private` helpers, aliases (`old = new`), re-exports or one-line
  wrappers: change the callers.
- A guarded division is a named helper, not a multiply by a reciprocal.

## Layout

- One job per module, the one its name says, stated in its docstring.
- A module with more than one topic has sections: a divider line, a Title Case title, a divider line; a section
  holds its types, then its functions, a helper before its first caller. Divider: `# ` plus 75 `=`.
- A call or signature that fits the line limit is one line, however many arguments. One that does not gets one
  argument per line with a trailing comma and the closer on its own line. Name an intermediate rather than hugging
  all arguments on one middle line.
- A constant is defined once and imported, never copied into a test or script.
- Imports point down a fixed order of layers; a step two layers need moves to the earlier one.
- An `__init__.py` holds only imports and `__all__`. A new module stays out of it until accepted.

## Enforcing tools

Starter setup: `ruff format` (line length 130, double quotes, spaces, `docstring-code-format`)
and `ruff check` with `E W F I B UP C90 SIM RET PLW0602 PLW0603 ARG`, `E501` ignored (the formatter owns layout),
`max-complexity = 9`, tests exempt from `C901` and `ARG`. A type checker (`ty`) runs on the same files. Run them as
the project's `make`/`uv` targets say; a project without a config starts from `references/pyproject-ruff.md`. Use the project's package tool only, and never resolve or install packages unasked.

## What no tool checks

Verbs and nouns, one word per idea, one job per function and module, phases and blank lines, `Literal` vs `int`,
no-`dict` results, section dividers, import layering. The reviewer reads for these; a rule that keeps failing gets a
project gate (`harness:retro`).

Ruff and the type checker also let these through unless the project adds a check of its own:

- `typing.cast` and ignore comments (`# type: ignore`, `# noqa`): the config in `references/pyproject-ruff.md` does not
  ban them; a project check (a grep in its gate) does.
- Missing annotations on a signature: the selected ruff rules do not require them; the project needs a check.
- One-line calls: `ruff format` keeps a call with a magic trailing comma exploded, one argument per line, so a
  call that fits one line stays long if someone left the comma. Only a project script catches it.
