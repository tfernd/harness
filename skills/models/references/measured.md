# Measured facts

Measured, not documented. Samples are small, scores are the agents' own, and task difficulty is not controlled. Documented
facts and URLs are in `../SKILL.md`.

## Cold readers 

- A Haiku cold reader on a dry run over 3 plan items: 18 real gaps (11 major, 1 blocker) and 23 false claims.
- Later cold readers on Sonnet, forced to quote lines: 0 false of 43 claims re-checked (17, 14 and 12 over three jobs),
  with 2, 2 and 5 net-new major findings.
- Both the model and the quoting rule changed between the two runs, so neither alone explains the drop.
- The three gaps that mattered most in the dry run were found by reading code, so a reader's output is a hypothesis.

## Self-scores by model 

Command: `python3 bin/harness-import --ledger scratch/g4/ledger.jsonl` (160 reports with a report card, from one real multi-agent project), then `python3 -I references/by_model.py <ledger> <transcript root> <project>`, which reads each
agent's model from its `.meta.json`, else from the `model` field in its transcript. Scores are the agent's own Task,
Brief and Ease, 1 to 5. Audit grades were not in these reports. Groups under 10 reports are dropped (`harness:models`).

| Role | Model | Reports | Task | Brief | Ease | Reports saying "no problem met" |
|---|---|---|---|---|---|---|
| worker | haiku | 102 | 4.55 | 3.77 | 3.81 | 24 |
| scout | haiku | 14 | 4.07 | 3.93 | 3.50 | 4 |

- No Sonnet or Opus group reached 10 reports, so no comparison between models is claimed.
- Among Haiku workers' 102 reports the causes named most were `the agent itself` (84 mentions), `brief` (62) and
  `other agent` (42); a report can name several.
- Self-scores run high against the problems the same reports list; compare with audit grades (`harness:retro`) before
  trusting a score.
