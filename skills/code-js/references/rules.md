# Rules in full and tool configuration

Every rule below is checkable by eye or by the named tool. Rule names are Biome or typescript-eslint names; confirm
each against the installed version (`biome explain <rule>`, the ESLint plugin docs) before turning it on, since
Biome moves rules between groups and versions.

## Types and exports

- `noExplicitAny` (Biome), `@typescript-eslint/no-explicit-any`: no `any`.
- `noNonNullAssertion` (Biome): no `!`.
- `noEnum`, `noNamespace`, `noDefaultExport` (Biome style group).
- `noBarrelFile`, `noReExportAll` (Biome performance group); override off for the one public entry file.
- `noTsIgnore` (Biome): use `@ts-expect-error` with a reason only when unavoidable.
- `as` casts: Biome has no ban. ESLint: `@typescript-eslint/consistent-type-assertions` with
  `assertionStyle: "never"`, or a project script on the syntax tree. `as const` stays allowed.
- Exhaustive switch: `@typescript-eslint/switch-exhaustiveness-check`; or the `assertNever` helper in the default
  branch, which fails to compile when a variant is missing:

```ts
export const assertNever = (value: never): never => {
  throw new Error(`Unhandled variant: ${JSON.stringify(value)}`);
};
```

## Boundary parsing

- `JSON.parse`, `response.json()`, storage reads, message payloads and DOM datasets are `unknown`.
- A parser function returns the named type or throws/returns an error value naming the field. A schema library only
  with the project's yes; otherwise hand-written guards (`typeof`, `in`, `Array.isArray`).
- After the parser, no further shape checks on the same value.

## Errors and promises

- Result value for expected failure; thrown `Error` with `{ cause }` for a broken contract.
- ESLint: `@typescript-eslint/no-floating-promises`, `no-misused-promises`, `only-throw-error`. Biome: its
  floating-promise rule where the installed version has one. `no-empty` / `noUselessCatch` flag some bad catches only.
- Abort: pass `signal` to `fetch` and to listeners; a loader keeps one request in flight and drops stale answers.

## Immutability and state

- Compiler: `readonly` on fields and arrays; `Readonly<T>`, `ReadonlyArray<T>`. Lint: `prefer-const`,
  `noParameterAssign` (Biome).
- Module-level `let`, or an exported mutable object: ESLint `no-restricted-syntax` on a top-level `let`, or a script.

## Size and structure

- Function about 30 lines, file about 500 lines: a project may enforce by a script that counts lines per file.
  Complexity: Biome `noExcessiveCognitiveComplexity`; ESLint `complexity`, `max-lines-per-function`.
- Dependency direction: Biome `noRestrictedImports` / ESLint `no-restricted-imports` with patterns per folder, or
  `eslint-plugin-boundaries`, or a script that reads import specifiers from the syntax tree. Write the allowed
  directions once (for example `shared <- features <- app`).
- Engines or heavy third-party libraries are imported in one folder only.

## DOM

- A script over the syntax tree (not a regex) can flag `innerHTML`, `outerHTML`, `insertAdjacentHTML`,
  `querySelector`/`closest`/`matches` with a `.` or `#` selector, `getElementById`, and `on*` attributes in HTML.
- Keep `data-` names literal at the call site so a check can match them to the markup.
