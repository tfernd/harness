# harness

A Claude Code plugin that makes an AI coding session safer and cheaper to trust. It adds three things: **hooks** that
refuse risky or wasteful actions, **skills** that give the model short rule sheets, and **agents** that do narrow jobs
(find a fact, review a diff, run a check) and must report in a fixed, checked form.

**[See the Harness Map](https://tfernd.github.io/harness/)**: one page on what runs when, what each rule stops, and who does what. `make map` rebuilds it from the repo, and `make check` fails when it is stale.

Install, update and project setup are written for agents in [AGENTS.md](AGENTS.md). This page says what the plugin does,
how the parts fit, what it stops and what it does not.

## What it is for

- **Stop damage.** No force push, no `git reset --hard`, and no `rm` that loses work: a delete in the project moves to
  `__harness__/trash/`, in any project.
- **Stop wasted turns** (in every project). Every agent starts knowing how to make cheap tool calls. Under zsh, a glob that matches nothing is refused and an unquoted pattern (`--include=*.py`) is quoted for the tool; a foreground `sleep` is removed or moved to the
  background, with a note, and an agent that reads one small thing at a time is nudged.
- **Make agent work checkable.** A sub-agent cannot end with "done": its report has fixed sections, and its claims (files
  changed, exit codes, `path:line` evidence) are checked against what it really did.
- **Turn problems into rules.** What agents report piles up in an inbox, and a due retro turns it into changes.
- **Keep the cost down.** The main session orchestrates: it scripts repetitive work, hands changes to `harness:worker` agents
  (a hook caps the edits it makes itself in one turn), and uses agents where parallel work pays.

## How you use it

Install it once (see [AGENTS.md](AGENTS.md)) and run `/harness:init` in a project. Then work as usual: you ask, and the
main session follows the `orchestrator` skill. `/harness:init` writes an `AGENTS.md`. You see a refusal
only when a hook stops something (the agent is told what to change, so usually you do nothing), a question when a package
change needs your yes, and a closing status after a big job. In this repo, `make help` lists the checks.

## How the pieces work together

```
you ── ask ──> main session (follows the orchestrator skill)
                 │  works itself; scripts the repetitive part
                 │  briefs agents only for parallel or large units
                 ▼
        agents: planner · cold-reader · analyst · scout · researcher · worker · designer · releaser · runner · reviewer · auditor
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

## One mode: everywhere

Every rule runs in every repo with no setup: the safety guard with its scratch folder (`__scratch__/`), `/tmp` and package-change
rules, the commit rule, start-up context, turn tracking, retros and the feedback inbox, the brief, skill, budget and report
checks for every agent, and the cap on the main session's own edits. One rule stays off until a project names it:
`delegate`. A start folder that is `/`, the home folder or a parent of it is no project: there
the scratch rule is off and the feedback goes to the plugin's data folder, not into the folder.

Settings come in two layers, each key over the one before: the plugin's defaults (every rule on), then the owner's file
(`~/.config/harness/config.json`, or `$HARNESS_CONFIG`), which only overrides. Its optional `"projects"` key maps an absolute path or a glob to
sections that apply to a matching project root. No file inside a project is read. A project root is the git work-tree root of the session folder (the folder itself with no `.git`). A rule wanted off is set
off in the owner file, for example `"commit_style": false` or `"main_edits": {"max": 0}`.

## The hooks and what they stop

| Kind | Hook | When | What it does |
|---|---|---|---|
| Guard | `guard.py`, always | Before a command or edit | Moves what `rm` and `rmdir` name in the project into `__harness__/trash/<call id>/` and says so; `rm` deletes inside `__scratch__/` and the Claude scratchpad. Refuses every other delete (a glob, the project root, a path outside the project or under `node_modules`, `dist`, `.venv` or `.git`, `unlink`, `shred`, `find -delete`, `git clean`), pushes that rewrite remote history, and every git command that discards work or rewrites history (`reset --hard`, `checkout -- <paths>` or `.` or `-f`, `switch -f`, `-C` or `--force-create`, `checkout -B`, `restore` without `--staged`, `stash drop` and `clear`, `branch -D`, `-f`, `--force`, `-M` or `-C`, `tag -d`, `rebase` and `pull --rebase`, `commit --amend`, `filter-branch`, `filter-repo`, `reflog expire`, `gc --prune`, `update-ref -d`, `read-tree --reset -u`, a forced `fetch` into a ref, `worktree remove --force`), which are yours to run. It reads them through wrappers (`bash -c`, `ssh`, `watch`, `parallel`, `su -c`, aliases) and a long option by a prefix of three letters or more, and refuses one it cannot read: a variable as the command, a shell fed from stdin, `python -c` with `os.system` or `subprocess`. Also refuses globs that match nothing. Lets the call run changed, and says so, when it quotes a glob in a pattern position (`--include=*.py`, `-name`, `-g`) or removes a foreground `sleep` (or moves the call to the background) |
| Guard | `guard.py`, configured | Before a command or edit | Asks you before a package change by any manager (`pip`, `uv`, `npm`, `pnpm`, `yarn`, `bun`, `cargo`, `go`, `gem`, `pipx`, `conda`, `mamba`, `poetry`, `apt`, `dnf`, `brew`, `setup.py install`, `uv run --with`); a read-only call is not asked. Lets writes under `/tmp` and shell writes outside `__scratch__/` run, with a note on where such files belong |
| Guard | `commit_gate.py` | Before a command | Refuses a commit whose message `-m`, `-F` or a heredoc shows is not `type(scope): title` with `* ` bullets, and a commit, tag, merge or pull request whose text, trailers or author show AI attribution (`Co-authored-by`, `Assisted-by`, `Generated-by` or `Signed-off-by` naming an AI, a line opening with "Generated with", "Generated by" or "Made with" an AI, a robot emoji), and the `-f`/`-F` fields of `gh api`, read after Unicode folding. Refuses a commit whose message it cannot read (an editor, a variable or substitution, a file written in the same command): it names `-F <file>` written beforehand or a quoted heredoc. It reads through `env`, `bash -c`, `cd X &&` and `git -C`. Also refuses a commit that leaves fewer test definitions in the changed test files than the last commit, unless its message has a bullet `* Tests removed: <reason>` (`tests_kept` turns it off). It counts Python, JavaScript, Go and Rust tests, and a test whose body is only `pass`, `...` or a docstring counts for nothing |
| Guard | `delegate.py` | Before a command or edit | With the `delegate` key, lets edits and unlisted commands from the main session run and adds a note that agents do the work here. In every project, `main_edits` refuses the main session's edit once it has made `max` (default 3) edits in one turn outside `allow` (default `__harness__/feedback/*`, `__scratch__/*`): the change goes to a `harness:worker`; `max` 0 turns it off; Bash edits and files outside the project are not counted |
| Guard | `budget.py` | Before every call | Refuses every call but the handback from an agent past its turns, so it sends a partial report. Any agent type has a default. Every `progress.every` calls (default 10, 0 is off) an agent adds a line to a progress file, and the main session's next call gets a one-line note of what each agent is doing |
| Gate | `brief_lint.py` | Before an agent starts | In any project, refuses a generic agent (`general-purpose`, `Explore`, `Plan`, or no type) and names the harness role to use. With the `brief` key, lets the brief go and adds a note when it has no `Goal:`, when a worker brief has no `Write set:` and `Judge:`, a reviewer brief no `Input:` and `Tree:`, an auditor brief no `Input:` and `Judge:`, a runner brief no `Runs:`, or when the budget is in anything but turns |
| Gate | `report_gate.py` | An agent hands back or stops | Any agent type must end with a report: Answer, Not proven and a Verdict of done, partial or blocked, plus Problems, Next time, Open and Feedback when they have something to say. Refuses the handback of a malformed one, or one its transcript does not back, while the agent can still fix it; an agent that stops without a handback gets the report sent back instead. Up to 3 times in all, naming only the sections that are wrong. Files problems and writes the ledger |
| Teacher | `context.py` | Session or agent starts | Adds text agents would otherwise forget: load the orchestrator, the whole `tool-habits` skill, the report form owed, past lessons, open problems. Refuses nothing |
| Teacher | `skill_gate.py` | Before a command or edit | With the `skill_gate` key, lets an edit run and gives the agent the skill's own text when it has not seen it, for that kind of file, including a shell write or a Python script that writes, and for a commit or pull request the `git-commit` text. Once per agent; needs no Skill call |
| Teacher | `nudge.py` | After a read | Adds one line of advice after a repeated read or three small reads in a row, at most twice per agent, and once per agent after a test or build piped into `tail`/`head` without `pipefail`. Refuses nothing |
| Closer | `turn.py` | Your turn ends | Holds the turn for a missing status after a long turn, a status that does not name each agent run under `## Agents`, a lesson with no rule changed, a bare "no lessons" after a refused call, or a due retro |

A refusal says which rule fired and what to change. A rule marked as letting the call run says so in a note with the result.

Four more files in `hooks/` are not hooks. `common.py` holds what the hooks share. `shell.py` reads a command the way a
shell does, so the guard judges real commands and a quoted `rm` is no delete. `replay.py` runs the guard over your past
commands to find false refusals. `import_reports.py` backs `bin/harness-import`, which brings old report cards into the
ledger.

## What it does not prevent

- **It is not a sandbox.** The guard reads command text. A script that deletes files from inside Python, or a command
  built from variables it cannot see, gets through.
- **It fails open.** A bug in a hook, or a broken owner file, lets the call run. A hook never blocks on its own error.
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

| Kind | Agent | Model | Edits files | Job |
|---|---|---|---|---|
| Thinker | `planner` | sonnet | no | Turns a request into options, one recommendation, an order and judges |
| Thinker | `cold-reader` | sonnet | no | Reads a brief with no history and lists what is unclear |
| Thinker | `analyst` | sonnet | no | Groups feedback by meaning and proposes up to three rule changes |
| Finder | `scout` | haiku | no | Settles one fact with `path:line` evidence |
| Finder | `researcher` | sonnet | no | Answers one question from outside sources, each claim with its URL |
| Doer | `worker` | sonnet | yes | Makes one change inside a write set, with its tests |
| Doer | `designer` | opus | yes | Makes pages, layouts and mock-ups inside a write set, as variants when asked |
| Doer | `releaser` | sonnet | yes | Splits a diff into commit units, runs the pre-push check, drafts the PR body, writes CI files; never commits or pushes |
| Doer | `runner` | haiku | no | Runs the commands in its brief and sorts failures by cause |
| Checker | `reviewer` | sonnet | no | Reviews a unit against its spec, once, at the end |
| Checker | `auditor` | sonnet | no | Re-runs an agent's checks and marks each claim true or false |

## Skills

| Kind | Skills | Use |
|---|---|---|
| Run the job | `orchestrator`, `workflows`, `models`, `accept`, `init` | How the main session works, picks a job shape and a model per role, accepts a unit, sets a project up |
| Think | `evidence`, `debug`, `spec`, `cold-read` | Settling facts, finding a bug's cause, writing a spec, checking a brief |
| Build | `code-python`, `code-js`, `code-html-css`, `code-shell`, `code-terraform`, `refactor`, `comments`, `git-commit`, `design`, `release` | Style rules loaded before touching those files, changing structure safely, comments, commits, visual design, preparing a release |
| Check | `testing`, `review`, `audit` | Writing tests that can fail, reviewing a unit, auditing a report |
| Report and learn | `report`, `retro`, `hook-authoring`, `skill-authoring`, `agent-authoring` | How agents report, turning past problems into rules, and writing a hook, skill or agent |
| Habits | `tool-habits` | Cheap tool calls: batched reads, edits that assert, the whole check chain in one call |

## The learning loop

1. Each report's Feedback items land in `__harness__/feedback/inbox.md`. Its Problems go to the ledger, and its Open items stay
   in the report for you.
2. When 20 items wait, the Stop hook holds a session that filed one until a retro is done. Separately, ten new reports
   add a one-line reminder at session start.
3. One `analyst` groups the items by meaning, checks them against the code and proposes up to three changes.
4. The main session applies or rejects each one and names the result in `__harness__/feedback/handled.md`.
5. Problems no rule fixes yet go in `__harness__/feedback/open.md`, and each agent of that role is told at its start.

## Other tools

`bin/harness-port` converts the skills, agents and hooks into the global folder of another tool, so one install serves
every project there. Run it from a clone and rerun it after `git pull`: hook commands point at that checkout.

```sh
bin/harness-port --target kiro      # ~/.kiro: skills, agents, hooks/harness-hooks.json
bin/harness-port --target cortex    # ~/.snowflake/cortex: skills, agents, hooks.json (merged, yours are kept)
```

Cortex Code and Kiro without a clone: one line installs the port, and running it again updates it. The script
fetches the repo into `~/.local/share/harness` and ports from there.

```sh
curl -fsSL https://raw.githubusercontent.com/tfernd/harness/main/install.sh | sh -s -- cortex   # or kiro
```

Add `--uninstall` to remove it, then delete the clone it names (`~/.local/share/harness`).

`--dest DIR` writes elsewhere, `--dry-run` writes nothing, `--uninstall` removes exactly the files in
`harness-port.json`. Everything installs as `harness-<name>`; a command prints what it did not port.

- Kiro loses: `SubagentStart` and `SubagentStop` hooks (no trigger), the owner prompt (a guard "ask" becomes a block),
  command rewrites (the `sleep` fix, a quoted pattern and a move to the trash each become a block with the note), hook context outside session start and prompt submit,
  and agent models (pass `--model haiku=ID` for each). Agent prompts sit in `agents/harness-<name>.md` beside the JSON.
- Cortex loses: `SubagentStart`, preloaded skills on agents (load them by name), agent models, tool ids it lacks, and
  the report gate blocks nothing (advisory). An "ask" becomes a block.

## Configuration: the owner file

Every key is optional and the file itself is not needed: the defaults apply without it. The keys sit at the top of the owner file, or inside a `projects` entry to apply to one project.

| Key | Effect |
|---|---|
| `guard` | `scratch` names `__scratch__/`, `no_tmp` notes writes under `/tmp`, `ask_packages` asks before package changes and tool runs (`uvx`, `npx`, `bunx`, `dlx`), `commit_style: false` turns the commit rule off |
| `main_edits` | `max` (default 3, 0 is off) and `allow` (globs; default `__harness__/*`, `__scratch__/*`): the main session's edits per turn outside `allow` before the hook refuses and the change goes to a worker |
| `delegate` | Off until set. The main session hands edits to agents; `write_allow` and `bash_allow` list what it may still do |
| `brief` | Briefs must hold the lines each role needs. `required` replaces the defaults |
| `skill_gate` | Maps a file pattern to the skills to load before editing it |
| `budget` | Model turns per role, with `*` for the rest. It replaces the default table, so an unlisted role has none. A brief overrides it with `Budget: 30 turns` |
| `report` | Extra problem causes |
| `stop` | Minimum calls before a status is due, its headings, and which files count as rules |

Folders the plugin keeps in a project, each ignored by git through its own `.gitignore` holding `*`: `__harness__/` (a `README.md` that maps it,
`feedback/` with the inbox, handled lines, open problems and the retro mark, and `trash/`, where the guard moves what `rm`
and `rmdir` name, one folder per call; nothing reads it and the owner empties it) and `__scratch__/` for throwaway files. `rg` and Glob skip ignored folders,
so read their files by path. An old `harness-feedback/` folder moves into `__harness__/feedback/` at session start. The ledger lives in the plugin's data folder, not in the project.
