---
paths:
  - "tests/**"
  - "**/test_*.py"
  - "**/*.test.*"
  - "**/*.spec.*"
---
- Before writing or reviewing a test, load `harness:testing`.
- A new judge is shown to fail once under a deliberate bug, on a copy under the scratch folder, before it is trusted.
- A bug fix starts with a test that fails for the reported cause (`harness:workflows`).
