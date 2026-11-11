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
- Install or update once per machine, then restart Claude Code or run `/reload-plugins`:
  `claude plugin marketplace add tfernd/harness; claude plugin marketplace update harness && claude plugin install harness@harness --scope user && claude plugin update harness@harness`.
  The add may say the marketplace already exists and the install may say the plugin is already installed; the update then pulls the latest, so the same line works for a new or an installed plugin. Every pushed commit is a version.
- Per project, run `/harness:init` once. It writes `AGENTS.md` from `templates/`, asks only what the files do not settle, and shows a diff before touching an existing file.
- A team commits `AGENTS.md`; each member still installs the plugin.
- Cortex Code: `cortex plugin update harness || cortex plugin install tfernd/harness` updates it, or installs it when absent.
- Kiro: `curl -fsSL https://raw.githubusercontent.com/tfernd/harness/main/install.sh | sh -s -- kiro`
  installs; run it again to update; add `--uninstall` to remove it, then delete the clone it names (`~/.local/share/harness`).
- Uninstall: `claude plugin uninstall harness@harness`. Develop without touching the installed copy: `claude --plugin-dir .`.
- Hooks do nothing: `uv` is missing. Every rule runs by default; the owner file only overrides. A "harness guard
  blocked" message names the rule and the change to make.
- `bin/harness-import` imports past report cards from transcripts into the ledger (`--dry-run` writes nothing).

## Skills
- Writing a skill: `harness:authoring` (`references/skill.md`: form, limits, one home per fact, no project domain). `tests/check_skills.py` enforces the limits and the pointers.
- This repo is public, so nothing in it may name a person, a machine, a private project or a domain.
  `tests/check_leaks.py` enforces it (private words come from `$HARNESS_PRIVATE_WORDS` or
  `~/.config/harness/private-words`, never stored here). Run it before pushing.

## Agents
- Writing an agent: `harness:authoring` (`references/agent.md`).
- A new role is added in the same change to: the roles table and the models table in
  `skills/orchestrator/SKILL.md`, `DEFAULT_BUDGET` in `hooks/budget.py`, and the page (`docs/build_map.py`, `docs/map.html.in`, then rebuild `docs/index.html`).

## Hooks
- Writing a hook: `harness:authoring` (`references/hook.md`: events, fail open, the time budget, soft against hard, what counts as built). Hooks here are stdlib Python 3.12.
- Each new rule gets a case in `tests/run_cases.py`; a new check is shown to fail once on a deliberate bug (`harness:testing`).
- A rule is built when it has passed cases, a replay (`hooks/replay.py`) and a live run under `claude --plugin-dir .`.
- A new guard rule is checked with `hooks/replay.py` for false refusals against real commands.
- The plugin keeps its state in `__harness__/` and throwaway files in `__scratch__/`, each ignored by git through its own `.gitignore` (`*`); a hook makes both.

## Ports and sync
- The Claude plugin (`skills/`, `agents/`, `hooks/`) is the only source. `bin/harness-port` (runs `port/harness_port.py`) converts it into `~/.kiro` or `~/.snowflake/cortex`; rerun it after `git pull`, since hook commands point at the checkout.
- Ported hook commands run `port/shim.py`, which maps the other tool's payloads to the Claude hooks' and back. `install.sh` clones the repo into `~/.local/share/harness` and runs the port from there.
- A change to a skill, agent or hook touches no port file; edit `port/` only to change the conversion itself. `README.md` ("Other tools") lists what each port loses; `docs/build_map.py` fails when one of its port-note phrases is missing from `README.md` or on more than one line.

## Build and release
- Release order: `make check` (map freshness, hook cases, skill form, leaks), then commit, then push, then update. `.githooks/pre-push` runs `make check` on every push; `make help` lists the targets.
- `docs/index.html` embeds the source of every hook and the text of every agent and skill: a change to any of them makes it stale (the pre-push check then fails). It also needs the port-loss phrases in `README.md`. Run `make map` (`docs/build_map.py`) and commit the page with the change.
- Commit from the main session only (`harness:git`); a sub-agent never writes to git.
- Update the installed copy with `claude plugin marketplace update harness && claude plugin update harness@harness`, then restart Claude Code or run `/reload-plugins`: a running session keeps the hooks it loaded at start. Cortex Code and Kiro update with the lines under Install.
- `.github/workflows/check.yml` is the only workflow: on a push or pull request to `main` it runs the checks above. GitHub Pages serves `docs/` from `main` (a repo setting, not a workflow), so a push publishes the page.

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
