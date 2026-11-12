---
name: code-terraform
description: Terraform style from HashiCorp's published conventions - file layout, naming, argument order, variables and outputs, version pinning, secrets, fmt and validate. Load before writing, moving or reviewing any .tf or .tfvars file.
---

# Terraform

Every rule here is HashiCorp's published style guide
(`https://developer.hashicorp.com/terraform/language/style`, read for this skill). No comments or docstrings: `harness:code`.

## Format

- Two spaces per nesting level. Align the `=` of consecutive single-line arguments. `terraform fmt` does this, and
  only this: it aligns and indents.
- Arguments first, nested blocks after, a blank line between; the order inside a resource is under "Naming and order".
- Blank line between top-level blocks. Repeated nested blocks of one type stay together without gaps.
- No comments (`harness:code`); variable and output `description` arguments stay, they are data.

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

Split a large `main.tf` by domain (`network.tf`, `storage.tf`, `compute.tf`). `override.tf` is rare.
Local modules live in `./modules/<module_name>`.

## Naming and order

- Descriptive nouns with underscores, for resources, variables, outputs and locals alike. Do not repeat the resource
  type in its name (`aws_instance.web`, not `aws_instance.web_instance`).
- Type and name are both quoted in a declaration.
- Data sources before the resources that use them. Inside a resource: `count`/`for_each` (then a blank line),
  plain arguments, block arguments, `lifecycle`, `depends_on`.
- `count` for nearly identical copies and for optional creation (`count = var.enabled ? 1 : 0`); `for_each` when each
  instance needs distinct values.

## Variables, outputs, locals

- A `.tf` file holds no literal for a value that differs between deployments (names, ids, sizes, lists); it goes in `.tfvars`, behind a variable.
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
- A git-sourced module in stage, prod and any shared environment pins to a release tag, a major-line tag or a commit SHA
  (`?ref=`), never a branch; a sandbox may use a branch while testing.
- Never commit state files, `.terraform/`, saved plans, or `.tfvars` with secrets. Commit `.terraform.lock.hcl` in root
  configurations only, never in a child module; commit the `.gitignore` and a README. Prefer short-lived credentials or a secrets manager to static keys.
- Share data between workspaces through `tfe_outputs` and provider data sources; avoid sharing full state files.

## Running and committing

- Never run `plan` or `apply` against a real backend or account; a local plan with no refresh and no lock is fine.
  Deploys are the owner's: hand over the commands in run order, one copy-paste block each. Never act on a workspace
  while the owner is applying it.
- The harness guard asks before `terraform`, `tofu` or `terragrunt` `apply`, `destroy`, `import`, `taint`, `untaint`, `force-unlock`, `state rm|mv|push` and `workspace delete`, and before `output` (it prints secrets).
- Copy the nearest working sibling workspace or module before writing a new one, and follow the repo's own file-naming
  and folder pattern for `.tfvars` and workspaces.
- Declare apply order between workspaces (platform before project) where the repo's deploy tool supports it.
- `validate` misses plan-time errors (invalid index, unsupported attribute): read the empty-input and `count = 0` paths
  by hand, and say what only a plan can prove.
- The repo's own pre-commit hook is the gate; run it once per unit, not after each edit. `fmt` and `validate` (below)
  are the fallback when the repo has none.
- Never commit build artifacts (zips, plans, state, `.terraform/`).
- A branch gone stale after another merge is updated from the base before pushing.
- A change to a folder's `.tf` or `.tfvars` updates that folder's README in the same commit.
- JSON inside a `.tfvars` string is parsed in the gate (`jsondecode` or a JSON linter); `validate` does not check it.

## Enforcing tools

- `terraform fmt -check -recursive` (it skips subfolders without `-recursive`) and `terraform validate` (syntax and types
  only; run `terraform init -backend=false` first). Run `terraform version` first.
- TFLint is the guide's suggested linter for further rules; if `tflint` is missing, report TFLint as Not proven.
- `terraform test` for modules, run in CI (guide).

## What no tool checks

`terraform fmt` aligns and indents only. The reviewer reads the rest: argument order, blank lines between blocks,
the stable order of variables and outputs, descriptions on variables and outputs, descriptive names,
not repeating the type in a name, file split by domain, whether a variable should be exposed at all, and whether a name
says enough.
