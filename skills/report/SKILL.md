---
name: report
description: The report every sub-agent ends with - what was done, what is not proven, problems, what to do differently, feedback and a verdict written last. A hook sends back a report that breaks the form. Every role preloads it.
---

# The report

Your report is the main session's only view of your run. Keep it short and useful: say what was done and what is not
proven. A passing check gets one line; quote a command only when it failed or matters. `hooks/report_gate.py` sends back a
report that breaks the form, naming the sections that are wrong. A refused handback: call it again with the whole report,
fixed. A report sent back after you stopped: send only those sections again; the ones you leave out stay as they were.

## The form

Title, then these sections under their exact `##` headings, in this order. Leave out a section marked "if any" when it has
nothing to say, and add no other `##` heading. The report is at most 6000 characters outside fenced blocks; cut repeated
detail first, and move long lists to a file in the scratch folder and name it.

```markdown
# Report: <role>, <task in six words>
## Answer
<what was asked and what was done or found, in plain words, naming each file changed. Passing checks in one line;
a failing command quoted with its exit code>
## Not proven
- <what was not run or shown, and why>
## Problems
- <what happened> (cause: brief | tool | rule | environment | other agent | the agent itself). <what would have helped>
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
| Problems | If any | One cause from the list per item, and the words "would have helped" with what would have |
| Next time | If different | Left out when you would do the same |
| Open | If any | Includes a change needed outside your write set, with its file |
| Feedback | If any | Each item names a file to change; it goes to `harness-feedback/inbox.md` for a retro: the project's with `.harness.json`, else the plugin's data folder |
| Verdict | Always | Last. `done`, `partial` or `blocked`, then one sentence |

Write the Verdict after the rest and let it follow from it. If Not proven holds something the job needed, the word is
`partial`. An owner reads the Verdict first, so it must be true on its own.

## What the hook checks against your transcript

- Each file you changed through Edit, Write or NotebookEdit is named by its absolute or project-relative path, unless it
  lies under the project's scratch folder.
- A claim that tests, lint, a check, a gate or a build passed needs a Bash call of yours.
- Each `exit <N>` you write is the result of a Bash call: the code a failed call printed (`Exit code N`), 0 for a call
  that did not fail, or a code a call printed itself (`rg exit 1`, make's `Error 2`). Describing a code, write "exits with 2".
- A mark READ `` `path:line` ``, when you use one, names an existing file with at least that many lines, by its path from
  the project root or an end of path only one project file has; `path:a-b` checks `b`. A text quoted right after it, in "..." or backticks, must lie on that line or within 3 lines.

## Filling it

- Keep notes as you work: each retry, failed call and rule that pulled the other way; a report written from memory drops them.
- "The agent itself" is a cause, and the most useful one to admit. A mistake left out is the worse failure.
- Mark a claim that isn't obvious as READ, DERIVED or PROBED (`harness:evidence`), with `path:line` or the command.
