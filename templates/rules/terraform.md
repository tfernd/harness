---
paths:
  - "**/*.tf"
  - "**/*.tfvars"
---
- Before writing, moving or reviewing a Terraform file, load `harness:code-terraform`.
- Comments: `harness:comments`.
- Run `terraform fmt -check` and `terraform validate` before the report; their exit codes go in it. Never run `apply`
  or `destroy` unless the brief says so.
