# Plan

The harness is meant for everyone and every job: it runs under Claude Code, Cortex Code and Kiro, keeps its rules
on by default, and improves itself from the reports its agents file. This file says what we build next, why, and in
what order. Each step lands as its own commits, with `make check` green, before the next starts.

## Build, in order

### 1. Full text in the page popups

- **What:** a button in each popup of `docs/index.html` switches from the summary to the whole skill, agent or hook,
  rendered (headings, lists, tables, code).
- **Why:** the owner wants to read a part without leaving the page.
- **Done:** built from the files by `docs/build_map.py`; works from `file://`, light and dark, at 320px.

### 2. No comments, everywhere

- **What:** `harness:comments` becomes the no-comments skill, loaded before every code edit in every project:
  - no comments and no docstrings; names, types and small functions carry the meaning;
  - never a comment about a change (`# removed X`, `# was Y`, `# now uses Z`): the diff and the commit say that;
  - kept only where a machine reads it: a shebang, an encoding line, a PEP 723 block, a license header the project
    requires, a directive a tool needs to run.
  - `harness:code-python`, `harness:testing` and the other skills drop their docstring rules to match.
  - This repo: replace the six `__doc__` reads used for argparse (`port/harness_port.py`, `docs/build_map.py`,
    `hooks/replay.py`, `tests/mutants.py`, `tests/check_skills.py`, `tests/run_cases.py`), run `make strip`, make
    `.githooks/pre-commit` executable. The page's hook summaries move to a `SUMMARY` constant per hook first, since
    the strip removes docstrings.
- **Why:** comments were written for human readers; an agent reads the code itself. A comment goes stale, costs
  tokens on every read, and a comment about a removal is noise forever. Needing one is a sign the code should be
  clearer.
- **Done:** the skill says it; `bin/strip-comments --check` passes on this repo; the pre-commit hook is on.

### 3. Guard: AWS read-only, and no piped installers

- **What:**
  - `aws`: read-only by default. `describe-*`, `list-*`, `get-*`, `s3 ls`, `sts get-caller-identity`, `logs tail` and
    the like run; every other `aws` command (create, put, update, delete, invoke, `s3 cp`/`mv`/`rm`/`sync` to a
    bucket, `deploy`) asks the owner. The same for `sam` and `cdk` deploys and deletes.
  - `curl ... | sh`, `wget ... | bash` and the like ask the owner.
- **Why:** a write to an AWS account cannot be undone from the session; a piped installer runs unseen code.
- **Done:** cases and planted bugs for each, a replay over past transcripts with the count of new asks.

### 4. Skills for the work stack

Each skill comes with a `skill_gate` kind in `hooks/common.py`, so it arrives before the first edit of that kind of file.

| Skill | Covers | Kind |
|---|---|---|
| `aws-cli` | read first and say what a write will do; profiles and regions named on every call; Lambda, API Gateway, IAM least privilege, SAM or CDK; calls through an AI gateway: timeouts, retries with backoff, no key in code | none (a command skill) |
| `snowflake-cli` | `snow` connections, roles and warehouses named on every call; `snow sql` read first; stages, deploys of procedures and apps | none (a command skill) |
| `code-sql` | Snowflake SQL: idempotent DDL (`CREATE OR ALTER`, never `CREATE OR REPLACE` on a table with data), dynamic tables (target lag, refresh mode), procedures, Snowpark ML, scan cost | `*.sql` |
| `code-yaml` | anchors, quoting, indentation traps; Harness.io pipelines and templates; GitHub Actions; `.pre-commit-config.yaml` with pinned revs | `*.yaml`, `*.yml` |
| `code-make` | `.PHONY`, tabs, `make help`, one target per check, no unguarded `rm -rf $(VAR)` | `Makefile`, `*.mk` |

- **Why:** the owner's work runs on Snowflake, AWS, Harness.io pipelines and Makefiles; none has a skill today.
- **Done:** `tests/check_skills.py` passes; the page lists them; each skill_gate kind has a case.

### 5. Plugin state out of the project

- **What:** move `__harness__/` and `__scratch__/` to `${XDG_STATE_HOME:-~/.local/state}/harness/projects/<slug>/`
  (`feedback/`, `trash/`, `scratch/`), with a one-time migration at session start.
- **Why:** the owner wants no plugin folders inside a project.
- **Start from:** ``state-move.patch` in this project's state folder under `~/.local/state/harness/projects/``, cut from the old
  history; it conflicts in `README.md`, `hooks/common.py`, `hooks/delegate.py`, `hooks/guard.py`, `hooks/turn.py`,
  `tests/mutants.py` and `tests/run_cases.py`. Also move the `Makefile` `clean` target, `tests/check_port.py`
  `WORK` and the mutant work folder out; refuse an `XDG_STATE_HOME` inside a project; drop the dead scratch clause
  in `hooks/skill_gate.py`.
- **Done:** no hook run creates a folder inside a project (a case shows it).

## Later

- **Guard for data and infrastructure:** ask before `terraform apply`/`destroy`, SQL `DROP`, `TRUNCATE`, `DELETE`
  without `WHERE`, `CREATE OR REPLACE TABLE`, `docker system prune`, `kubectl delete`, `helm uninstall`, and any
  command naming a production profile or connection.
- **Secrets:** refuse a write whose text holds a private key or an AWS access key, and `git add` of a `.env` file.
- **`multi-repo` skill:** a change across several repositories: the order they land in, one branch and PR per repo,
  each repo's own checks.
- **Review lenses:** the reviewer reads with a lens, a checklist for one kind of risk. A data lens checks SQL for
  cost and correctness (a full scan, `SELECT *` in a dynamic table, a missing filter); a cloud lens checks IAM
  wildcards, public buckets and missing timeouts.
- **Frontmatter for the page:** a `kind:` field in skill and agent frontmatter instead of the lists in
  `docs/build_map.py` (check live that Claude Code ignores the key).
- **Thin the tests:** remove near-duplicate cases and planted bugs; never a rule's only case; 0 survivors kept.
- **Retro:** over 100 reports wait; run `harness:retro`.
- **Small fixes:** scoped tools (`npx @scope/tool`) always ask; `is_skipped` in the commit gate misses class-level
  skips and `pytest.skip()`; a worktree's own `__scratch__/` counts as outside scratch; worktree agents start from
  the last pushed commit, so push first; the mutant runner should warn when the tree changes under it.

## Test by hand

- A live run under `claude --plugin-dir .` of each new guard rule.
- The real install: `curl -fsSL https://raw.githubusercontent.com/tfernd/harness/main/install.sh | sh -s -- cortex`
  and `kiro`, then `--uninstall`.
