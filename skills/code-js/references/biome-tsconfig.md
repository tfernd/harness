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
      "recommended": true,
      "complexity": { "noExcessiveCognitiveComplexity": "error" },
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

`useIgnoreFile: true` needs a `.gitignore`; with none, set it to `false`.

An override turns `noBarrelFile` and `noReExportAll` off for the one public entry file (`src/index.ts`).

`tsconfig.json` compiler options (the one list; `harness:code-js` points here): `strict`, `skipLibCheck`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`,
`noImplicitOverride`, `noFallthroughCasesInSwitch`, `erasableSyntaxOnly`, `verbatimModuleSyntax`,
`allowImportingTsExtensions`, `noEmit`, `target` and `module` `esnext`, `moduleResolution` `bundler`.
