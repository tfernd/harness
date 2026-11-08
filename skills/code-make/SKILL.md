---
name: code-make
description: Makefile and .mk rules - a help target built from ## text, .PHONY, strict bash flags, guarded rm, real-file prerequisites, dry runs before destructive targets. Load before writing, moving or reviewing a Makefile or a .mk file.
---

# Makefile

No comments or docstrings: `harness:comments`. The `## ` text after a target is data that `make help` prints, so it stays.
Recipes are shell: `harness:code-shell`.

## Header

Start the file with these lines, in this order:

```make
.DEFAULT_GOAL := help
SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
MAKEFLAGS += --warn-undefined-variables
.DELETE_ON_ERROR:
```

| Line | Why |
|---|---|
| `.DEFAULT_GOAL := help` | a bare `make` lists the targets instead of running a build |
| `SHELL`, `.SHELLFLAGS` | when recipes use bash; make's default shell has no `pipefail` |
| `--warn-undefined-variables` | a misspelt variable warns instead of expanding to nothing |
| `.DELETE_ON_ERROR:` | a target whose recipe fails is removed, so a half-written file is never taken as done |

## Targets

- Recipe lines begin with a tab, never spaces.
- The `help` target is first in the file and prints the `## ` text of every target, including those in a `.mk`
  file the Makefile includes (`$(MAKEFILE_LIST)`):

```make
help: ## List the targets
	@grep -E '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | sed 's/:.*## /  /'
```

- Each `## ` text is a short verb phrase that says what the target does, since it is the only documentation a caller sees.
- Every target that makes no file is in `.PHONY:`, for example `.PHONY: help check test clean`. Without it, a file
  named `test` in the tree makes `make test` report "up to date" and do nothing.
- One target per check (`test`, `lint`, `skills`), each running one check and failing when it fails. `check` runs them
  all, one recipe line each, in the order it should stop:

```make
check: ## Run every check, in order
	uv run python tests/run_cases.py
	uv run python tests/check_skills.py
```

- Make stops at the first failing recipe line. Prerequisites run in order only without `make -j`, so a recipe is the
  way to keep an order.
- A target that builds a file is named by the file, with its inputs as prerequisites, so make skips it when nothing
  changed:

```make
build/app: $(SRCS)
	mkdir -p "$(dir $@)"
	cc -o "$@" $(SRCS)
```

## Variables

| Form | Use |
|---|---|
| `X := value` | the default: the value is fixed where the line stands |
| `X = value` | only when the value must wait for a later line |
| `X ?= value` | a value the caller may override: `make test PYTHON=python3.12` |
| `X += value` | adds to a variable that already exists |

- Quote every path in a recipe: `rm -- "$(OUT)"`. Make puts the text in before the shell reads it, so a space in the
  path splits it into two words.

## Destructive recipes

- Never `rm -rf $(VAR)` when VAR may be empty or unset: the delete can land on the wrong tree. Use a fixed path
  (`rm -rf -- __scratch__/build`), or guard the variable on its own line before the delete:

```make
clean-build:
	@$(if $(BUILD_DIR),,$(error BUILD_DIR is empty))
	rm -rf -- "$(BUILD_DIR)"
```

- Before running a destructive target, run `make -n <target>`: it prints the commands without running them. Read them,
  then run for real. The guard line runs under `-n` too, so an empty variable stops there.
- `make -n` is no dry run for a line with `$(MAKE)`, a `+` prefix, or a `$(shell ...)` or `eval` expansion: those run anyway, so read the recipe first.


## Recursion

- Do not call `$(MAKE) -C dir` unless that folder has its own Makefile that must run. A sub-make cannot see the
  top-level graph, so a stale file inside it is not rebuilt by the top make. Prefer one Makefile with a target per folder.

## Gates

- `make -n <target>` exits 0 for each changed target and prints the commands to read; `make -n help` lists every target.
- A tab error or a missing target fails in make itself (`*** missing separator`, `No rule to make target`); that is a
  failed gate, never a pass.

## What no tool checks

Whether every destructive recipe guards every variable it uses, whether a file target lists its real inputs, whether
each `## ` text is true, and whether a quoted path is right inside `$(shell ...)` or an `eval`.
