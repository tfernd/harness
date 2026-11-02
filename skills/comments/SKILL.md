---
name: comments
description: How to write comments and docstrings in any language - when one stays, its form, what never goes in. Load when adding, editing or reviewing a comment or docstring.
---

# Comments and docstrings

Language rules: `harness:code-python`, `harness:code-js`,
`harness:code-html-css`, `harness:code-terraform`.

## When a comment stays

A comment stays only when it says why, states an invariant, or warns of a trap. Delete one that repeats the name, the
signature or the next line. A better name beats a comment.

## Never in a comment or docstring

- A file path or file name.
- Agents, sessions, tickets, dates, who asked for it.
- How the code came to be, what it replaced, an experiment story.
- A claim about another file's behaviour that nothing keeps true; name the symbol instead.

A reviewer lists the comment lines of a diff with `git diff -U0 | rg '^\+\s*(#|//|\*|/\*)'` and runs
`rg -n '[A-Za-z_/]+\.(py|ts|js|css|html|tf)\b'` over them for file names, and `rg -n '\b20[0-9]{2}-[0-9]{2}'` for
dates (the patterns are a starting point, not a gate).

## Form

- A comment on its own line starts with a capital and ends with a period.
- A trailing comment is a fragment (a shape, a few words of why): lowercase, no period. If it pushes the line past the
  limit, move it above the line.
- A comment sits directly above what it explains. No banner art. A language skill may define one section divider (`harness:code-python` does).
- `TODO(<topic>): <what is missing>`. A planned branch that is missing raises `NotImplementedError` (Python) or
  throws an `Error` (JS, TS) with the same message. A missing module is tracked in the project plan, not by a TODO
  elsewhere.

## Docstrings and doc comments

- A module or script opens with 1 to 3 lines saying its job and, when useful, what it does not do. A script says what
  it measures or does, and the command.
- The first line of a function, class or method is a summary in plain words, at most 100 characters: what it
  returns or does. A property or one-line function gets only that.
- A class says in one sentence what it represents; each field gets a short comment.
- After the summary, only if needed and at most 4 short lines: an edge case that happens (zero, empty, ties, a
  sign); a `Note:` for what a caller must know that is not about the result (precision, a sync, a memory cost); what
  `None` or `undefined` means for an optional parameter.
- No `Args:` / `Returns:` / `@param` / `@returns` blocks where the type hints already carry them (`@param` is allowed in
  plain JS, where there are no type hints). No examples. No
  proofs or derivations: point to the doc section by its heading.
- Words before notation. A function, class or module may be named in backticks.
- A project may require a doc line on every top-level item (a common TypeScript rule). Then it is one
  `/** */` line saying what the item is or does, and the project's rules file says so. Without that rule, do not add
  one that repeats the name.

## A constant's comment

It sits above the constant, and a reader can check it against the value: what it counts or measures in the domain's
words; its unit and per what (bytes, items per batch, a fraction of memory); why that value, the rule or limit that
fixes it. "A fraction" alone is not a comment. A value nobody measured says `# TODO(benchmark): <what would measure
it>` and a test defends it.

## Proving a comments-only change

A change to comments and docstrings only must not change behaviour. Python: compare `ast.dump` of each file before
and after, docstrings stripped. JS and TS: the formatter's diff and `git diff` must touch comment lines only.

## What no tool checks

Whether a comment says why rather than what. The reviewer reads every added comment and asks "would the code be
harder to read without it?". A tool can only check form, and little of it: nothing by default checks the capital or the final period (ruff's `D`
rules do, when the project enables them; ruff `E`/`W` and biome do not), and none checks the sentence.
