---
name: code-terraform
description: Terraform style from HashiCorp's published conventions - file layout, naming, argument order, variables and outputs, version pinning, secrets, fmt and validate. Load before writing, moving or reviewing any .tf or .tfvars file.
---

# Terraform

Every rule here is HashiCorp's published style guide
(`https://developer.hashicorp.com/terraform/language/style`, read for this skill). Comments: `harness:comments`.

## Format

- Two spaces per nesting level. Align the `=` of consecutive single-line arguments. `terraform fmt` does this, and
  only this: it aligns and indents.
- Arguments first, nested blocks after, a blank line between; the order inside a resource is under "Naming and order".
- Blank line between top-level blocks. Repeated nested blocks of one type stay together without gaps.
- Comments use `#`, never `//` or `/* */`, and only where the logic is genuinely complex.

## Files

| File | Holds |
|---|---|
| `terraform.tf` | `required_version`, `required_providers` |
| `providers.tf` | provider blocks, the unaliased default first |
| `backend.tf` | backend configuration |
| `main.tf` | resources and data sources |
| `variables.tf` | variables, in one stable order (alphabetical by default) |
| `outputs.tf` | outputs, in one stable order (alphabetical by default) |
| `locals.tf` | shared locals; file-only locals sit at the top of that file |

Split a large `main.tf` by domain (`network.tf`, `storage.tf`, `compute.tf`). `override.tf` is rare and commented.
Local modules live in `./modules/<module_name>`.

## Naming and order

- Descriptive nouns with underscores, for resources, variables, outputs and locals alike. Do not repeat the resource
  type in its name (`aws_instance.web`, not `aws_instance.web_instance`).
- Type and name are both quoted in a declaration.
- Data sources before the resources that use them. Inside a resource: `count`/`for_each` (then a blank line),
  plain arguments, block arguments, `lifecycle`, `depends_on`.
- `count` for nearly identical copies and for optional creation (`count = var.enabled ? 1 : 0`); `for_each` when each
  instance needs distinct values. Comment them when the effect is not obvious.

## Variables, outputs, locals

- Every variable has `type` and `description`, in the order type, description, default, sensitive, validation. Give a
  default to an optional one. Expose only settings that differ between deployments.
- `sensitive = true` on secrets (values still appear in plain text in state). `validation` only for strict
  requirements.
- A secret that must not reach state: an `ephemeral` variable or output, and a write-only argument (`*_wo`) where the
  provider has one; `sensitive` only hides it from output.
- Every output has `description`, in the order description, value, sensitive.
- Locals sparingly.

## Versions and secrets

- Pin providers in `required_providers`; set `required_version`; pin registry modules to a major and minor version
  (`version` is ignored for local modules).
- Never commit state files, `.terraform/`, saved plans, or `.tfvars` with secrets. Commit `.terraform.lock.hcl`, the
  `.gitignore` and a README. Prefer short-lived credentials or a secrets manager to static keys.
- Share data between workspaces through `tfe_outputs` and provider data sources; avoid sharing full state files.

## Enforcing tools

- `terraform fmt -check -recursive` (it skips subfolders without `-recursive`) and `terraform validate` (syntax and types
  only; run `terraform init -backend=false` first). Run `terraform version` first.
- TFLint is the guide's suggested linter for further rules; if `tflint` is missing, report TFLint as Not proven.
- `terraform test` for modules, run in CI (guide).

## What no tool checks

`terraform fmt` aligns and indents only. The reviewer reads the rest: argument order, blank lines between blocks,
comment style, the stable order of variables and outputs, descriptions on variables and outputs, descriptive names,
not repeating the type in a name, file split by domain, whether a variable should be exposed at all, and whether a
comment is needed.
