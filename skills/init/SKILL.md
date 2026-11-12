---
name: init
description: Load to set a project up for the harness plugin. Writes AGENTS.md from the plugin's template, adapted to the project's languages, and never overwrites an existing file without showing the difference. Writes no JSON: every rule runs by default.
---

# Initialize a project

Every harness rule runs with no setup, and the plugin reads no file inside a project. The plugin cannot ship a project's `AGENTS.md`, so this skill writes it from `${CLAUDE_PLUGIN_ROOT}/templates/AGENTS.md`.
The main session asks (step 2) and writes the proposal; the owner approves it; a `harness:worker` installs it.

## Steps

1. **Detect.** Check which targets exist first: `AGENTS.md`, `CLAUDE.md`. Then read
   the project root: `ls`, and `rg --files -g '*.py' -g '*.ts' -g '*.js' -g '*.html' -g '*.css' -g '*.tf' | head`. Note
   the languages, the test folder and the check commands (Makefile, `package.json` scripts, CI files).
2. **Ask** only what the files do not settle: the check commands.
3. **Propose.** Write the file first to `/tmp/harness/<project>/init/AGENTS.md`. Replace every placeholder in angle brackets with a project fact;
   leave none. `TOPIC` is the one placeholder you leave unchanged: it names a folder the agents choose.
4. **Diff and install.** Run `diff -u AGENTS.md /tmp/harness/<project>/init/AGENTS.md` (a missing target is a new
   file). An existing target is overwritten only on the owner's word: keep, replace, or merge; ask. On the owner's yes,
   brief a `harness:worker` to install the proposal. When merging into an existing `AGENTS.md`, it adds the missing
   sections and leaves the owner's lines as they are.
5. **Report** the file written or skipped and why, and the choices left to the owner.

## What the plugin keeps outside the project

- `~/.local/state/harness/<project>/` holds the harness's state and a `README.md` that maps it.
- `/tmp/harness/<project>/` holds throwaway files.
- Both sit outside the project, so git sees neither. Read their files by path.

## Overrides

A default changes only in the owner's file (`~/.config/harness/config.json`, or `$HARNESS_CONFIG`), never in the project. Its optional `"projects"` key maps an absolute path or a glob to the sections that apply to a matching project root. The sections and their keys are in the README; a section not named keeps its default.
