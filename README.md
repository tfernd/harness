# harness

A Claude Code plugin that makes an AI coding session safer and cheaper to trust. It adds three things: **hooks** that
refuse risky or wasteful actions, **skills** that give the model short rule sheets, and **agents** that do narrow jobs
(find a fact, review a diff, run a check) and must report in a fixed, checked form.

**[See the Harness Map](https://tfernd.github.io/harness/)**: one page on what runs when, what each rule stops, and who does what. `make map` rebuilds it from the repo. `make check` fails when it is stale and also runs the cases, skill and leak checks.

Install, update and project setup are written for agents in [AGENTS.md](AGENTS.md). This page says what the plugin does,
how the parts fit, what it stops and what it does not.

## What it is for

- **Stop damage.** No force push, no `git reset --hard`, and no delete at all: agents never run `rm`, `rmdir`, `unlink`, `shred`, `find -delete` or `git clean`, in any project.
- **Stop wasted turns** (in every project). Every agent starts knowing how to make cheap tool calls. Under zsh, a glob that matches nothing is refused and an unquoted pattern (`--include=*.py`) is quoted for the tool, with a note,.
- **Make agent work checkable.** A sub-agent cannot end with "done": its report has fixed sections, and its claims (files
  changed, exit codes, `path:line` evidence) are checked against what it really did.
- **Keep the cost down.** The main session orchestrates: it scripts repetitive work, hands changes to `harness:worker` agents
  (a hook caps the edits it makes itself in one turn), and uses agents where parallel work pays.

## How you use it

Install it once: in Claude Code, `claude plugin marketplace add https://github.com/tfernd/harness.git; claude plugin marketplace update harness && claude plugin install harness@harness --scope user && claude plugin update harness@harness` installs or updates it (see [AGENTS.md](AGENTS.md)). Then run `/harness:init` in a project. Then work as usual: you ask, and the
main session follows the `orchestrator` skill. `/harness:init` writes an `AGENTS.md`. You see a refusal
only when a hook stops something (the agent is told what to change, so usually you do nothing), a question when a package
change needs your yes, and a closing status after a big job. In this repo, `make help` lists the checks.

The band (`harness-band`) is a separate Claude Code plugin: `claude plugin install harness-band@harness --scope user`. Kiro and Cortex Code get the harness only.

## How the pieces work together

```
you ── ask ──> main session (follows the orchestrator skill)
                 │  works itself; scripts the repetitive part
                 │  briefs agents only for parallel or large units
                 ▼
        agents: planner · scout · researcher · worker · designer · reviewer
                 │  each ends with a REPORT

 at every start     context: orchestrator pointer, tool-habits, report form
 before each call   guard · skill_gate · budget
 when an agent ends report_gate: checks the report before its handback
 when a turn ends   turn: holds for the status
```

Skills are text the model reads. Hooks run outside the model, so it cannot talk its way past them. Reports are where the
two meet: a skill says what to write, a hook checks it.

## One mode: everywhere

Every rule runs in every repo with no setup: the safety guard with its scratch folder (`/tmp/harness/<project>/`) and package-change
rules, the commit rule, start-up context, turn tracking, and the skill and report
checks for every agent. A start folder that is `/`, the home folder or a parent of it is no project: there
the scratch rule is off.

Settings come in two layers, each key over the one before: the plugin's defaults (every rule on), then the owner's file
(`~/.config/harness/config.json`, or `$HARNESS_CONFIG`), which only overrides. Its optional `"projects"` key maps an absolute path or a glob to
sections that apply to a matching project root. No file inside a project is read. A project root is the git work-tree root of the session folder (the folder itself with no `.git`). A rule wanted off is set
off in the owner file, for example `{"guard": {"commit_style": false}}`.

## The hooks and what they stop

| Kind | Hook | When | What it does |
|---|---|---|---|
| Guard | `guard.py`, always | Before a command or edit | Refuses every delete, anywhere, for the main session and sub-agents alike (`rm`, `rmdir`, `unlink`, `shred`, `truncate`, `find -delete`, `git clean`, `make clean` and `distclean`, `busybox rm`, `ssh <host> rm`, a variable or substitution that names a deleter as the command, and `python -c` or a Python heredoc that calls `os.remove`, `os.unlink`, `os.rmdir`, `shutil.rmtree`, `Path.unlink` or `Path.rmdir`; `--help`, `--version` and a dry run, `-n` alone or in a letter cluster such as `git clean -nfd`, are not deletes): the main session is told to give you the command in the chat and say why, and a sub-agent is told to leave the file. Throwaway files go in `/tmp/harness/<project>/`, which no agent cleans: a fresh run takes a new folder name. Also refuses pushes that rewrite remote history, and every git command that discards work or rewrites history (`reset --hard`, `checkout -- <paths>` or `.` or `-f`, `switch -f`, `-C` or `--force-create`, `checkout -B`, `restore` without `--staged`, `stash drop` and `clear`, `branch -D`, `-f`, `--force`, `-M` or `-C`, `tag -d`, `rebase` and `pull --rebase`, `commit --amend`, `filter-branch`, `filter-repo`, `reflog expire`, `gc --prune`, `update-ref -d`, `read-tree --reset -u`, a forced `fetch` into a ref, `worktree remove --force`), which are yours to run. It reads them through wrappers (`bash -c`, `ssh`, `watch`, `parallel`, `su -c`, aliases) and a long option by a prefix of three letters or more, and refuses one it cannot read: a variable as the command, a shell fed from stdin, `python -c` with `os.system` or `subprocess`. Also refuses globs that match nothing. Lets the call run changed, and says so, when it quotes a glob in a pattern position (`--include=*.py`, `-name`, `-g`) |
| Guard | `guard.py`, always | Before a command | Refuses `pkill -f`, `pkill` without `-x` and `killall -r`, which can match the wrong process; use `pgrep -x` then `kill <pid>` |
| Guard | `guard.py`, always | Before a command | Lets a test, check or build piped into `tail` or `grep` (not `grep` with `-q`, `-m`, `-l` or `-L`) run with `set -o pipefail` added, and says so, so the pipe keeps the failing exit code |
| Guard | `guard.py`, configured | Before a command or edit | Asks you before a package change by any manager (`pip`, `uv`, `npm`, `pnpm`, `yarn`, `bun`, `cargo`, `go`, `gem`, `pipx`, `conda`, `mamba`, `poetry`, `apt`, `dnf`, `brew`, `setup.py install`, `uv run --with`); a read-only call is not asked, and before a command that writes to an AWS account (`aws` other than `describe-`, `list-`, `get-` and similar reads, `s3 cp` to `s3://`, `s3 rm`, `sam deploy`, `cdk deploy`, `terraform`, `tofu` or `terragrunt` `apply`, `destroy`, `import`, `taint`, `state rm|mv|push`), before a command or file read that shows a secret (`.env`, `~/.aws/credentials`, private keys, `*.pem`, `*.tfstate`, `printenv`, `terraform output`, `aws secretsmanager get-secret-value`, `gh auth token`; the Read tool too), or a piped installer (`curl ... | sh`, `sh -c "$(curl ...)"`, `bash <(curl ...)`); a read-only call is not asked. Lets shell writes outside the throwaway folder run, with a note on where such files belong |
| Guard | `guard.py`, sub-agents | Before a command | Refuses a git or `gh` command that writes (commit, push, pull request, merge, tag, branch change) from a sub-agent; the main session may run them on your word |
| Guard | `commit_gate.py` | Before a command | Refuses a commit whose message `-m`, `-F` or a heredoc shows is not `type(scope): title` with `* ` bullets, and a commit, tag, merge or pull request whose text, trailers or author show AI attribution (`Co-authored-by`, `Assisted-by`, `Generated-by` or `Signed-off-by` whose name is an AI tool or model (a person named Jean-Claude or Ai passes), a line opening with "Generated with", "Generated by" or "Made with" an AI tool ("Made with cursor pagination" passes), a robot emoji), and the `-f`/`-F` fields of `gh api`, read after Unicode folding. Refuses a commit whose message it cannot read (an editor, a variable or substitution, a file written in the same command): it names `-F <file>` written beforehand or a quoted heredoc. It reads through `env`, `bash -c`, `cd X &&` and `git -C`. Also refuses a commit that leaves fewer test definitions in the changed test files than the last commit, unless its message has a bullet `* Tests removed: <reason>` (`tests_kept` turns it off). It counts Python, JavaScript, Go and Rust tests, and a test whose body is only `pass`, `...` or a docstring counts for nothing |
| Note | `budget.py` | Before every call | Every `progress.every` calls (default 10, 0 is off) an agent adds a line to a progress file, and the main session's next call gets a one-line note of what each agent is doing |
| Gate | `report_gate.py` | An agent hands back or stops | Any agent type must end with a report that has its sections as `##` headings, in order: Answer, Not proven and Verdict, plus Problems, Next time, Open and Feedback when they have something to say, with no other `##` heading. It checks the headings only, never the wording or the length. Refuses the handback of a report that misses or misorders one while the agent can still fix it; an agent that stops without a handback gets the report sent back instead. Up to 3 times in all, naming only the sections that are wrong. Files problems |
| Teacher | `context.py` | Session or agent starts | Adds text agents would otherwise forget: for the main session, the start line "This codebase is yours"; load the orchestrator, the whole `tool-habits` skill, the report form owed. Refuses nothing |
| Teacher | `skill_gate.py` | Before a command or edit | With the `skill_gate` key, lets an edit run and gives the agent the skill's own text when it has not seen it, for that kind of file, including a shell write or a Python script that writes, and for a commit or pull request the `git-commit` text. Once per agent; needs no Skill call |
| Closer | `turn.py` | Your turn ends | Holds the turn for a missing status after a long turn; only notes (the turn ends) a status that does not name each agent run under `## Agents` |

`hooks.json` runs one command per event, `hooks/dispatch.py <Event>`, which reads the event once and calls the hooks above in process, in a fixed order (`ROUTES` in that file); a block from any hook ends the run, notes are joined, a hook that crashes lets the call run, and each hook still runs alone with `uv run --script hooks/<name>.py`.

A refusal says which rule fired and what to change. A rule marked as letting the call run says so in a note with the result.

Four more files in `hooks/` are not hooks. `common.py` holds what the hooks share. `shell.py` reads a command the way a
shell does, so the guard judges real commands and a quoted `rm` is no delete. `replay.py` runs the guard over your past
commands to find false refusals.

## What it does not prevent

- **It is not a sandbox.** The guard reads command text. A script that deletes files from inside Python, or a command
  built from variables it cannot see, gets through.
- **It fails open.** A bug in a hook, or a broken owner file, lets the call run. A hook never blocks on its own error.
- **Read-only agents still have Bash.** `scout`, `reviewer` and the others have no Edit or Write tool, but a shell command
  can write; only the guard applies to it.
- **Skills are mostly advice.** `skill_gate` reads a script's text, so a path built at run time gets past it. `tool-habits` is injected, but nothing checks that it is followed.
- **Reports are checked for form and for claims it can verify** (files, exit codes, quoted lines). Whether the conclusion
  is right is not checked; you must do that.
- **It does not judge the code.** Style rules live in skills and tests, not in hooks.
- **Nothing runs without `uv`.**

## Agents

| Kind | Agent | Model | Edits files | Job |
|---|---|---|---|---|
| Thinker | `planner` | sonnet | no | Turns a request into options, one recommendation, an order and judges |
| Finder | `scout` | haiku | no | Settles one fact with `path:line` evidence |
| Finder | `researcher` | sonnet | no | Answers one question from outside sources, each claim with its URL |
| Doer | `worker` | sonnet | yes | Makes one change in the files its brief names, with its tests |
| Doer | `designer` | sonnet | yes | Makes pages, layouts and mock-ups, as variants when asked |
| Checker | `reviewer` | sonnet | no | Reviews a unit against its spec, once, at the end |

## Skills

| Kind | Skills | Use |
|---|---|---|
| Run the job | `orchestrator`, `workflows`, `init` | How the main session works, picks a model per role, accepts a unit, picks a job shape, builds visual work mock-first, sets a project up |
| Think | `evidence`, `spec` | Settling facts, writing and cold-reading a spec |
| Build | `code-python`, `code-js`, `code-html-css`, `code-shell`, `code-terraform`, `code-sql`, `code-yaml`, `code-make`, `code`, `git`, `design` | Style rules loaded before touching those files, comments, names and refactoring in any language, commits and releases, visual design |
| Tools | `aws-cli`, `snowflake-cli` | Running those command-line tools safely: what reads, what writes, what to ask first |
| Check | `testing`, `review` | Writing tests that can fail, reviewing a unit, finding a bug's cause, sweeping a whole repo against itself |
| Report | `report`, `authoring` | How agents report, and writing a hook, skill or agent |
| Habits | `tool-habits` | Cheap tool calls: batched reads, edits that assert, the whole check chain in one call |

## Other tools

`bin/harness-port` converts the skills, agents and hooks into the global folder of another tool, so one install serves
every project there. Run it from a clone and rerun it after `git pull`: hook commands point at that checkout.

```sh
bin/harness-port --target kiro
bin/harness-port --target cortex
```

- `kiro` writes `~/.kiro`: skills, agents, `hooks/harness-hooks.json`.
- `cortex` writes `~/.snowflake/cortex`: skills, agents, `hooks.json` (merged, yours are kept).

Cortex Code installs it as a plugin with its own CLI. The one line below updates it, or installs it when it is absent;
`cortex plugin uninstall harness` removes it:

```sh
cortex plugin update harness || cortex plugin install tfernd/harness
```

Kiro without a clone: one line installs the port, and running it again updates it. The script fetches the repo into
`~/.local/share/harness` and ports from there (it still takes `cortex` too).

```sh
curl -fsSL https://raw.githubusercontent.com/tfernd/harness/main/install.sh | sh -s -- kiro
```

Add `--uninstall` to remove it, then delete the clone it names (`~/.local/share/harness`).

`--dest DIR` writes elsewhere, `--dry-run` writes no file in the target folder (the Kiro installer still updates its own clone first), `--uninstall` removes exactly the files in
`harness-port.json`. Everything installs as `harness-<name>`; a command prints what it did not port.

- Kiro loses: `SubagentStart` and `SubagentStop` hooks (no trigger), the owner prompt (a guard "ask" becomes a block),
  command rewrites (a quoted pattern becomes a block with the note), hook context outside session start and prompt submit,
  and agent models (pass `--model haiku=ID` for each). Agent prompts sit in `agents/harness-<name>.md` beside the JSON.
  A hook that matches `NotebookEdit` gets no match on Kiro, an agent's `Skill` tool is dropped, and ported agent text that mentions `TaskStop` has no equivalent.
- Kiro crew (the separate crew app): when `~/.kiro/crew/` exists the Kiro port also merges `harness-*` entries into
  `~/.kiro/crew/hooks.json` (yours are kept, the old file is saved as `hooks.json.harness-backup`, `--uninstall` removes
  only the `harness-*` entries). Each command is wrapped so that only a refusal blocks and any crash or timeout lets the
  call run, and it uses the absolute `uv` found at install time. The crew has no `SubagentStart` or `SubagentStop`
  event; a guard "ask" and a command rewrite become a block. The entry shape is the one the crew dashboard writes; the
  crew's agent specs (under `~/.kiro/agents`) also carry their own `hooks` field, which the port does not touch.
  `sh port/kiro-crew-probe.sh` checks that your crew fires an entry.
- Cortex loses: `SubagentStart`, agent models unless `--model` is passed, tool ids it lacks (`NotebookEdit`, `Skill`), and
  the report gate blocks nothing (advisory). An "ask" becomes a block. Ported agent text that mentions `TaskStop` has no equivalent.

## Configuration: the owner file

Every key is optional and the file itself is not needed: the defaults apply without it. The keys sit at the top of the owner file, or inside a `projects` entry to apply to one project.

| Key | Effect |
|---|---|
| `guard` | `scratch` names a project folder the guard treats as scratch (default none), `ask_packages` asks before package changes and tool runs (`uvx`, `npx`, `bunx`, `dlx`), except that `uvx`, `uv tool run`, `uv run --with`, `npx` and `bunx` run unasked with a release delay added (`--exclude-newer`, `--before`, `--minimum-release-age`; `tool_delay_days`, default 7, and 0 asks again; `pnpm dlx` and `yarn dlx` have no checked flag and still ask), `ask_cloud` asks before an `aws`, `sam` or `cdk` command that writes to an account, `ask_installers` asks before a fetcher piped into an interpreter, `commit_style: false` turns the commit rule off, `block_dbt_targets` false turns off the dbt non-dev target guard, `dbt_dev_targets` lists extra dev target names that pass it, `block_snow` false turns off the snow write guard, `snow_sandbox_connections` lists connection names that run snow writes like any name holding `sandbox` (not `DROP` of a database or schema), `ask_secrets` false turns off the secret question, `deny_packages` is an alias of `ask_packages` |
| `tests_kept` | `enabled: false` turns off the commit rule that refuses a commit leaving fewer test definitions in the changed test files |
| `skill_gate` | Maps a file pattern to the skills to load before editing it |
| `stop` | Minimum calls before a status is due, its headings, and which files count as rules |

Folders the plugin keeps outside the project: `~/.local/state/harness/<project>/` for state (a `README.md` maps it; `$XDG_STATE_HOME` is honoured; an old `__harness__/` is copied there once, never deleted) and `/tmp/harness/<project>/` for throwaway files, which `/tmp` clears itself. Read their files by path.
