# harness

A Claude Code plugin for spec-driven multi-agent work: safety guards everywhere, plus enforced sub-agent reports and a
learning loop in the projects that opt in. One agent's output is never trusted alone, so the rules are hooks, not prose.

## Install

Git auth comes from your machine; background updates never prompt, so a stored credential is required.

```bash
gh auth setup-git
```
```bash
claude plugin marketplace add OWNER/harness
```
```bash
claude plugin install harness@harness --scope user
```

## Updates

`plugin.json` has no `version` on purpose: each pushed commit is a new version. Auto-update can be turned on under
`/plugin`, Marketplaces; a private fork needs a stored git credential for background updates. `/reload-plugins` applies an update, and
`claude plugin update harness@harness` forces one.

Every push reaches every project, and the checks run locally
before each push. Once per clone:

```bash
git config core.hooksPath .githooks
```

Develop against the checkout, without touching the installed copy:

```bash
claude --plugin-dir .
```

## What ships

**Agents** (`agents/`): each preloads the `report` skill and ends with its form.

| Agent | Model | Job |
|---|---|---|
| `scout` | haiku | Read-only; settles one fact with path:line evidence |
| `cold-reader` | sonnet | Read-only; reads a brief with no history and lists gaps |
| `worker` | sonnet | Makes one change inside a write set, with its tests |
| `reviewer` | sonnet | Read-only; reviews a unit against its spec |
| `auditor` | sonnet | Re-runs judges, marks report claims true or false, grades the author |
| `runner` | haiku | Runs the commands its brief lists, edits nothing |

**Skills** (`skills/`):

- Process: `orchestrator`, `workflows`, `accept`, `init`, `report`.
- Quality: `spec`, `cold-read`, `review`, `audit`, `evidence`, `testing`.
- Coding: `code-python`, `code-js`, `code-html-css`, `code-terraform`, `comments`.
- Learning: `models`, `retro`; `bin/harness-import` imports past report cards from transcripts into the ledger.

**Rules are templates.** A plugin cannot ship `.claude/rules/`, so `templates/rules/` holds them (`python`, `typescript`,
`web`, `terraform`, `tests`) and `/harness:init` copies them, with `AGENTS.md` and `.harness.json`, into a project,
showing the difference before it overwrites a file.

## Hooks

| Hook (`hooks/`) | Event | When it runs |
|---|---|---|
| `context.py` | SessionStart, SubagentStart | strict: tells the main session to load `harness:orchestrator`, a role which report it owes |
| `guard.py` | PreToolUse: Bash, Write, Edit, NotebookEdit | always for the core rules; strict for the rest |
| `delegate.py` | PreToolUse: same tools, main session only | `delegate` key: refuses edits and unlisted Bash from the main session |
| `brief_lint.py` | PreToolUse: Agent, Task | `brief` key: a brief must hold its required lines |
| `turn.py` | PostToolUse, UserPromptSubmit, Stop | strict: tracks the turn; blocks a stop on job status, lessons or feedback left open |
| `report_gate.py` | SubagentStop | strict: sends a bad report back up to 3 times, checks its claims, writes the ledger |

"Strict" means the project has a `.harness.json`. The guard rules that are always on (deletes, force push,
`git reset --hard`, unquoted globs, sleep polling) are best effort, not a security boundary: they read the command
text, and a determined or unusual command can get past them. A bug in a hook lets the call run.

## What runs where

| Rule | Every project | With `.harness.json` |
|---|---|---|
| `rm` and other deletes, force push, `git reset --hard`, unquoted globs, sleep polling | yes | yes |
| Package changes, writes under `/tmp`, shell writes outside scratch, a lock around Python | no | if configured |
| Main session edits only through agents (`delegate`), briefs checked (`brief`) | no | if configured |
| Sub-agent reports in the `report` skill's form, sent back up to 3 times | no | yes |
| Job status, lessons backed by a rule change, feedback handled before a turn ends | no | yes |

`.harness.json`, every key optional (`{}` turns on the report and turn gates alone):

```json
{
  "guard": {
    "scratch": "scratch",
    "no_tmp": true,
    "deny_packages": true,
    "lock": {
      "commands": ["bin/queue"],
      "free_env": "NO_QUEUE=",
      "free_scripts": ["bin/api_index.py"],
      "message": "this project's Python runs under its queue"
    }
  },
  "delegate": {"write_allow": [], "bash_allow": []},
  "brief": {},
  "report": {"short": [], "full": [], "causes": ["queue"]},
  "stop": {"min_calls": 3, "headings": ["Verdict", "Done", "Needs you", "Next", "Lessons"], "rule_paths": ["AGENTS.md", ".claude"]}
}
```

- `report.short` and `report.full` name extra agent types that owe the short or the full report; the six roles are
  judged already.
- `delegate`: the key turns on the rule. `write_allow` holds globs (relative to the project) the main session may edit;
  `bash_allow` adds command prefixes to a default list of read and git commands.
- `brief`: the key turns on the rule. `{"required": {"worker": ["Goal:", "Write set:", "Judge:"], "*": ["Goal:"]}}` is
  the default.

## Where data lands

- `harness-feedback/inbox.md` and `harness-feedback/handled.md` in the project: sub-agent feedback and its verdicts.
  Commit them.
- `ledger.jsonl` in the plugin's data folder (`$CLAUDE_PLUGIN_DATA`, else `~/.cache/harness`): one row per sub-agent,
  with its whole report.

## Tests

Each hook case feeds a hook the JSON the harness sends. A new rule gets a case in `tests/run_cases.py` and a deliberate
bug in `tests/mutants.py` that the case catches. `tests/replay.py` runs the guard over your past Bash commands to find
false refusals.

```bash
python3 tests/run_cases.py
```
