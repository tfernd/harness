---
paths:
  - "**/*.ts"
  - "**/*.tsx"
  - "**/*.js"
  - "**/*.jsx"
  - "**/*.mjs"
---
- Before writing, moving or reviewing a JavaScript or TypeScript file, load `harness:code-js`.
- Comments and docstrings: `harness:comments`.
- Core rules: strict types, named exports only, no `any`/`enum`/`as`/`!`, parse input at the boundary, errors keep
  their `cause` and are never swallowed, full-word names, no module-level mutable state.
- Run the project's lint, format and type checks (named in `AGENTS.md`) before the report; their exit codes go in it.
