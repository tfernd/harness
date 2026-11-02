# Auto-compaction settings under test

A record of what was set and when, so a later run of `bin/compaction-report` can say whether the change really saved money.

| Set on | Opus 5.5 | Sonnet 5.5 | Haiku 5.5 |
|---|---|---|---|
| Before 2026-11-02 | 400k | 700k | 500k |
| 2026-11-02 | 250k | 250k | 100k |

Haiku was asked for at 90k, just under the 100k price step, but the documented minimum of `autoCompactWindow` is 100k and the
docs don't say what a lower value does.

Effort also changed around the same time, from low to medium on Opus and Sonnet, and Haiku now sets medium. Higher effort costs more per
call on its own, so it can hide or fake a saving: compare calls at the same effort where possible.

## What the replay predicted (2026-11-02)

Against the real cost of past sessions, at list price, main sessions only.

| Model | Best threshold | Change |
|---|---|---|
| Opus 5.5 | 200k, flat to 250k | -22.1% |
| Sonnet 5.5 | 250k | -14.0% |
| Haiku 5.5 | 90k | -36.0% |

All models at one threshold: 150k gave -35.8% and 200k gave -35.6%. These predictions don't price rework after a compaction.

## The test

Due 2026-11-09, or after enough long sessions at the new settings.

1. Run the report on sessions since the change, and on the same span before it, with `--since` and `--until`.
2. Compare the real cost per call and per long session, by model, not the replay's prediction.
3. Look for rework: more reads and edits right after a compaction than before the change.
4. Say whether to keep, raise or lower each level, and add a row to the table above.

Different work between the two spans can explain a difference, so report the sample sizes and treat a small change as no change.
