# Findings

What testing the harness against real use found, and what is still open. Measured over the owner's past sessions (about
2,300 agent transcripts and 110 main sessions) unless marked read. A row leaves "Open" when it is fixed and has a case.

## Open

| # | Problem | Evidence | Next |
|---|---|---|---|
| 1 | The fix for lost handback reports is not proven live | headless runs report by text, so only the desktop app shows a handback; cases cover the logic, and no case can write a transcript late, so `REPORT_WAIT_S` is undefended | After a push, count ledger rows against agents in a real session |
| 2 | Planted bugs still uncaught | see Score | Read each survivor; write a case or show it changes nothing |

## Score

Planted bugs caught by the cases, `tests/plant_bugs.py --count 200 --seed 1`: **172 of 200, 86%**. By hook: `brief_lint` 5/5,
`budget` 13/13, `common` 7/7, `nudge` 5/5, `skill_gate` 9/9, `turn` 24/26, `guard` 45/51, `import_reports` 5/7, `report_gate` 25/32,
`shell` 29/38, `context` 2/3, `delegate` 3/4. Measured before the last review's small fixes. Before this round's new cases the same code scored 84%. Finish line: 95%, with each remaining survivor read
and shown to change nothing. `shell` is the weakest.

## Not settled

- **Glob refusals on old commands:** of 4,020 past commands the rule would still refuse, 2,013 really failed with "no matches
  found", so 97% of the 2,075 true catches stayed after the fixes, and 512 of the 2,370 that ran fine are no longer refused.
  The other 1,858 ran fine but their files have since changed, so a replay cannot tell if they are false refusals.
- **Waste:** 76% of agent turns hold one call and 23% of calls are small reads, but runs of 4 or more single reads occur in
  about 1% of agents, and repeats in about 1.5%. The nudge will stay rare. The ledger's `tool_turns` gives the baseline from now
  on, so a retro can show whether the start rule moves it.

## Fixed, with the number that showed it

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

- `uv run python tests/plant_bugs.py --count 200 --seed 1`: plants random bugs in copies of the hooks and scores how many the
  cases catch. The same seed on the same code plants the same bugs. No bug is ever left in the repo.
- `uv run python tests/mutants.py`: the named bugs, which must all be caught.
- `uv run --script hooks/replay.py`: the always-on guard over past commands.
