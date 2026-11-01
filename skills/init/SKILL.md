---
name: init
description: Load to set a project up for the harness plugin. Writes .harness.json, AGENTS.md and .claude/rules/ from the plugin's templates, adapted to the project's languages, and never overwrites an existing file without showing the difference.
---

# Initialize a project

The plugin cannot ship rules or a project `AGENTS.md`, so this skill writes them from `${CLAUDE_PLUGIN_ROOT}/templates/`.
A worker does the writing (`harness:orchestrator`); the owner approves the result. A sub-agent cannot ask the owner, so
the main session asks (step 2) and puts the answers in the worker's brief.

## Steps

1. **Detect.** Check which targets exist first: `.harness.json`, `AGENTS.md`, `CLAUDE.md`, `.claude/rules/*`. Then read
   the project root: `ls`, and `rg --files -g '*.py' -g '*.ts' -g '*.js' -g '*.html' -g '*.css' -g '*.tf' | head`. Note
   the languages, the test folder and the check commands (Makefile, `package.json` scripts, CI files).
2. **Ask** (main session, before briefing) only what the files do not settle: the scratch folder name, the check
   commands, which folders the main session may write (`delegate.write_allow`). The answers go in the worker's brief.
3. **Pick the templates.**

   | Project has | Copy |
   |---|---|
   | always | `AGENTS.md`, `harness.json` |
   | tests | `rules/tests.md` |
   | Python | `rules/python.md` |
   | JavaScript or TypeScript | `rules/typescript.md` |
   | HTML or CSS | `rules/web.md` |
   | Terraform | `rules/terraform.md` |

4. **Propose.** Write each file first to `scratch/init/<file>` (the project's scratch folder): `harness.json` as
   `.harness.json`; `AGENTS.md`; each rule as its name. Replace every placeholder in angle brackets with a project fact;
   leave none. `TOPIC` is the one placeholder you leave unchanged: it names a folder the agents choose. Adjust each rule's `paths`
   globs to the project's real folders.
5. **Diff and install.** For each proposal, run `diff -u <target> scratch/init/<file>` (a missing target is a new
   file). An existing target is overwritten only on the owner's word: keep, replace, or merge; ask. A new file (no target) is
   installed after the owner approves the whole set. When merging into an existing `AGENTS.md`, add the missing sections and
   leave the owner's lines as they are. Targets: `.harness.json` and `AGENTS.md` at the root, rules under
   `.claude/rules/`.
6. **Check.** Parse `.harness.json` (`uv run python -c 'import json; json.load(open(".harness.json"))'`). Confirm each rule's
   `paths` matches at least one file (`rg --files -g '<glob>'`).
7. **Report** the files written, the files skipped and why, and the choices left to the owner.

## `.harness.json`

Every key is optional; the key's presence turns its rule on. `{}` turns on the report and turn gates alone.

```json
{"guard": {"scratch": "scratch", "no_tmp": true}, "delegate": {"write_allow": [], "bash_allow": []}, "brief": {}}
```

- `guard`: `scratch` is the throwaway folder; `no_tmp` refuses writes under `/tmp`.
- `delegate`: the main session may edit only paths matching a `write_allow` glob (relative to the project root, matched
  with fnmatch) and may run Bash only when every simple command starts with a default or `bash_allow` prefix. A prefix
  matches whole words: `git log` matches `git log -3`, not `git logs`. Default prefixes: `git status`, `git log`,
  `git diff`, `git show`, `git add`, `git commit`, `gh`, `ls`, `rg`, `head`, `wc` (the hook's
  list, `hooks/delegate.py`). A push is not on the list: it needs the owner's word, or a `bash_allow` entry of the project. The main session commits only on the owner's word, whatever the list allows. An empty `write_allow` lets the main session edit nothing.
- `brief`: turns on the brief check. Default `required` is `{"worker": ["Goal:", "Write set:", "Judge:"], "*":
  ["Goal:"]}`; it applies to the six harness roles only (scout, cold-reader, worker, reviewer, auditor, runner).

Feedback of sub-agents lands in `harness-feedback/inbox.md` and `harness-feedback/handled.md`; commit both.
