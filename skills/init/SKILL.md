---
name: init
description: Load to set a project up for the harness plugin. Writes .harness.json and AGENTS.md from the plugin's templates, adapted to the project's languages, and never overwrites an existing file without showing the difference.
---

# Initialize a project

The plugin cannot ship a project's `.harness.json` or `AGENTS.md`, so this skill writes them from `${CLAUDE_PLUGIN_ROOT}/templates/`.
The main session asks (step 2) and does the writing; the owner approves the result.

## Steps

1. **Detect.** Check which targets exist first: `.harness.json`, `AGENTS.md`, `CLAUDE.md`. Then read
   the project root: `ls`, and `rg --files -g '*.py' -g '*.ts' -g '*.js' -g '*.html' -g '*.css' -g '*.tf' | head`. Note
   the languages, the test folder and the check commands (Makefile, `package.json` scripts, CI files).
2. **Ask** only what the files do not settle: the scratch folder name, the check
   commands.
3. **Pick the templates:** `AGENTS.md` and `harness.json`, always.

4. **Propose.** Write each file first to `scratch/init/<file>` (the project's scratch folder): `harness.json` as
   `.harness.json`; `AGENTS.md`. Replace every placeholder in angle brackets with a project fact;
   leave none. `TOPIC` is the one placeholder you leave unchanged: it names a folder the agents choose.
5. **Diff and install.** For each proposal, run `diff -u <target> scratch/init/<file>` (a missing target is a new
   file). An existing target is overwritten only on the owner's word: keep, replace, or merge; ask. A new file (no target) is
   installed after the owner approves the whole set. When merging into an existing `AGENTS.md`, add the missing sections and
   leave the owner's lines as they are. Targets: `.harness.json` and `AGENTS.md` at the root.
6. **Check.** Parse `.harness.json` (`uv run python -c 'import json; json.load(open(".harness.json"))'`).
7. **Report** the files written, the files skipped and why, and the choices left to the owner.

## `.harness.json`

Every key is optional; the key's presence turns its rule on. `{}` turns on the report and turn gates alone.

```json
{"guard": {"scratch": "scratch", "no_tmp": true}, "brief": {}}
```

- `skill_gate`: init writes the template's defaults (`.py` to `harness:code-python`, JS and TS to `harness:code-js`, `.html` and `.css` to `harness:code-html-css`, `.tf` and `.tfvars` to `harness:code-terraform`, `.sh` to `harness:code-shell`, test files to `harness:testing`); drop the entries of languages the project lacks.
- `guard`: `scratch` is the throwaway folder; `no_tmp` refuses writes under `/tmp`.
- `delegate` (optional, not in the starter; add it only to make agents do every edit): the main session may edit only paths matching a `write_allow` glob (relative to the project root, matched
  with fnmatch) and may run Bash only when every simple command starts with a default or `bash_allow` prefix. A prefix
  matches whole words: `git log` matches `git log -3`, not `git logs`. The default prefixes are `DEFAULT_BASH_ALLOW` in `hooks/delegate.py`. A push is not on the list: it needs the owner's word, or a `bash_allow` entry of the project. The main session commits only on the owner's word, whatever the list allows. An empty `write_allow` lets the main session edit nothing.
- `brief`: turns on the brief check. Default `required` is `{"worker": ["Goal:", "Write set:", "Judge:"], "*":
  ["Goal:"]}`; it applies to every agent type.

Feedback of sub-agents lands in `harness-feedback/`; commit the folder.
