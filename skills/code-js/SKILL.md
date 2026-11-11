---
name: code-js
description: General JavaScript and TypeScript rules - strict TS, named exports, no any/enum/casts, full-word names, parse at the boundary, errors with cause, module and DOM rules, tsc and Biome or ESLint setup. Load before writing, moving or reviewing any .js, .ts or .mjs file.
---

# JavaScript and TypeScript

Goal: code a reader checks by eye or a tool checks for them: types that cannot lie, errors that surface, modules with
one job. Long lists and tool starters: `references/rules.md`, `references/biome-tsconfig.md`.

No comments or docstrings: `harness:comments`. Web pages: `harness:code-html-css`.

## Runtime and form

- Use the project's runtime and package tool (Bun, Node or a browser); commands below are examples. Never add a
  dependency unasked.
- ES modules only. Relative imports name the extension the project's resolver needs. Group `import type` apart with
  `verbatimModuleSyntax` on.
- Two-space indent, double quotes, semicolons, 120 columns, trailing commas in multi-line lists. The formatter owns this.
- Plain JavaScript gets no JSDoc types and no `// @ts-check`. If you want types, use TypeScript.

## Types

- Strict compiler flags, listed once in `references/biome-tsconfig.md`.
- Named exports only; no default exports. No barrel files; one public entry file may re-export.
- Banned: `any`, `enum`, `!` non-null assertions, `as` casts (except `as const`), `@ts-ignore`, `namespace`. Use a union
  of literals for an enum, a type guard or an `in` check for a cast.
- Parse at the boundary: input from a network, file, storage, DOM or `JSON.parse` is `unknown`, checked once by a
  parser or guard into a named type. Inside, trust the type; do not re-check.
- A variant type is a discriminated union (a literal `kind` field). A `switch` over it is exhaustive: the last branch
  calls `assertNever(value)`.
- A fixed group is a `type` with named fields, not a tuple or loose object. More than two parameters, or any boolean
  parameter, means one destructured options object.
- Data is immutable by default: `readonly` fields and arrays, `const`, new values instead of mutation.
- Arrow functions in a `const` by default; `function` where `this` is needed. Follow the file you edit.

## Errors and async

- A wrong input throws an `Error` with one sentence naming the value and what was expected. Rethrow with
  `new Error(message, { cause })`. Where failure is expected, return a result value (`{ ok: true, value }` or
  `{ ok: false, error }`) instead of throwing.
- Never swallow: a `catch` rethrows, returns a typed error, or reports it. It never returns a default or stays empty.
- No floating promises: each one is awaited, returned or handed to a named handler that reports its failure.
- Async work that outlives its caller (fetch, timer, listener, stream) is cancellable through an `AbortSignal` or
  returns its cleanup; the latest request wins, stale answers are dropped.
- `Math.random` and `Date.now` are injected (a parameter or a clock) where output must be reproducible or testable.

## Names

- What a name must say, and the verbs and booleans: `harness:naming`.
- Types, classes: PascalCase. Functions, variables, methods: lowerCamel. Fixed numbers: UPPER_SNAKE. Folders lower
  case; an acronym is a word (`Svg`, `toSvg`).
- A name never shadows a type or a global (`number`, `string`, `name`).

## Modules and size

- One job per function and per module; the same code is never written twice. A helper a second module needs moves to
  a shared folder.
- Size: a function over about 30 lines, or one whose steps need separating, is split into named helpers
  (biome `noExcessiveCognitiveComplexity` flags complexity). A file over about 500 lines is split by job.
- Dependency direction: shared code imports nothing from features; a feature never imports a sibling feature; a
  low-level folder never imports a higher one. Check with the project's import rule or a script.
- No module-level mutable state (`let`, mutable object or array at top level). State lives in the caller or in one
  named store; an event hub or cache is the only exception, and it is named as such.
- Test seams: side effects (clock, random, network, file system, DOM) enter as parameters or a small interface, so a
  test passes a fake. Pure logic sits apart from the code that does I/O.
- A server validates input where it enters: paths resolve inside their root, subprocesses take an argument list,
  never a shell string.

## DOM, if the project has a browser UI

- Build nodes with `createElement` and `textContent`; never `innerHTML`, `outerHTML` or `insertAdjacentHTML`.
- DOM access goes through one small layer of helpers; feature code does not call `document` directly.
- Select by a `data-` attribute, never by a style class or id, scoped to a root (`root.querySelector`). Styling uses
  classes, scripts use `data-` attributes.
- Events by delegation on a root; no inline `onclick` attributes. Listeners are removed with the element or an
  `AbortSignal`.
- Never set an input's value while it has focus. Update lists by key, so focus and scroll survive.

## Enforcing tools

- Types: `tsc --noEmit` with the flags in `references/biome-tsconfig.md`. Lint and format: Biome or ESLint with
  typescript-eslint, whichever the project has; rule names and config in `references/rules.md`. Tests: the runtime's
  runner (`bun test`, `node --test`, or the project's).
- Use the project's own gate; a project without one starts from `references/biome-tsconfig.md`.
- Run the gate once at the end of a piece of work, not after each step.

## What no tool checks

Each needs a project check (a script, an added lint rule) or the reviewer:

- `as` casts and `any` hidden behind a cast, unless the project bans them with a rule.
- A `catch` that returns a default instead of surfacing the error.
- Name quality and verb choice, one job per module, sharing rather than copying, function size, error sentences that
  name the value, validation at entries, dependency direction without an import rule.
- That a boundary really parses (a type annotation on `JSON.parse` output is a cast in disguise).
- That async work is cancellable and no module keeps hidden state.
