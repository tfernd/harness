---
name: code-js
description: General JavaScript and TypeScript rules - Bun, strict TS, named exports, no any or enums, full-word names, module and error rules, biome and tsc setup. Load before writing, moving or reviewing any .js, .ts or .mjs file.
---

# JavaScript and TypeScript

Starting `biome.json` and `tsconfig.json`: `references/biome-tsconfig.md`.

Comments: `harness:comments`. Web pages: `harness:code-html-css`.

## Runtime and form

- Bun is the default runtime and package tool unless the project uses another. Never add a dependency unasked.
- ES modules only. Relative imports name the extension (`./color.ts`, `../shared/dom.js`). Group `import type` apart
  with `verbatimModuleSyntax` on.
- Two-space indent, double quotes, semicolons, 120 columns, trailing commas in multi-line lists. The formatter owns
  this; do not hand-format against it.

## TypeScript

- Strict compiler flags, listed once in `references/biome-tsconfig.md` (at least `strict`, `noUncheckedIndexedAccess`,
  `verbatimModuleSyntax`).
- Named exports only; no default exports.
- Banned: `any`, `enum`, `!` non-null assertions, `as` casts, `@ts-ignore`, `namespace`. Use a union of literals
  instead of an enum, a type guard or an `in` check instead of an assertion or a cast.
- A fixed group is a `type` with named fields, not a tuple or a loose object. A function with more than two
  parameters, or any boolean parameter, takes one destructured options object.
- A wrong input throws one sentence naming the value and what was expected.
- Arrow functions in a `const` by default; `function` where `this` is needed. Follow the file you edit.

## Names

- Full words saying what a thing is or does: `repoList`, `showRepos`, `isSelected`. Never `rl`, `e`, `i`, `btn`.
- Types, classes: PascalCase. Functions, variables, methods: lowerCamel. Fixed numbers: UPPER_SNAKE
  (`DEGREES_PER_RADIAN`). Folders lower case; an acronym is a word (`Svg`, `toSvg`).
- Booleans start with `is`, `has` or `can`. Functions are verbs (`createX`, `showX`, `listX`, `readX`).
- A name never shadows a type or a global (`number`, `string`, `name`).

## Design rules

- One job per function and per module. The same code is never written twice; a helper a second module needs moves to
  a shared folder, and a module never imports from a sibling feature.
- A server validates input where it enters: paths resolve inside their root, subprocesses take an argument list,
  never a shell string.
- A function that grows past what reads as one list of steps is split into named helpers (biome
  `noExcessiveCognitiveComplexity` flags size; the starter turns it on).

## Enforcing tools

- `bunx biome check .` (format, lint, imports); `bunx biome check --write` fixes. `bunx tsc --noEmit` for types.
  `bun test` for tests. Use the project's own gate; a project without one starts from `references/biome-tsconfig.md`.
- Run the gate once at the end of a piece of work, not after each step.

## What no tool checks

Biome and tsc do not catch these; each needs a project check (a script, a lint rule the project adds) or the reviewer:

- `as` casts (tsc allows them; only a project rule bans them) and `any` hidden behind a cast.
- A `catch` that returns a default instead of surfacing the error.
- `Math.random` or `Date.now` in code that must be reproducible.
- Name quality and verb choice, function size and blank-line layout, one job per module, sharing rather than copying,
  error sentences that name the value, input validation at entries.
