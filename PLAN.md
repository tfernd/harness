# Plan

The harness is meant for everyone and every job: it runs under Claude Code, Cortex Code and Kiro, keeps its rules
on by default, and improves itself from the reports its agents file. This file holds what is left after the current
version; each item says what done looks like.

## Merge

- **Plugin state out of the project.** Branch `worktree-agent-a7ae9e5cb1f277172` moves `__harness__/` and
  `__scratch__/` to `${XDG_STATE_HOME:-~/.local/state}/harness/projects/<slug>/` (`feedback/`, `trash/`, `scratch/`),
  with a one-time migration at session start. It was cut from an older base and conflicts in 7 files
  (`README.md`, `hooks/common.py`, `hooks/delegate.py`, `hooks/guard.py`, `hooks/turn.py`, `tests/mutants.py`,
  `tests/run_cases.py`). Done: rebased onto main, cases and the touched mutants pass, and no hook run creates a
  folder inside a project.
  - Also move `Makefile` `clean`, `tests/check_port.py` `WORK` and the mutant work folder out of the repo.
  - A user-set `XDG_STATE_HOME` inside a project puts the trash inside it: refuse that.
  - `hooks/skill_gate.py` keeps a scratch exemption that is dead once scratch is outside the project: remove it and
    its mutant.

## Take action

- **No comments or docstrings.** `bin/strip-comments` and `.githooks/pre-commit` exist; the hook is committed
  switched off. Replace the six `__doc__` reads used for argparse (`port/harness_port.py`, `docs/build_map.py`,
  `hooks/replay.py`, `tests/mutants.py`, `tests/check_skills.py`, `tests/run_cases.py`) with plain strings, run
  `make strip`, make the hook executable, and change the comments, testing and code-python skills to "no comments".
- **Thin the tests.** Remove near-duplicate cases in `tests/run_cases.py` and rows in `tests/mutants.py`; never a
  rule's only case, and the mutant score stays at 0 survivors.
- **Retro.** The ledger holds over 100 reports since the last retro: run `harness:retro` and apply what it proposes.

## Test

- Live run under `claude --plugin-dir .` of the guard's new rules (`git branch -C`, local `npx`) and the gates.
- The real install: `curl -fsSL https://raw.githubusercontent.com/tfernd/harness/main/install.sh | sh -s -- cortex`
  and `kiro`, then `--uninstall`.
- Replay (`hooks/replay.py`) before and after a guard change, so a new refusal is counted against a baseline.
- The commit gate has no replay: build one from past `git commit` calls with their repository state.

## See

- Scoped tools (`npx @scope/tool`) always ask: read the package's `bin` entry in `node_modules` to allow them.
- `is_skipped` in the commit gate reads only function decorators: class-level skips, `skipIf` and `pytest.skip()`
  in a body still count as kept tests.
- Prune old copies of the plugin in the Claude Code plugin cache after an update.

## Block and guardrail

- The guard treats a worktree's own `__scratch__/` as outside scratch, so agents in worktrees cannot clean up.
- Agents with `isolation: "worktree"` start from the last pushed commit, not local HEAD: push before launching
  them, or have them hand back a patch against a named commit.
- An agent edited a test file while its mutant run read it: the mutant runner should refuse to start, or warn,
  when the tree changes under it.

## Generalize

- Every rule on by default for every project; overrides only in `~/.config/harness/config.json`. No project file.
- One home per fact across skills, hooks and the page; the page (`docs/index.html`) is rebuilt by
  `docs/build_map.py` and checked in CI.
- Ports: anything added for Claude Code gets its Cortex and Kiro form in `port/` in the same change.
