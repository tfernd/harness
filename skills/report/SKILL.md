---
name: report
description: The report every sub-agent ends with - what was done, what is not proven, problems, what to do differently, feedback and a verdict written last. A hook sends back a report that breaks the form. Preloaded by every role; load it yourself before writing a report.
---

# The report

Your report is the main session's only view of your run. Keep it short and useful: say what was done and what is not
proven. A passing check gets one line; quote a command only when it failed or matters. `hooks/report_gate.py` checks one
thing: the required sections are there, as `##` headings in order. It sends back a report that misses or misorders one,
naming the sections that are wrong. A refused handback: call it again with the whole report,
fixed. A report sent back after you stopped: send only those sections again; the ones you leave out stay as they were.

## The form

Title, then these sections under their exact `##` headings, in this order. Leave out a section marked "if any" when it has
nothing to say, and add no other `##` heading. A long list belongs in a file in `/tmp/harness/<project>/`, named in the report.

```markdown
# Report: <role>, <task in six words>
## Answer
<what was asked and what was done or found, in plain words, naming each file changed. Passing checks in one line;
a failing command quoted with its exit code>
## Not proven
- <what was not run or shown, and why>
## Problems
- <what happened> (cause: brief | tool | rule | environment | other agent | the agent itself)
## Next time
<what you would do differently on the same job>
## Open
- <a choice only the owner can make>: <option>, <cost>; <option>, <cost>
## Feedback
- <file to change>: <the change, and the problem it would have prevented>
## Verdict
<done | partial | blocked>: <one sentence that fits everything above>
```

| Section | When | Rule |
|---|---|---|
| Answer | Always | States what happened, not how good it is; the judgement waits for Verdict |
| Not proven | Always | Never bare: "nothing" needs its reason |
| Problems | If any | One cause from the list per item |
| Next time | If different | Left out when you would do the same |
| Open | If any | Includes a change needed in a file your brief does not name, with its file |
| Feedback | If any | Each item names a file to change; the main session reads it in the same turn and acts |
| Verdict | Always | Last. `done`, `partial` or `blocked`, then one sentence |

A claim that something could not be done needs the quoted error of a real attempt; otherwise write
`not attempted: <why>`, never "can't". A restriction is a conclusion earned from a real failure.

Write the Verdict after the rest and let it follow from it. `done` means every Judge line of the brief is met;
`partial` means a named Judge line is unmet; `blocked` means the job could not go on. Not proven may list limits (a run
left to the main session, a path not exercised) without making the verdict `partial`. An owner reads the Verdict first, so it must be true on its own.

## Filling it

- Send the report only after every background job you started has ended or been stopped; a stray job wakes you again after
  the report. A job still needed is stopped and listed under Not proven with the command to rerun it.

- Keep notes as you work: each retry, failed call and rule that pulled the other way; a report written from memory drops them.
- "The agent itself" is a cause, and the most useful one to admit. A mistake left out is the worse failure.
- Writing tics to avoid, each with a plain form: `references/prose.md`.
- Mark a claim that isn't obvious as READ, DERIVED or PROBED (`harness:evidence`), with `path:line` or the command.
