# AGENTS.md
How to work on this repo, a Claude Code plugin (`harness`) that is also its own marketplace.

## What it is
- Skills, agents, hooks and templates for spec-driven multi-agent work. `README.md` says what ships and what it blocks; install and project setup are below.
- Every push reaches every project that has it installed, so run `uv run python tests/run_cases.py` and `uv run python tests/check_leaks.py` before pushing.
- Once per clone: `make setup` (it runs `git config core.hooksPath .githooks`, the pre-push check). `make help` lists the
  targets; `make check` is what the push runs. `make clean` empties `__scratch__/`, so run it only when you own the folder.
- This repo runs under its own plugin, with the defaults. A hook or skill that gets in the way here
  gets in the way everywhere, so fix it in the plugin.

## Install, update, set up a project
- Needs Claude Code, `uv` on `PATH` (hooks run as `uv run --script`) and git access to this repo (`gh auth setup-git` for a private one).
- Install once per machine, then restart Claude Code or run `/reload-plugins`:
  `claude plugin marketplace add https://github.com/tfernd/harness.git` and `claude plugin install harness@harness --scope user`.
  The git URL matches an `extraKnownMarketplaces` entry of the same form; if the add still says the source does not match,
  the marketplace is already known: skip the add and run `claude plugin marketplace update harness`.
- Update: `claude plugin marketplace update harness` and `claude plugin update harness@harness`. Every pushed commit is a version.
- Per project, run `/harness:init` once. It writes `AGENTS.md` from `templates/`, asks only what the files do not settle, and shows a diff before touching an existing file.
- A team commits `AGENTS.md`; each member still installs the plugin.
- Cortex Code and Kiro: `curl -fsSL https://raw.githubusercontent.com/tfernd/harness/main/install.sh | sh -s -- cortex` (or `kiro`)
  installs; run it again to update; add `--uninstall` to remove it, then delete the clone it names (`~/.local/share/harness`).
- Uninstall: `claude plugin uninstall harness@harness`. Develop without touching the installed copy: `claude --plugin-dir .`.
- Hooks do nothing: `uv` is missing. Every rule runs by default; the owner file only overrides. A "harness guard
  blocked" message names the rule and the change to make.
- `bin/harness-import` imports past report cards from transcripts into the ledger (`--dry-run` writes nothing).

## Skills
- Writing a skill: `harness:skill-authoring` (form, limits, one home per fact, no project domain). `tests/check_skills.py` enforces the limits and the pointers.
- This repo is public, so nothing in it may name a person, a machine, a private project or a domain.
  `tests/check_leaks.py` enforces it (private words come from `$HARNESS_PRIVATE_WORDS` or
  `~/.config/harness/private-words`, never stored here). Run it before pushing.

## Agents
- Writing an agent: `harness:agent-authoring`.
- A new role is added in the same change to: the table in `skills/models/SKILL.md`, the roles table in
  `skills/orchestrator/SKILL.md`, `DEFAULT_BUDGET` in `hooks/budget.py`, and the page (`docs/build_map.py`, `docs/map.html.in`, then rebuild `docs/index.html`).

## Hooks
- Writing a hook: `harness:hook-authoring` (events, fail open, the time budget, soft against hard, what counts as built). Hooks here are stdlib Python 3.12.
- Each new rule gets a case in `tests/run_cases.py` and a deliberate-bug control in `tests/mutants.py` that the case catches.
- A case can pass for the wrong reason: run the mutants of the hook you changed before trusting it (`tests/mutants.py --only`).
- `tests/plant_bugs.py` and `tests/mutants.py` copy `hooks/` as they go: never edit a hook during a run, or its score means nothing.
- `CASE_THREADS` and `DEFAULT_JOBS` in `tests/mutants.py` keep an audit from freezing the machine: never raise them.
- A rule is built when it has passed cases, mutants, a replay (`hooks/replay.py`) and a live run under `claude --plugin-dir .`.
- A new guard rule is checked with `hooks/replay.py` for false refusals against real commands.
- The plugin keeps its state in `__harness__/` and throwaway files in `__scratch__/`, each ignored by git through its own `.gitignore` (`*`); a hook makes both.

## Working efficiently
- Tool turns and call habits: `skills/tool-habits/SKILL.md` is their one home; `hooks/context.py` puts its body in every session and sub-agent at start.
- Test once per unit, when it is done, not after each edit. When moving or migrating files, change first and test at the
  end. Run the smallest check that can fail, never the whole suite twice, and never a check to confirm what a tool
  already confirmed (a write that succeeded, a file just read).
- Never run `ruff format` (or any formatter) over the whole repo; format only files you changed. Run no formatter on
  `hooks/`, `tests/` or `port/`: they are hand-laid.
- A slow check runs once, in the background. A slow machine is a cost to the owner too.

## Files
- `.claude-plugin/marketplace.json` and `plugin.json` carry no `version`, on purpose: each commit is a version.
- Throwaway files go in `__scratch__/`, never `/tmp`.
- Check the plugin with `claude plugin validate .`.
