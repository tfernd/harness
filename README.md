# harness

A Claude Code plugin for spec-driven work with several agents. The main session does not edit code. It writes briefs,
hands them to sub-agents, and judges what comes back. No single agent is trusted: every unit is specified, reviewed,
implemented, audited, fixed, integrated and tested by different agents, and the rules that keep this honest are hooks,
not advice.

This repo is both the plugin and its own marketplace. Rules for people who work on the repo are in
[AGENTS.md](AGENTS.md).

## The idea

The main session ("the orchestrator") loads the `orchestrator` skill and works in this order:

1. **Spec** a large job in a file with goals, settled decisions, write sets and judges (`spec`, `cold-read`).
2. **Review** the spec or brief with a reader that has no history.
3. **Implement** with a `worker` that may edit only the files in its write set.
4. **Audit** the worker's report with an `auditor` that re-runs the judges and marks each claim true or false.
5. **Fix** failures by the steps in the `review` skill, then **integrate** the units and **test** the whole.

Example: to add a retry flag to a command-line tool, the main session briefs one worker with `Goal:`, `Write set:` and
`Judge:` lines. The worker edits two files and runs the test. A reviewer reads the diff. An auditor re-runs the test and
checks the worker did not touch a third file. Only then does the main session accept the unit.

## Install and update

The hooks run as `uv run --script`, so `uv` must be on `PATH`.

Git auth comes from your machine. Background updates never prompt, so a stored credential is required.

```bash
gh auth setup-git
claude plugin marketplace add OWNER/harness
claude plugin install harness@harness --scope user
```

- `plugin.json` has no `version` on purpose: each pushed commit is a new version.
- Update by hand with `claude plugin update harness@harness`, then `/reload-plugins`.
- Auto-update is switched on under `/plugin`, Marketplaces. For a private repo it works only with a stored git
  credential, because the background check cannot ask for a password.
- Develop against a checkout without touching the installed copy: `claude --plugin-dir .`.

### A new project

Run `/harness:init` (the `init` skill). It looks at the project's languages, asks only what the files do not settle,
writes proposals to the project's scratch folder, shows a diff against any existing file, and installs only on your
word. It writes `.harness.json`, `AGENTS.md` and the matching files under `.claude/rules/`.

## Repo map

| Path | Holds | Read by |
|---|---|---|
| `.claude-plugin/` | `plugin.json` and `marketplace.json`, without a version | Claude Code, at install |
| `skills/` | one folder per skill, a `SKILL.md` and optional `references/` | the plugin, at runtime |
| `agents/` | the six role definitions | the plugin, at runtime |
| `hooks/` | `hooks.json` and the hook scripts, plus helpers `common.py` and `shell.py`, `replay.py` and `import_reports.py` | the plugin, at runtime |
| `templates/` | files that `/harness:init` copies into a project | the project, after init |
| `bin/` | command-line tools | maintainers and project owners |
| `tests/` | hook cases, mutants and the leak check | this repo's maintainers |
| `.githooks/` | the pre-push hook | this repo's maintainers |
| `.github/` | CI workflow definitions | this repo's maintainers |
| `AGENTS.md` | how to work on this repo | this repo's maintainers |
| `scratch/` | throwaway files, git-ignored (see below) | this repo's maintainers |

## Skills

A skill is a short guide an agent loads when its description says so. Each fact lives in one skill; others point to it
as `harness:<name>`.

| Group | Skills |
|---|---|
| Process | `orchestrator`, `workflows`, `accept`, `init`, `report` |
| Quality | `spec`, `cold-read`, `review`, `audit`, `evidence`, `testing` |
| Coding languages | `code-python`, `code-js`, `code-html-css`, `code-terraform` |
| Writing | `comments` |
| Learning | `models`, `retro` |

`orchestrator` is for the main session only; sub-agents never load it. `report` is preloaded by every role.

## Agents

Each agent file sets `tools`, `model` and the skills it preloads.

| Agent | Model | Edits files | Job |
|---|---|---|---|
| `scout` | haiku | no | Settles one fact with `path:line` evidence |
| `cold-reader` | sonnet | no | Reads a brief with no history and lists gaps |
| `worker` | sonnet | yes | Makes one change inside a write set, with its tests |
| `reviewer` | sonnet | no | Reviews a unit against its spec |
| `auditor` | sonnet | no | Re-runs judges, marks report claims true or false, grades the author |
| `runner` | haiku | no | Runs the commands its brief lists and reports |

"No" means no Edit or Write tool. These roles still have Bash, so they can run commands; the guard hooks apply to them.
A brief may step a role up to a stronger model (`models` skill).

## Hooks

`hooks/hooks.json` wires them. "Strict" means the project has a `.harness.json`; without one, only the always-on part of
`guard.py` runs.

| Hook | Event | What it does |
|---|---|---|
| `context.py` | SessionStart, SubagentStart | Strict. Tells the main session to load `harness:orchestrator`, and tells a role which report form it owes |
| `budget.py` | PreToolUse, every tool | Strict. Refuses every tool call of a sub-agent that is past its time budget, so it must send a partial report |
| `guard.py` | PreToolUse: Bash, Write, Edit, NotebookEdit | Always: blocks `rm` and other deletes, force push, `git reset --hard`, unquoted globs, sleep polling. Strict and configured: blocks package changes, writes under `/tmp`, shell writes outside scratch, Python run outside a lock |
| `delegate.py` | PreToolUse: same tools | The `delegate` key. Refuses edits and unlisted Bash from the main session |
| `brief_lint.py` | PreToolUse: Agent, Task | The `brief` key. A brief for a role must hold its required lines, such as `Goal:` |
| `turn.py` | PostToolUse, UserPromptSubmit, Stop | Strict. Tracks the turn; blocks a stop while the job status, lessons or feedback are left open |
| `report_gate.py` | SubagentStop | Strict. Sends a bad report back up to 3 times, checks its claims against the transcript, writes the ledger |

The always-on guard rules are best effort, not a security boundary: they read the command text. A bug in a hook lets the
call run; a hook never fails closed on an exception.

## Templates and rules

A plugin cannot ship `.claude/rules/`, so the rules are templates. `/harness:init` copies them into the project:

| Template | Goes to | When |
|---|---|---|
| `templates/harness.json` | `.harness.json` | always |
| `templates/AGENTS.md` | `AGENTS.md` | always; placeholders in angle brackets are filled in |
| `templates/rules/tests.md` | `.claude/rules/tests.md` | the project has tests |
| `templates/rules/python.md` | `.claude/rules/python.md` | Python |
| `templates/rules/typescript.md` | `.claude/rules/typescript.md` | JavaScript or TypeScript |
| `templates/rules/web.md` | `.claude/rules/web.md` | HTML or CSS |
| `templates/rules/terraform.md` | `.claude/rules/terraform.md` | Terraform |

A rule file has `paths` globs and a line such as "before writing a `.py` file, load `harness:code-python`". Claude Code
loads it when a matching file is touched.

### `.harness.json` keys

Every key is optional; `{}` turns on the report and turn gates alone.

| Key | Effect |
|---|---|
| `guard.scratch`, `guard.no_tmp` | Name the scratch folder; refuse writes under `/tmp` |
| `guard.deny_packages` | Refuse install, remove and resolve commands for packages |
| `guard.lock` | Python must run through the listed wrapper commands, with free scripts and prefixes exempt |
| `delegate` | Turns on the main-session rule; `write_allow` globs it may edit, `bash_allow` extra command prefixes |
| `brief` | Turns on brief checks; `required` maps a role (or `*`) to the line labels it needs |
| `report` | `short` and `full` add agent types that owe a report; `causes` adds problem causes |
| `budget` | Maps a role to minutes of working time |
| `stop` | `min_calls`, the status `headings` a long turn must end with, and `rule_paths` that back a lesson |

## bin/

| Tool | Does |
|---|---|
| `bin/harness-import` | Imports past report cards from Claude Code transcripts into the ledger. Safe to rerun; `--dry-run` writes nothing |

## Files in your project

- `.harness.json`: the configuration above. Commit it.
- `harness-feedback/inbox.md` and `handled.md`: feedback that agents file at the end of a report, and the main session's
  verdict on each. The folder is not a dot-folder because Claude Code refuses to write those. Commit both files.
- **The ledger**, `ledger.jsonl`: one row per sub-agent with its whole report, scores and causes. It lives in the plugin's
  data folder (`$CLAUDE_PLUGIN_DATA`, else `~/.cache/harness`), not in the project.
- **Budgets:** a brief may hold a line `Budget: 15` (minutes). Past it, `budget.py` refuses the agent's tool calls and
  the agent reports what it has. Without the line, the `budget` key gives a default per role.
- **`scratch/`:** the project's throwaway folder for probes, proposals and one-off output. It is git-ignored and agents
  use it instead of `/tmp`; the guard refuses `/tmp` when `guard.no_tmp` is set. This repo has its own git-ignored
  `scratch/` for the same purpose, and it is unrelated to any project's.

## The learning loop

1. Every sub-agent ends with a report that has a REPORT CARD: Task, Brief and Ease scores and a list of problems with
   their causes.
2. `report_gate.py` checks the form and writes one ledger row.
3. An auditor's grade can be compared with the author's own score.
4. The `retro` skill groups the ledger by cause, role and brief, and proposes a rule change when a problem appears twice.
5. The change goes to a hook, gate, skill or brief template. A lesson that does not end in a rule change does not close
   the turn.

Example: three workers lose time because a brief names a stale line number. The retro proposes a line in the brief
template, and the lesson is closed by that edit.

## Testing this repo

Run both before pushing; every pushed commit reaches every project through auto-update.

```bash
uv run python tests/run_cases.py
uv run python tests/check_leaks.py
```

- `tests/run_cases.py`: each case feeds a hook the JSON Claude Code sends and checks the answer.
- `tests/mutants.py`: a deliberate bug per rule, which a case must catch. A rule that cannot fail is not a rule.
- `hooks/replay.py` (run it with `uv run --script`): runs the always-on guard rules over your past Bash commands to find false refusals.
- `tests/check_leaks.py`: fails when a file names a person, an email, a home path or a private word. The private word list
  is read from `$HARNESS_PRIVATE_WORDS` or `~/.config/harness/private-words` and never stored here.

Once per clone, enable the pre-push hook, which runs both commands above and stops the push if either fails:

```bash
git config core.hooksPath .githooks
```
