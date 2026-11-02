# harness

A Claude Code plugin that makes an AI coding session safer and cheaper to trust. It adds three things: **hooks** that
refuse risky or wasteful actions, **skills** that give the model short rule sheets, and **agents** that do narrow jobs
(find a fact, review a diff, run a check) and must report in a fixed, checked form.

Install, update and project setup are written for agents in [AGENTS.md](AGENTS.md). This page says what the plugin does,
how the parts fit, what it stops and what it does not.

## What it is for

- **Stop damage.** No `rm`, no force push, no `git reset --hard`, in any project.
- **Stop wasted turns** (in a project with `.harness.json`). Every agent starts knowing how to make cheap tool calls. Under zsh, globs that match nothing are refused in any project, as is `sleep`
  polling, and an agent that reads one small thing at a time is nudged.
- **Make agent work checkable.** A sub-agent cannot end with "done": its report has fixed sections, and its claims (files
  changed, exit codes, `path:line` evidence) are checked against what it really did.
- **Turn problems into rules.** What agents report piles up in an inbox, and a due retro turns it into changes.
- **Keep the cost down.** The main session works directly, scripts repetitive work, and uses agents only where parallel
  work pays.

## How you use it

Install it once (see [AGENTS.md](AGENTS.md)) and run `/harness:init` in a project. Then work as usual: you ask, and the
main session follows the `orchestrator` skill. `/harness:init` writes `.harness.json` and an `AGENTS.md`. You see a refusal
only when a hook stops something (the agent is told what to change, so usually you do nothing), a question when a package
change needs your yes, and a closing status after a big job. In this repo, `make help` lists the checks.

## How the pieces work together

```
you ── ask ──> main session (follows the orchestrator skill)
                 │  works itself; scripts the repetitive part
                 │  briefs agents only for parallel or large units
                 ▼
        agents: scout · runner · cold-reader · worker · reviewer · auditor · analyst · planner · researcher
                 │  each ends with a REPORT

 at every start     context: orchestrator pointer, tool-habits, report form, open problems
 before each call   guard · delegate · skill_gate · brief_lint · budget
 after a read       nudge
 when an agent ends report_gate: checks the report, files problems in the inbox and the ledger
 when a turn ends   turn: status, lessons, and a retro when 20 items wait
                 ▼
 inbox ──> analyst ──> a new rule in a hook, skill or brief template, or a line in open.md
```

Skills are text the model reads. Hooks run outside the model, so it cannot talk its way past them. Reports are where the
two meet: a skill says what to write, a hook checks it.

## Two modes

| Mode | When | What runs |
|---|---|---|
| **Safety only** | The project has no `.harness.json` | The always-on guard, nothing else |
| **Strict** | The project has a `.harness.json` | The guard, plus start-up context, turn tracking, report and budget checks, and each rule you switch on |

## The hooks and what they stop

| Hook | When | What it does |
|---|---|---|
| `context.py` | Session or agent starts | Adds text agents would otherwise forget: load the orchestrator, the whole `tool-habits` skill, the report form owed, past lessons, open problems. Refuses nothing |
| `guard.py`, always | Before a command or edit | Refuses deletes (`rm`, `rmdir`, `unlink`, `shred`, `find -delete`, `git clean`), pushes that rewrite remote history, `git reset --hard`, globs that match nothing or that the shell would expand too early, and `sleep` inside a `while` or `until` loop |
| `guard.py`, configured | Before a command or edit | Asks you before package changes. Refuses writes under `/tmp`, shell writes outside the scratch folder, and Python run outside its lock wrapper |
| `commit_gate.py` | Before a command | Refuses a commit whose message `-m`, `-F` or a heredoc shows is not `type(scope): title` with `* ` bullets, and a commit or pull request whose text shows AI attribution. It cannot read a commit that opens an editor, or a message in a variable set by an earlier call |
| `delegate.py` | Before a command or edit | With the `delegate` key, refuses edits and unlisted commands from the main session, so agents do the work |
| `skill_gate.py` | Before an Edit or Write | With the `skill_gate` key, refuses an edit until the skill for that kind of file is loaded |
| `brief_lint.py` | Before an agent starts | With the `brief` key, refuses a brief with no `Goal:`, a worker brief with no `Write set:` and `Judge:`, and a budget in anything but turns |
| `budget.py` | Before every call | Refuses every call but the handback from an agent past its turns, so it sends a partial report. Any agent type has a default |
| `nudge.py` | After a read | Adds one line of advice after a repeated read or three small reads in a row, at most twice per agent. Refuses nothing |
| `report_gate.py` | An agent stops | Any agent type must end with a report: Answer, Not proven and a Verdict of done, partial or blocked, plus Problems, Next time, Open and Feedback when they have something to say. Sends back a malformed one, or one its transcript does not back, up to 3 times. Files problems and writes the ledger |
| `turn.py` | Your turn ends | Holds the turn for a missing status after a long turn, a lesson with no rule changed, a bare "no lessons" after a refused call, or a due retro |

A refusal says which rule fired and what to change.

Four more files in `hooks/` are not hooks. `common.py` holds what the hooks share. `shell.py` reads a command the way a
shell does, so the guard judges real commands and a quoted `rm` is no delete. `replay.py` runs the guard over your past
commands to find false refusals. `import_reports.py` backs `bin/harness-import`, which brings old report cards into the
ledger.
`bin/compaction-report` measures what auto-compaction costs in your Claude Code logs and replays each session at other thresholds; `make compaction` writes `compaction-report/report.html`.

## What it does not prevent

- **It is not a sandbox.** The guard reads command text. A script that deletes files from inside Python, or a command
  built from variables it cannot see, gets through.
- **It fails open.** A bug in a hook, or a broken `.harness.json`, lets the call run. A hook never blocks on its own error.
- **Read-only agents still have Bash.** `scout`, `reviewer` and the others have no Edit or Write tool, but a shell command
  can write; only the guard applies to it.
- **Skills are mostly advice.** `skill_gate` forces a load only before the Edit and Write tools, so a script that edits a
  file gets past it. `tool-habits` is injected, but nothing checks that it is followed.
- **Reports are checked for form and for claims it can verify** (files, exit codes, quoted lines). Whether the conclusion
  is right is not checked; an `auditor` or you must do that.
- **It does not judge the code.** Style rules live in skills and tests, not in hooks.
- **Budgets count model turns, not time or tokens.**
- **A retro can be answered badly.** The Stop hook checks that a rule file changed or that a rejection has its own reason,
  not that the decision was good.
- **Nothing runs without `uv`**, and a project with no `.harness.json` gets the safety guard only.

## Agents

| Agent | Model | Edits files | Job |
|---|---|---|---|
| `scout` | haiku | no | Settles one fact with `path:line` evidence |
| `runner` | haiku | no | Runs the commands in its brief and sorts failures by cause |
| `cold-reader` | sonnet | no | Reads a brief with no history and lists what is unclear |
| `worker` | sonnet | yes | Makes one change inside a write set, with its tests |
| `reviewer` | sonnet | no | Reviews a unit against its spec, once, at the end |
| `auditor` | sonnet | no | Re-runs an agent's checks and marks each claim true or false |
| `analyst` | sonnet | no | Groups feedback by meaning and proposes up to three rule changes |
| `planner` | sonnet | no | Turns a request into options, one recommendation, an order and judges |
| `researcher` | sonnet | no | Answers one question from outside sources, each claim with its URL |

## Skills

| Group | Skills | Use |
|---|---|---|
| Always on | `tool-habits` | Cheap tool calls: batched reads, edits that assert, the whole check chain in one call |
| Process | `orchestrator`, `workflows`, `accept`, `init`, `report` | How the main session works, picks a job shape, accepts a unit, sets a project up, and how agents report |
| Quality | `spec`, `cold-read`, `review`, `audit`, `evidence`, `testing`, `debug`, `refactor` | Writing a spec, checking a brief, reviewing, auditing, settling facts, writing tests that can fail, finding a bug's cause, changing structure safely |
| Languages | `code-python`, `code-js`, `code-html-css`, `code-terraform`, `code-shell` | Style rules, loaded before touching those files |
| Writing | `comments`, `git-commit` | When a comment stays and how it reads; how a commit is written |
| Learning | `models`, `retro` | Which model suits each role; turning past problems into rules |

## The learning loop

1. Each report's Feedback items land in `harness-feedback/inbox.md`. Its Problems go to the ledger, and its Open items stay
   in the report for you.
2. When 20 items wait, the Stop hook holds a session that filed one until a retro is done. Separately, ten new reports
   add a one-line reminder at session start.
3. One `analyst` groups the items by meaning, checks them against the code and proposes up to three changes.
4. The main session applies or rejects each one and names the result in `harness-feedback/handled.md`.
5. Problems no rule fixes yet go in `harness-feedback/open.md`, and each agent of that role is told at its start.

## Configuration: `.harness.json`

Every key is optional; `{}` turns on the report and turn checks alone.

| Key | Effect |
|---|---|
| `guard` | `scratch` names the scratch folder, `no_tmp` refuses `/tmp`, `ask_packages` asks before package changes, `lock` forces Python through a wrapper, `commit_style: false` turns the commit rule off |
| `delegate` | The main session hands edits to agents; `write_allow` and `bash_allow` list what it may still do |
| `brief` | Briefs must hold the lines each role needs. `required` replaces the defaults |
| `skill_gate` | Maps a file pattern to the skills to load before editing it |
| `budget` | Model turns per role, with `*` for the rest. It replaces the default table, so an unlisted role has none. A brief overrides it with `Budget: 30 turns` |
| `report` | Extra problem causes |
| `stop` | Minimum calls before a status is due, its headings, and which files count as rules |

Files the plugin writes in a project: `harness-feedback/` (inbox, handled lines, open problems, the retro mark). Throwaway
files go in the scratch folder. The ledger lives in the plugin's data folder, not in the project.
