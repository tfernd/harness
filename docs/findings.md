# Findings

What testing the harness against real use found, and what is still open. Measured over the owner's past sessions (about
2,300 agent transcripts and 110 main sessions) unless marked read. A row leaves "Open" when it is fixed and has a case.

## Open

| # | Problem | Evidence | Next |
|---|---|---|---|
| 1 | The fix for lost handback reports is not proven live | headless runs report by text, so only the desktop app shows a handback; cases cover the logic, and no case can write a transcript late, so `REPORT_WAIT_S` is undefended | After a push, count ledger rows against agents in a real session |
| 2 | Planted bugs still uncaught | see Score | Read each survivor; write a case or show it changes nothing |

## Score

Planted bugs caught by the cases: **177 of 200, 88%** (`--count 200 --seed 1`), then **51 of 60, 85%** on a fresh sample (`--count 60 --seed 2`). The 200 ran before
the last 12 cases went in, and the 60 before the last three, so each is a floor. Finish line: 95%, or each survivor read and shown to change nothing.

The survivors read so far split in two. Most change nothing a hook can show: a bound that cannot be reached (`end < 0` where the end is never 0), or a word's flag that
no rule reads. The real gaps left are `REPORT_WAIT_S` (row 1) and folders whose names end in `+`.

## Not settled

- **Glob refusals on old commands:** of 4,020 past commands the rule would still refuse, 2,013 really failed with "no matches
  found", so 97% of the 2,075 true catches stayed after the fixes, and 512 of the 2,370 that ran fine are no longer refused.
  The other 1,858 ran fine but their files have since changed, so a replay cannot tell if they are false refusals.
- **Waste:** 76% of agent turns hold one call and 23% of calls are small reads, but runs of 4 or more single reads occur in
  about 1% of agents, and repeats in about 1.5%. The nudge will stay rare. The ledger's `tool_turns` gives the baseline from now
  on, so a retro can show whether the start rule moves it.

## What past sub-agents complained of

Read from 206 FEEDBACK and 273 PROBLEMS MET sections, counted by keyword, so upper bounds. Of 755 problem bullets, the cause was the agent itself 308, a brief 108, a tool
83, another agent 65, a rule 41, the environment 24.

- **Acted on:** every session and agent now starts knowing the shell, the scratch folder and what stands in for a missing Grep (`hooks/context.py`), since 85 sections
  met a guard refusal and 43 of those named a glob. An agent is told when a fifth of its turns are left (`hooks/budget.py`), and to re-read shared files before an edit (`agents/worker.md`).
- **Tried and taken out:** a hook refusing a brief whose `Input:` path does not exist. Of 202 such paths in past briefs, agents met a missing file twice and used 166, which had
  therefore existed. It would catch almost nothing, so the wrong facts in briefs lie elsewhere. The sender's checklist in `harness:orchestrator` stays their only guard.
- **Left to the project:** style gates, gates red from other agents' work, GPU sharing.
- **Not fixable here:** the permission system refuses edits under `skills/**` even when the write set names them; the owner allows them.

## Fixed, with the number that showed it

- **The clock:** skills and templates still sized work in minutes, and a project's `AGENTS.md` keeps the copy `harness:init` wrote until someone edits it. Updating the plugin does not change those copies.
- **The audit froze the machine:** six jobs of eight threads on 24 cores reached a load of 162 and the machine had to restart. The tools now run 6 threads at low priority, and each bug stops at its first
  failing case: 60 bugs take 1:42 at a load of about 4, where 200 took over 12 minutes.
- **Lost reports:** a bad or unseen handback report was sent back to an agent that had already ended. 59 of 63 such blocks were
  never answered, and the ledger row and feedback were lost. The row and feedback are now always written.
- **Time budgets:** a clock punished slow machines and long tests. Budgets now count model turns, with defaults near each role's
  99th percentile: on past agents they would stop 4 of 626 workers and 1 of 154 scouts.
- **Unreadable budgets:** 157 past briefs said `Budget: N turns` and the hook ignored them. Turns are now the unit, and the brief
  rule refuses any other.
- **Handback past the budget:** refused 17 times across 10 agents.
- **`Budget:` line with more text after it:** ignored, so the default applied, on 351 of 453 readable budgets.
- **Glob rule:** it refused a glob an earlier step would create, a glob inside `bash -c`, and globs for people not on zsh.
- **Stop hook baseline:** a notification or a sub-agent's message moved the rule baseline, so real lessons were called missing.
- **Nudge:** it missed `cd x; cmd` and forgot reads after any command.
- **No cases:** `import_reports.py` and `replay.py` now have cases.
- **Stale mutants:** four pointed at code that no longer existed; `tests/mutants.py --check` now runs in pre-push and CI.
- **Pre-push hook:** it was not switched on in this clone, so one push ran no local checks.

## How to rerun

- `uv run python tests/plant_bugs.py --count 60 --seed 2`: plants random bugs in copies of the hooks and scores how many the
  cases catch. An audit, by hand, after a big hook change; no push or CI runs it. The same seed on the same code plants the same bugs. No bug is ever left in the repo.
- `uv run python tests/mutants.py`: the named bugs, which must all be caught.
- `uv run --script hooks/replay.py`: the always-on guard over past commands.
