# harness

A Claude Code plugin that makes an AI coding session safer and cheaper to trust. It adds three things: **hooks** that
refuse risky or wasteful actions, **skills** that give the model short rule sheets, and **agents** that do narrow jobs
(find a fact, review a diff, run a check) and must report in a fixed, checked form.

Install, update and project setup are written for agents in [AGENTS.md](AGENTS.md). This page says what the plugin does,
how the parts fit, what it stops and what it does not.

## What it is for

- **Stop damage.** No `rm`, no force push, no `git reset --hard`, in any project.
- **Stop wasted turns** (in every project). Every agent starts knowing how to make cheap tool calls. Under zsh, globs that match nothing are refused in any project; a foreground `sleep` is removed or moved to the
  background, with a note, and an agent that reads one small thing at a time is nudged.
- **Make agent work checkable.** A sub-agent cannot end with "done": its report has fixed sections, and its claims (files
  changed, exit codes, `path:line` evidence) are checked against what it really did.
- **Turn problems into rules.** What agents report piles up in an inbox, and a due retro turns it into changes.
- **Keep the cost down.** The main session orchestrates: it scripts repetitive work, hands changes to `harness:worker` agents
  (a hook caps the edits it makes itself in one turn), and uses agents where parallel work pays.

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
 when an agent ends report_gate: checks the report before its handback, files problems in the inbox and the ledger
 when a turn ends   turn: status, each agent's outcome, lessons, and a retro when 20 items wait
                 ▼
 inbox ──> analyst ──> a new rule in a hook, skill or brief template, or a line in open.md
```

Skills are text the model reads. Hooks run outside the model, so it cannot talk its way past them. Reports are where the
two meet: a skill says what to write, a hook checks it.

## Two modes

| Mode | When | What runs |
|---|---|---|
| **Everywhere** | The plugin is installed; no file needed | The safety guard, start-up context, turn tracking, the brief, skill, budget and report checks for `harness:` roles. Feedback goes to the plugin's data folder; nothing is written into the repo |
| **Opted in** | The project has a `.harness.json` | All of the above, plus the guard's project rules (scratch, `/tmp`, packages, lock), the commit rule, retros, budgets and reports for the repo's own agents, and each rule its keys switch on |

Settings come in three layers, each key over the one before: the plugin's defaults, the owner's file
(`~/.config/harness/config.json`, or `$HARNESS_CONFIG`), then the project's `.harness.json`. The plugin's defaults that apply in every repo,
with or without a `.harness.json`, are the template's `brief`, `skill_gate` and `main_edits` sections (`DEFAULT_SECTIONS` in `hooks/common.py`).

## The hooks and what they stop

| Hook | When | What it does |
|---|---|---|
| `context.py` | Session or agent starts | Adds text agents would otherwise forget: load the orchestrator, the whole `tool-habits` skill, the report form owed, past lessons, open problems. Refuses nothing |
| `guard.py`, always | Before a command or edit | Refuses deletes (`rm`, `rmdir`, `unlink`, `shred`, `find -delete`, `git clean`; `rm` works inside a named scratch folder), pushes that rewrite remote history, `git reset --hard`, globs that match nothing or that the shell would expand too early. Lets a foreground `sleep` run changed (removed, or moved to the background) and says so |
| `guard.py`, configured | Before a command or edit | Asks you before package changes and refuses Python run outside its lock wrapper. Lets writes under `/tmp` and shell writes outside the scratch folder run, with a note on where such files belong |
| `commit_gate.py` | Before a command | Refuses a commit whose message `-m`, `-F` or a heredoc shows is not `type(scope): title` with `* ` bullets, and a commit or pull request whose text shows AI attribution. It cannot read a commit that opens an editor, or a message in a variable set by an earlier call |
| `delegate.py` | Before a command or edit | With the `delegate` key, lets edits and unlisted commands from the main session run and adds a note that agents do the work here. In every project, `main_edits` refuses the main session's edit once it has made `max` (default 3) edits in one turn outside `allow` (default `harness-feedback/*`, `scratch/*`): the change goes to a `harness:worker`; `max` 0 turns it off; Bash edits are not counted |
| `skill_gate.py` | Before a command or edit | With the `skill_gate` key, lets an edit run and gives the agent the skill's own text when it has not seen it, for that kind of file, including a shell write or a Python script that writes, and for a commit or pull request the `git-commit` text. Once per agent; needs no Skill call |
| `brief_lint.py` | Before an agent starts | In any project, refuses a generic agent (`general-purpose`, `Explore`, `Plan`, or no type) and names the harness role to use. With the `brief` key, lets the brief go and adds a note when it has no `Goal:`, when a worker brief has no `Write set:` and `Judge:`, a reviewer brief no `Input:` and `Tree:`, an auditor brief no `Input:` and `Judge:`, a runner brief no `Runs:`, or when the budget is in anything but turns |
| `budget.py` | Before every call | Refuses every call but the handback from an agent past its turns, so it sends a partial report. Any agent type has a default |
| `nudge.py` | After a read | Adds one line of advice after a repeated read or three small reads in a row, at most twice per agent, and once per agent after a test or build piped into `tail`/`head` without `pipefail`. Refuses nothing |
| `report_gate.py` | An agent hands back or stops | Any agent type must end with a report: Answer, Not proven and a Verdict of done, partial or blocked, plus Problems, Next time, Open and Feedback when they have something to say. Refuses the handback of a malformed one, or one its transcript does not back, while the agent can still fix it; an agent that stops without a handback gets the report sent back instead. Up to 3 times in all, naming only the sections that are wrong. Files problems and writes the ledger |
| `turn.py` | Your turn ends | Holds the turn for a missing status after a long turn, a status that does not name each agent run under `## Agents`, a lesson with no rule changed, a bare "no lessons" after a refused call, or a due retro |

A refusal says which rule fired and what to change. A rule marked as letting the call run says so in a note with the result.

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
- **Skills are mostly advice.** `skill_gate` reads a script's text, so a path built at run time gets past it. `tool-habits` is injected, but nothing checks that it is followed.
- **Reports are checked for form and for claims it can verify** (files, exit codes, quoted lines). Whether the conclusion
  is right is not checked; an `auditor` or you must do that.
- **It does not judge the code.** Style rules live in skills and tests, not in hooks.
- **Budgets count model turns, not time or tokens.**
- **A retro can be answered badly.** The Stop hook checks that a rule file changed or that a rejection has its own reason,
  not that the decision was good.
- **Nothing runs without `uv`.**

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

## Other tools

`bin/harness-port` converts the skills, agents and hooks into the global folder of another tool, so one install serves
every project there. Run it from a clone and rerun it after `git pull`: hook commands point at that checkout.

```sh
bin/harness-port --target kiro      # ~/.kiro: skills, agents, hooks/harness.json
bin/harness-port --target cortex    # ~/.snowflake/cortex: skills, agents, hooks.json (merged, yours are kept)
```

`--dest DIR` writes elsewhere, `--dry-run` writes nothing, `--uninstall` removes exactly the files in
`harness-port.json`. Everything installs as `harness-<name>`; a command prints what it did not port.

- Kiro loses: `SubagentStart` and `SubagentStop` hooks (no trigger), the owner prompt (a guard "ask" becomes a block),
  command rewrites (the `sleep` fix becomes a block with a note), hook context outside session start and prompt submit,
  and agent models (pass `--model haiku=ID` for each). Agent prompts sit in `agents/harness-<name>.md` beside the JSON.
- Cortex loses: `SubagentStart`, preloaded skills on agents (load them by name), agent models, tool ids it lacks, and
  the report gate blocks nothing (advisory). An "ask" becomes a block.

## Configuration: `.harness.json`

Every key is optional; the same keys work in the owner's file. `{}` opts a project in with the defaults.

| Key | Effect |
|---|---|
| `guard` | `scratch` names the scratch folder, `no_tmp` refuses `/tmp`, `ask_packages` asks before package changes, `lock` forces Python through a wrapper, `commit_style: false` turns the commit rule off |
| `main_edits` | `max` (default 3, 0 is off) and `allow` (globs; default `harness-feedback/*`, `scratch/*`): the main session's edits per turn outside `allow` before the hook refuses and the change goes to a worker |
| `delegate` | The main session hands edits to agents; `write_allow` and `bash_allow` list what it may still do |
| `brief` | Briefs must hold the lines each role needs. `required` replaces the defaults |
| `skill_gate` | Maps a file pattern to the skills to load before editing it |
| `budget` | Model turns per role, with `*` for the rest. It replaces the default table, so an unlisted role has none. A brief overrides it with `Budget: 30 turns` |
| `report` | Extra problem causes |
| `stop` | Minimum calls before a status is due, its headings, and which files count as rules |

Files the plugin writes in a project: `harness-feedback/` (inbox, handled lines, open problems, the retro mark). Throwaway
files go in the scratch folder. The ledger lives in the plugin's data folder, not in the project.
