# Accepting a unit and the closing status

## Accepting a unit

1. Read the diff of the files the brief names, new files included, and the report's Not proven and Problems. A change
   in any other file is sent back, not kept.
2. Future-reader test: would a fresh agent reading this cold find it easier or harder? Names say what a thing is, docs
   are true of the code under them. If harder, the unit goes back to its writer.
3. Run the gates of the unit's tier (`harness:workflows`). Rerun the worker's Judge only when its report is the sole
   evidence of a claim. After a review, rerun each finding's command, drop a finding whose output does not show its
   stated cause, and brief workers for the rest. A gate that could not run is accepted only as "not run" and listed.
4. A new module is wired where the project registers modules.
5. Update the plan: the unit's row leaves "Next", a decision it settled is recorded, a line it made false is removed.
6. Write the commit proposal (`harness:git`) before the next unit starts.

## The closing status

The Stop hook (`hooks/turn.py`) asks for it at the end of a turn that ran several agents or edits, once no background
agent is still running. Never write it before the hook asks: a turn that ends while agents run gets a progress note of
a few lines, and a quick answer gets nothing.

Short lines, no tables, under these `##` headings in this order. The hook holds the turn for the required ones and
notes an agent missing from `## Agents`.

| Heading | When | Holds |
|---|---|---|
| `## Verdict` | Always | Done, partial or blocked, and the one thing that matters most |
| `## Done` | Always | One line per ask since the last status: the ask, done, partly or failed, and its evidence (a command with its exit code, or a file) |
| `## Agents` | The turn ran agents | One line per agent: the description it was given, its verdict, and what happened to its problems (fixed in FILE, rejected: why, or none) |
| `## Decisions` | If any | A choice made for the owner, with its reason, so they can overrule it |
| `## Needs you` | Always | What only the owner can do, each with what happens if they do nothing; "nothing" when empty |
| `## Not proven` | If any | What was skipped or only read. A problem not resolved carries to the next status |
| `## Next` | Always | The one thing to do next, with its cost |

Say what a thing does before its jargon. Report a failure or a bent rule as plainly as a success. A number is a signed
percent against a named baseline, with its command.
