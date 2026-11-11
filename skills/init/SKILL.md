---
name: init
description: Load to set a project up for the harness plugin. Writes AGENTS.md from the plugin's template, adapted to the project's languages, and never overwrites an existing file without showing the difference. Writes no JSON: every rule runs by default.
---

# Initialize a project

Every harness rule runs with no setup, and the plugin reads no file inside a project. The plugin cannot ship a project's `AGENTS.md`, so this skill writes it from `${CLAUDE_PLUGIN_ROOT}/templates/AGENTS.md`.
The main session asks (step 2) and does the writing; the owner approves the result.

## Steps

1. **Detect.** Check which targets exist first: `AGENTS.md`, `CLAUDE.md`. Then read
   the project root: `ls`, and `rg --files -g '*.py' -g '*.ts' -g '*.js' -g '*.html' -g '*.css' -g '*.tf' | head`. Note
   the languages, the test folder and the check commands (Makefile, `package.json` scripts, CI files).
2. **Ask** only what the files do not settle: the check commands.
3. **Propose.** Write the file first to `__scratch__/init/AGENTS.md`. Replace every placeholder in angle brackets with a project fact;
   leave none. `TOPIC` is the one placeholder you leave unchanged: it names a folder the agents choose.
4. **Diff and install.** Run `diff -u AGENTS.md __scratch__/init/AGENTS.md` (a missing target is a new
   file). An existing target is overwritten only on the owner's word: keep, replace, or merge; ask. A new file is
   installed after the owner approves it. When merging into an existing `AGENTS.md`, add the missing sections and
   leave the owner's lines as they are.
5. **Report** the file written or skipped and why, and the choices left to the owner.

## What the plugin keeps in the project

- `__harness__/` holds the harness's state and a `README.md` that maps it.
- `__scratch__/` holds throwaway files.
- Each folder carries its own `.gitignore` holding `*`, written by a hook when the folder is made, so git sees neither and nothing needs committing or ignoring by hand. `rg` and Glob skip ignored folders, so read their files by path.

## Overrides

A default changes only in the owner's file (`~/.config/harness/config.json`, or `$HARNESS_CONFIG`), never in the project. Its optional `"projects"` key maps an absolute path or a glob to the sections that apply to a matching project root. The sections and their keys are in the README; a section not named keeps its default.
