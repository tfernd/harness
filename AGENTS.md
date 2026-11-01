# AGENTS.md
How to work on this repo, a Claude Code plugin (`harness`) that is also its own marketplace.

## What it is
- Skills, agents, hooks and templates for spec-driven multi-agent work. `README.md` says what ships and how to install.
- Every push reaches every project that has it installed, so run `uv run python tests/run_cases.py` and `uv run python tests/check_leaks.py` before pushing.
- Once per clone: `git config core.hooksPath .githooks` (the pre-push check).

## Skills
- No project domain in a skill; a reference is a general starter, never one repo's taste.
- This repo is public, so nothing in it may name a person, a machine, a private project or a domain.
  `tests/check_leaks.py` enforces it (private words come from `$HARNESS_PRIVATE_WORDS` or
  `~/.config/harness/private-words`, never stored here). Run it before pushing.
- Frontmatter holds `name` and `description` only. The description is at most 300 characters and says when to load
  the skill. The body is at most 150 lines; detail goes in `references/`.
- Each fact has one home; point to another skill as `harness:<name>`.

## Agents
- `agents/<name>.md` with `name`, `description`, `tools`, `model`, `skills`. `hooks`, `mcpServers` and
  `permissionMode` are ignored in a plugin, so never use them.

## Hooks
- Stdlib Python 3.10 only. A bug in a hook lets the call run: never fail closed on an exception.
- Each new rule gets a case in `tests/run_cases.py` and a deliberate-bug control in `tests/mutants.py` that the case
  catches. A rule that cannot fail is not a rule.
- A new guard rule is checked with `hooks/replay.py` for false refusals against real commands.
- The feedback folder is `harness-feedback/`, not a dot-folder, which Claude Code refuses to write.

## Working efficiently
- Read in bulk: one Python call reads every file, line range and match you need and prints them together. Never one
  Read per file in a row, and one `rg` or script over all paths, not one search per path.
- Edit in bulk: one Python script makes every edit of a unit, an assert on each exact string, not one Edit per change.
- Test once per unit, when it is done, not after each edit. When moving or migrating files, change first and test at the
  end. Run the smallest check that can fail, never the whole suite twice, and never a check to confirm what a tool
  already confirmed (a write that succeeded, a file just read).
- A check that takes over a minute runs once, in the background. A slow machine is a cost to the owner too.

## Files
- `.claude-plugin/marketplace.json` and `plugin.json` carry no `version`, on purpose: each commit is a version.
- Throwaway files go in `scratch/`, never `/tmp`.
- Check the plugin with `claude plugin validate .`.
