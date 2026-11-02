# Findings

What testing the harness against real use found, and what is still open. Measured over the owner's past sessions (about
2,300 agent transcripts and 110 main sessions) unless marked read. A row leaves this file when it is fixed and has a case.

## Open

| # | Problem | Evidence | Fix |
|---|---|---|---|
| 1 | The report gate sends back a handback report it cannot see. The agent has already ended, so the send-back is lost, and so are the ledger row and the feedback | 59 of 63 blocks after a handback were never resumed; 50 blocks said every heading was missing; the same report passes those heading checks on a later replay | Read `last_assistant_message` or the handback, wait for the transcript, and always write the row. Cause not proven: a live run used text, not a handback |
| 2 | The glob rule refuses a glob whose files an earlier step of the same command makes | `touch scratch/a.py; ls scratch/a*` and `gen && cat out/*.txt` are refused | Do not judge a path glob after a step that may write |
| 3 | The glob rule applies zsh's rule inside `bash -c`, where a glob with no match stays literal | `bash -c 'ls *.nothing'` is refused | Do not judge a glob inside a non-zsh shell's string |
| 4 | The glob rule assumes zsh for everyone, in a public plugin | read: no check of `$SHELL` in `hooks/guard.py` | Judge failing globs only when the shell is zsh |
| 5 | The nudge misses `cd x; cmd`, so its runs and repeats undercount | 7,394 of 19,874 one-call Bash calls start with `cd`; the rule unwraps only `cd x && cmd` | Unwrap both, then measure again |
| 6 | The nudge almost never fires | due in 11 of 2,305 agents; runs of 6 single small reads are rare | Decide its triggers from the numbers after 5 |
| 7 | A budget the hook cannot read is silently replaced by the default | 157 past briefs say `Budget: N turns` | Move to turn budgets, and have the brief check refuse an unreadable line |
| 8 | A time budget punishes a slow machine or a long test | owner's report; read: the clock starts at the brief | Count model turns in `hooks/budget.py` |
| 9 | `import_reports.py` and `replay.py` have no hook cases | no mention in `tests/run_cases.py` | Add cases for the import row |
| 10 | The Stop hook's lesson check can misjudge a turn in which `.harness.json` first appears | seen once: `AGENTS.md` had changed, the check said no rule file had | Take the baseline when the file first appears |

## Score

Planted bugs caught by the cases, `tests/plant_bugs.py --count 200 --seed 1`: **169 of 200, 84%**. By hook: `brief_lint` 4/4,
`context` 5/5, `delegate` 3/3, `report_gate` 28/32, `shell` 33/38, `budget` 10/11, `common` 7/8, `skill_gate` 8/9, `turn` 24/28,
`nudge` 10/13, `guard` 37/49. Finish line: 95% on the same seed, with each remaining survivor read and shown to change nothing.

Uncaught bugs worth a case first, since a wrong guard rule costs every project:

- `guard.py:643`, the poll rule: nothing checks that a loop without `sleep` passes.
- `guard.py:528` and `:450`, in-place edits: nothing checks that a plain `sed` passes.
- `guard.py:303`, denied `uv` commands, and `:609`, the lock's free variable.
- `guard.py:514`, `tar` write modes, and `:567` and `:571`, reading a `cd` target.
- `turn.py:141` to `:163`, which calls count as agents and background runs.
- `skill_gate.py:78` and `report_gate.py:409`, the scratch exemption.

Some survivors probably change nothing, such as `nudge.py:134` and `turn.py:318`. Read each before writing a case.

## Not settled

- **Glob refusals on old commands:** of 4,622 past commands the rule would refuse today, 2,075 really failed with "no matches
  found", so the rule is right on those. Another 2,370 ran fine, and today's files differ, so that count mixes findings 2 and
  3 with stale replays. Measure again after those fixes.
- **Waste:** 76% of agent turns hold one call and 23% of calls are small reads, but exact repeats are rare. Many one-call turns
  need the previous result, so the real saving is unknown. The ledger's `tool_turns` gives the baseline from now on.

## Fixed, with the number that showed it

- A handback past the budget was refused: 17 refusals across 10 agents.
- A `Budget:` line with more text after it was ignored, so the default applied: 351 of 453 readable budgets.
- Four mutants pointed at code that no longer existed; `tests/mutants.py --check` now runs in pre-push and CI.
- The pre-push hook was not switched on in this clone, so one push ran no local checks.

## How to rerun

- `uv run python tests/plant_bugs.py --count 200 --seed 1`: plants random bugs in copies of the hooks and scores how many the
  cases catch. The same seed plants the same bugs. No bug is ever left in the repo.
- `uv run python tests/mutants.py`: the named bugs, which must all be caught.
- `uv run --script hooks/replay.py`: the always-on guard over past commands.
