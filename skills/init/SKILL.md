---
name: init
description: Load to set a project up for the harness plugin. Writes AGENTS.md (and .harness.json only when the project needs an override) from the plugin's templates, adapted to the project's languages, and never overwrites an existing file without showing the difference.
---

# Initialize a project

Every harness rule runs with no `.harness.json`; the file only overrides the defaults. The plugin cannot ship a project's `AGENTS.md`, so this skill writes it from `${CLAUDE_PLUGIN_ROOT}/templates/`, and writes a `.harness.json` only when the project needs an override.
The main session asks (step 2) and does the writing; the owner approves the result.

## Steps

1. **Detect.** Check which targets exist first: `.harness.json`, `AGENTS.md`, `CLAUDE.md`. Then read
   the project root: `ls`, and `rg --files -g '*.py' -g '*.ts' -g '*.js' -g '*.html' -g '*.css' -g '*.tf' | head`. Note
   the languages, the test folder and the check commands (Makefile, `package.json` scripts, CI files).
2. **Ask** only what the files do not settle: the check commands, and whether the project needs an override
   of a default (another scratch folder, a rule off, `guard.lock`, `delegate`).
3. **Pick the templates:** `AGENTS.md` always; `harness.json` only when step 2 found an override.

4. **Propose.** Write each file first to `scratch/init/<file>` (the project's scratch folder): `AGENTS.md`, and the overrides as
   `.harness.json` (only the keys that differ from the defaults). Replace every placeholder in angle brackets with a project fact;
   leave none. `TOPIC` is the one placeholder you leave unchanged: it names a folder the agents choose.
5. **Diff and install.** For each proposal, run `diff -u <target> scratch/init/<file>` (a missing target is a new
   file). An existing target is overwritten only on the owner's word: keep, replace, or merge; ask. A new file (no target) is
   installed after the owner approves the whole set. When merging into an existing `AGENTS.md`, add the missing sections and
   leave the owner's lines as they are. Targets: `AGENTS.md` and, if written, `.harness.json` at the root.
6. **Check.** If written, parse `.harness.json` (`uv run python -c 'import json; json.load(open(".harness.json"))'`).
7. **Report** the files written, the files skipped and why, and the choices left to the owner.

## `.harness.json`

The file is optional and only overrides: every section of `${CLAUDE_PLUGIN_ROOT}/templates/harness.json` is already a default. Write only the keys that differ, for example:

```json
{"guard": {"scratch": "tmp-work", "commit_style": false}, "main_edits": {"max": 0}}
```

- `skill_gate`: the defaults map `.py` to `harness:code-python`, JS and TS to `harness:code-js`, `.html` and `.css` to `harness:code-html-css`, `.tf` and `.tfvars` to `harness:code-terraform`, `.sh` to `harness:code-shell`, test files to `harness:testing`; a key here adds to them.
- `guard`: `scratch` is the throwaway folder; `no_tmp` adds a note to a write under `/tmp`; a shell write in the project outside `scratch` gets one too; `ask_packages` asks before package changes; `commit_style: false` turns the commit rule off; `lock` (off until set) forces Python through a wrapper command.
- `main_edits`: `max` (default 3, 0 is off) caps the main session's own edits per turn outside `allow` (default `harness-feedback/*`, `scratch/*`); past it, changes go to a `harness:worker`. Raise it with `"main_edits": {"max": N}`.
- `delegate` (optional, not in the starter; add it only to make agents do every edit): the main session's edits outside a `write_allow` glob (relative to the project root, matched
  with fnmatch), and its Bash commands unless every simple command starts with a default or `bash_allow` prefix, run with a note that agents do the work here. A prefix
  matches whole words: `git log` matches `git log -3`, not `git logs`. The default prefixes are `DEFAULT_BASH_ALLOW` in `hooks/delegate.py`. A push is not on the list: it needs the owner's word, or a `bash_allow` entry of the project. The main session commits only on the owner's word, whatever the list allows. An empty `write_allow` notes every edit.
- `brief`: on by default. Default `required` is `DEFAULT_REQUIRED` in `hooks/brief_lint.py` (per role, with `*`
  for the rest); it applies to every agent type.

Feedback of sub-agents lands in `harness-feedback/`; commit the folder.
