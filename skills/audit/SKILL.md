---
name: audit
description: How an auditor tests another agent's report - re-runs its judges, marks each claim true or false with evidence, and grades the author's Task score. Load when you are the auditor, or when you judge an audit.
---

# Audit

Review reads the code (`harness:review`); an audit tests the **report**. The auditor takes an author's report, the
brief it answered and the tree, and finds out which claims hold. It edits nothing and does not fix; it runs.

## Steps

1. **Collect the claims.** List each claim of the report: every Work line, every gate result, every "not changed", every
   file named. Include what the report leaves out: files changed that it does not name (`git status` and `git diff
   --stat` are reading; the project may share a tree with other agents, so attribute only what the report's write set
   allows).
2. **Re-run the judges.** Run the brief's Judge commands yourself, once each, as the brief wrote them. Compare with the
   exit codes and counts the report quotes. Smallest case first; follow the project's rules for shared resources.
3. **Mark each claim** TRUE or FALSE, with evidence in the marks of `harness:evidence`: READ `path:line` with the
   quoted line, or PROBED with the command and exit code. A claim you cannot settle is UNSETTLED with the reason; it
   never counts as true.
4. **Check the write set.** Every changed file is inside the brief's write set; anything else is a breach and is listed.
5. **Check the report's honesty:** NOT CHECKED holds what really was not run; PROBLEMS MET holds the retries and failures
   visible in the evidence; the card scores follow from what you found.
6. **Grade.**

## The grade

Grade the author's **Task** score: the value it gave itself for how much of the brief is done.

| Grade | Meaning |
| --- | --- |
| 5 | Done and every claim true; judges pass when you rerun them |
| 4 | Done; a claim wrong in a way that does not change the result |
| 3 | A required part missing or a judge failing; the report said so |
| 2 | A required part missing or failing that the report did not say |
| 1 | Most of the brief not done, or the report mostly false |

The grade is the auditor's honest reading, not a repeat of the self-score. A false claim of success caps the grade at 2.

## The report

The full form of `harness:report`. Work holds, in this order:

- One line, exactly `Grade: N/5 for <role> <unit>`, where `<unit>` is the exact task text of the author's
  `# Report: <role>, <task>` title. Nothing follows it on the line. `harness:retro` and its `references/queries.md`
  join on that text, so its shape is fixed.
- On its own next line, the author's self-score: `Author's Task score: M/5`.
- Claims, one line each: TRUE, FALSE or UNSETTLED, the claim in a few words, the evidence.
- Judges re-run: the command, the exit code, the counts.
- Write-set breaches and unreported changes.

NOT CHECKED holds each claim and judge you could not settle, and why.

## Rules

- Do not rely on the author's output as evidence of itself; run it again or read the code.
- Never fix. A broken thing found is a finding for the orchestrator.
- A judge that passes for a reason unrelated to the change (it never touches the changed code) is reported: the
  claim "tests pass" is true but says nothing (`harness:testing`).
