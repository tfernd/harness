---
name: code-python
description: Python style and checkable rules - names, signatures, types, function size, layout, dispatch, errors, the ruff and type-checker setup. Load before writing, moving or reviewing any .py file.
---

# Python

No comments or docstrings: `harness:comments`. Tests: `harness:testing`.

## Procedure

1. Read first, in bulk: the brief's inputs, the code you change, every caller (grep the name). Grep before writing a
   helper; import what exists.
2. Write the whole unit, code and tests, before running anything.
3. Self-review the diff: every caller updated, no old name left, types and shapes at every step, edge cases (empty,
   zero, one element, ties, a sign), each test would fail on a plausible bug.
4. Run the formatter and linter once, then the project's gate. Never weaken a check to pass it.

## Names

- What a name must say, and the verbs and booleans: `harness:naming`.
- Casing: `snake_case` functions and variables, `PascalCase` classes, `UPPER_SNAKE` constants; a count is
  `num_<things>` (`num_files`).

## Signatures and types

- `from __future__ import annotations` first (redundant only on Python 3.14 or newer, where annotations are deferred;
  the starter targets 3.12); then three import blocks (standard library, third party, relative).
- Type hints on every signature; no `Any` where a type exists.
- `/` after the positional inputs and `*` before options, so options are keyword-only.
- No default for a value the caller must decide (a path, a unit, a size).
- A small closed set is a `Literal`, with the tuple of all its values beside it
  (`Mode = Literal["fast", "exact"]` and `MODES: tuple[Mode, ...] = ("fast", "exact")`). A size that is not a finite set is
  an `int`, checked once where it enters.
- No `typing.cast` and no checker ignore comment (`# type: ignore`, `# noqa`, `# pyright:`). Narrow with
  `isinstance`, `assert`, `match` or a lookup table typed to the `Literal`; if a third-party stub forces one, narrow
  with `isinstance` or `assert` and say why in the report.
- A fixed group of results is a `NamedTuple` or a frozen `dataclass`, never a `dict` and never optional fields filled
  by convention. A function returning a dict because its keys are data says so on its signature's closing line.
- No `.0` on a whole number unless it is a float on purpose.

## Functions

- One job each. The ruff complexity limit fails a function that branches more: split it, never raise the limit.
- A function reads in phases separated by blank lines: checks, preparation, compute, return. Every intermediate has a
  name.
- Two functions that differ by one step become one with an optional parameter whose name or type says what `None` means,
  or a function-valued parameter.
- Public entry points (called from outside the module) raise `ValueError` or `TypeError` for bad caller input, once,
  where it enters. Internal invariants use `assert` (stripped under `-O`, so never for input).
- Dispatch over a closed set is one `match`; `case _: raise` only over an unchecked outside value. Ties go by order
  and the function's name says so.
- No `global`, no module-level mutable state (a list, dict, set or cache changed at run time; frozen constants such as
  a tuple, a `frozenset` or a number are fine). No `_private` functions (a leading underscore hides a helper that
  should be shared or deleted), aliases (`old = new`), re-exports or one-line wrappers: change the callers.
- A guarded division is a named helper, not a multiply by a reciprocal.

## Layout

- One job per module, the one its name says.
- A module with more than one topic is split into modules. Within a module, types come first, then functions, a helper
  before its first caller.
- A call or signature that fits the line limit is one line, however many arguments. One that does not gets one
  argument per line with a trailing comma and the closer on its own line. Name an intermediate rather than hugging
  all arguments on one middle line. (Unenforced: `ruff format` keeps a left-over magic trailing comma exploded.)
- A constant is defined once and imported, never copied into a test or script.
- Imports point down a fixed order of layers; a step two layers need moves to the earlier one.
- An `__init__.py` holds only imports and `__all__`. A new module stays out of it until accepted.

## Enforcing tools

`ruff format` and `ruff check`, plus a type checker (`ty`) on the same files. Run them as the project's `make`/`uv`
targets say; a project without a config starts from `references/pyproject-ruff.md`, which holds the line length, the
rule set and the complexity limit.

## Scripts and dependencies

- A saved standalone script carries a PEP 723 header in its comment block: `requires-python`, `dependencies` and
  `[tool.uv]` with `exclude-newer = "7 days"`. It runs with `uv run --script`.
- A project sets `[tool.uv]` `exclude-newer = "7 days"` in `pyproject.toml`. uv then ignores releases newer than 7
  days, so a fresh broken or compromised release is not picked up.
- Throwaway Python inside a tool call (`python3 - <<'EOF'` to edit a file or inspect data) takes no header: it uses
  the standard library, and a header wastes tokens.

## What no tool checks

Verbs and nouns, one word per idea, one job per function and module, phases and blank lines, `Literal` vs `int`,
no-`dict` results, a module of one topic, import layering. The reviewer reads for these; a rule that keeps failing gets a
project gate.

Ruff and the type checker also let these through unless the project adds a check of its own:

- `typing.cast` and ignore comments (`# type: ignore`, `# noqa`): the config in `references/pyproject-ruff.md` does not
  ban them; a project check (a grep in its gate) does.
- Missing annotations on a signature: the selected ruff rules do not require them; the project needs a check.
- One-line calls: `ruff format` keeps a call with a magic trailing comma exploded, one argument per line, so a
  call that fits one line stays long if someone left the comma. Only a project script catches it.
