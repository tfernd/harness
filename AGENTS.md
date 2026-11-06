# AGENTS.md
How to work on this repo, a Claude Code plugin (`harness`) that is also its own marketplace.

## What it is
- Skills, agents, hooks and templates for spec-driven multi-agent work. `README.md` says what ships and what it blocks; install and project setup are below.
- Every push reaches every project that has it installed, so run `uv run python tests/run_cases.py` and `uv run python tests/check_leaks.py` before pushing.
- Once per clone: `make setup` (it runs `git config core.hooksPath .githooks`, the pre-push check). `make help` lists the
  targets; `make check` is what the push runs. `make clean` empties `scratch/`, so run it only when you own the folder.
- This repo runs under its own plugin, with the defaults and no `.harness.json`. A hook or skill that gets in the way here
  gets in the way everywhere, so fix it in the plugin.

## Install, update, set up a project
- Needs Claude Code, `uv` on `PATH` (hooks run as `uv run --script`) and git access to this repo (`gh auth setup-git` for a private one).
- Install once per machine, then restart Claude Code or run `/reload-plugins`:
  `claude plugin marketplace add tfernd/harness` and `claude plugin install harness@harness --scope user`.
- Update: `claude plugin marketplace update harness` and `claude plugin update harness@harness`. Every pushed commit is a version.
- Per project, run `/harness:init` once. It writes `AGENTS.md` from `templates/` (and a `.harness.json` only if the project needs an override),
  asks only what the files do not settle, and shows a diff before touching an existing file.
- A team commits `AGENTS.md` (and `.harness.json` if it has one); each member still installs the plugin.
- Uninstall: `claude plugin uninstall harness@harness`. Develop without touching the installed copy: `claude --plugin-dir .`.
- Hooks do nothing: `uv` is missing. Every rule runs with no `.harness.json`; it only overrides. A "harness guard
  blocked" message names the rule and the change to make.
- `bin/harness-import` imports past report cards from transcripts into the ledger (`--dry-run` writes nothing).
- `bin/compaction-report` measures what auto-compaction costs in your Claude Code logs and replays each session at other thresholds (`make compaction`; `--since`/`--until` take a window).

## Skills
- No project domain in a skill; a reference is a general starter, never one repo's taste.
- This repo is public, so nothing in it may name a person, a machine, a private project or a domain.
  `tests/check_leaks.py` enforces it (private words come from `$HARNESS_PRIVATE_WORDS` or
  `~/.config/harness/private-words`, never stored here). Run it before pushing.
- Frontmatter holds `name` and `description` only. The description is at most 300 characters and says when to load
  the skill. The body is at most 150 lines; detail goes in `references/`.
- Each fact has one home; point to another skill as `harness:<name>`. A `references/<file>` names only the skill's own folder; `tests/check_skills.py` enforces it.

## Agents
- `agents/<name>.md` with `name`, `description`, `tools`, `model`, `skills`. `hooks`, `mcpServers` and
  `permissionMode` are ignored in a plugin, so never use them.

## Hooks
- Stdlib Python 3.12 only. A bug in a hook lets the call run: never fail closed on an exception.
- Each new rule gets a case in `tests/run_cases.py` and a deliberate-bug control in `tests/mutants.py` that the case
  catches. A rule that cannot fail is not a rule.
- A case can pass for the wrong reason: run the mutants of the hook you changed before trusting it (`tests/mutants.py --only`).
- `tests/plant_bugs.py` and `tests/mutants.py` copy `hooks/` as they go: never edit a hook during a run, or its score means nothing.
- `CASE_THREADS` and `DEFAULT_JOBS` in `tests/mutants.py` keep an audit from freezing the machine: never raise them.
- Replay a new rule against what agents really met before reporting it as built: passing cases only show the code matches your assumption.
- A hook runs on every call under a 10-second timeout: no work at hook time that grows with a project's history.
- A judge that imports a hook by path (importlib) loads its siblings (`common`, `budget`) first.
- A rule is not built until it has passed cases, mutants, a replay on real data and a live run under `claude --plugin-dir .`.
- A new guard rule is checked with `hooks/replay.py` for false refusals against real commands.
- The feedback folder is `harness-feedback/`, not a dot-folder, which Claude Code refuses to write.

## Working efficiently
- Tool turns and call habits: `skills/tool-habits/SKILL.md` is their one home; `hooks/context.py` puts its body in every session and sub-agent at start.
- Test once per unit, when it is done, not after each edit. When moving or migrating files, change first and test at the
  end. Run the smallest check that can fail, never the whole suite twice, and never a check to confirm what a tool
  already confirmed (a write that succeeded, a file just read).
- A slow check runs once, in the background. A slow machine is a cost to the owner too.

## Files
- `.claude-plugin/marketplace.json` and `plugin.json` carry no `version`, on purpose: each commit is a version.
- Throwaway files go in `scratch/`, never `/tmp`.
- Check the plugin with `claude plugin validate .`.
