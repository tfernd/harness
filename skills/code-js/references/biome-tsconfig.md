# Starting biome and tsconfig

A starter pair. Copy only when the project has none; adjust `include` and `types`.

`biome.json`:

```json
{
  "vcs": { "enabled": true, "clientKind": "git", "useIgnoreFile": true },
  "formatter": { "enabled": true, "indentStyle": "space", "indentWidth": 2, "lineWidth": 120 },
  "linter": {
    "enabled": true,
    "rules": {
      "preset": "recommended",
      "suspicious": { "noExplicitAny": "error" },
      "style": {
        "noNonNullAssertion": "error",
        "noDefaultExport": "error",
        "noEnum": "error",
        "noNamespace": "error"
      },
      "performance": { "noBarrelFile": "error", "noReExportAll": "error" }
    }
  }
}
```

`useIgnoreFile: true` makes `biome check` fail in a folder with no `.gitignore`: the starter needs one (or set
`useIgnoreFile` to `false`). Source: an audit probe of this starter in a folder with no `.gitignore` (`scratch/audit-b/js`); not re-run when this
line was written.

An override turns `noBarrelFile` and `noReExportAll` off for the one public entry file (`src/index.ts`).

`tsconfig.json` compiler options: `strict`, `skipLibCheck`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`,
`noImplicitOverride`, `noFallthroughCasesInSwitch`, `erasableSyntaxOnly`, `verbatimModuleSyntax`,
`allowImportingTsExtensions`, `noEmit`, `target` and `module` `esnext`, `moduleResolution` `bundler`.
