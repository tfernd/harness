---
name: report
description: The report every sub-agent ends with - the full form (ten sections, from Answer to FEEDBACK FOR THE ORCHESTRATOR) and the short form for scouts, runners and cold readers, with what each section needs. A hook sends back a report whose headings or section shapes are wrong. Every role preloads it.
---

# The report

Your report is the orchestrator's only view of your run, and how the next brief, role and skill get better. Fill the
form below in its order, each section under its exact `##` heading. "none" is allowed only in OUTSIDE, DECIDE, NOT
CHECKED and FEEDBACK FOR THE ORCHESTRATOR; every other section says what it checked or met. The hook
`hooks/report_gate.py` sends the report back when a heading is missing, repeated or out of order, or when a section
lacks its shape. A report sent back is sent again whole, not only the fix.

- **Short form:** scout, runner, cold-reader, analyst, planner and researcher: Answer, Work, NOT CHECKED, PROBLEMS MET, REPORT CARD.
- **Full form:** worker, reviewer and auditor.
- A project adds roles under `report.short` and `report.full` in `.harness.json`. Every other agent type, built-in ones too, owes the short form.

The hook also checks your report against your own transcript, and sends it back on a breach:

- Each file you changed through Edit, Write or NotebookEdit is named by its absolute or project-relative path, unless it
  lies under the project's scratch folder.
- Each `exit <N>` is the result of a Bash call of yours: the code a failed call printed (`Exit code N`), or 0 for a
  call that did not fail.
- READ `` `path:line` `` names an existing file with at least that many lines; a relative path is from the project root;
  `path:a-b` checks `b`. A text quoted right after it, in "..." or backticks, must lie on that line or within 3 lines.

## Filling it

- Keep notes as you work: each retry, failed call, and rule that pulled the other way; a report written from memory
  drops them.
- Mark each claim READ, DERIVED or PROBED, with `path:line` or the command and its exit code; an unmarked claim is
  not refused, but the orchestrator trusts it less.
- A writer opens Work with the files changed, one line each: the file, the function, what changed (advice, not checked).
- Score honestly: a low score fixes the next brief; a mistake or broken rule left out is the worse failure.

## The full form

```markdown
# Report: <role>, <task in six words>
## Answer
<one paragraph: what was asked and what was found or done>
## Work
- <what was done or found> (READ `path:line` | DERIVED | PROBED `<command>`, exit <code>)
## NOT CHECKED
- <what the answer does not cover, the cases that did not run, and why>
## OUTSIDE
- <a change needed outside the write set, with the file>
## DECIDE
- <each open choice>: <option>, <cost>; <option>, <cost>
## PROBLEMS MET
- <what happened> (cause: brief | tool | rule | environment | other agent | the agent itself); resolved: <how, or "not">
## COMPLIANCE
Gates: <gate> exit <code>; <others>, or "no gate applied"
- <file:line of the rule>: <broke | nearly broke>, <on purpose | not>, <what happened>; would have stopped it: <a hook,
  a gate, a brief line>
## LEARNED
- <a fact the next agent needs> (<path:line | version | command>)
## REPORT CARD
| Score | Value | Why |
| --- | --- | --- |
| Task | N/5 | <how much of the brief is done, with marked evidence> |
| Brief | N/5 | <5: nothing had to be guessed> |
| Ease | N/5 | <5: nothing was looked up twice, no tool fought back> |

**What would have helped:** <the input, fact or tool that would have saved a problem above>

**How I would do it again:** <the order of work you would choose now>
## FEEDBACK FOR THE ORCHESTRATOR
- <a change to a brief, a role, a skill, a hook or a gate that would have prevented a problem above, naming the
  file>, or "none"
```

## The short form

The same headings, fewer: `## Answer`, `## Work` (at most 10 findings, each marked READ, DERIVED or PROBED, or one line per
command run with its exit code; a longer list goes under Answer), `## NOT CHECKED`, `## PROBLEMS MET`, `## REPORT CARD` (the table and the two lines).

## What each section needs

- **PROBLEMS MET:** one list of everything that went wrong or got in the way, each with its cause; "the agent itself"
  is a cause, and the most useful to admit. With no problem, one line: `no problem met: <what ran clean>`.
- **COMPLIANCE:** the gates run with their exit codes first (or that no gate applied), then every rule broken or nearly
  broken.
- **FEEDBACK FOR THE ORCHESTRATOR:** only changes to a rule, role, skill, hook, gate or brief template, each naming the
  file and the problem it would have prevented; status and results go in Answer or Work. Each item lands in the
  project's `harness-feedback/inbox.md`, where a retro reads it. `none`, `N/A`, `No feedback.` and `None needed.` file nothing.
- **What else is filed:** each problem with a cause of brief, rule or tool, and a Task score of 3 or lower, marked `[auto]`
  (at most 5 a report). DECIDE and OUTSIDE stay in the report for the orchestrator.
