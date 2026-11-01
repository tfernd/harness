---
name: retro
description: Turns the ledger of past agent reports into rule changes - groups problems by cause, role and brief, compares self-scores with audit grades, proposes a hook or gate for a problem seen twice. Load for a retrospective, after a big job, or when the same problem comes back.
---

# Retro

A retro reads facts from the ledger and ends with changes to a rule, hook, gate, brief template or role. A lesson that
stays a sentence is not a result.

## The ledger

`ledger.jsonl` in the plugin's data folder (`$CLAUDE_PLUGIN_DATA`; `~/.cache/harness` when unset). One JSON row per
stopped agent, written by `hooks/report_gate.py`; past reports come in through `bin/harness-import` (rows carry
`"imported": true`, `accepted` true and `send_backs` 0, so they say nothing about the gate).

Fields: `time`, `project`, `session`, `agent_id`, `role`, `accepted`, `send_backs`, `open_problems`, `scores`
(`Task`, `Brief`, `Ease`, each `"N/5"` or a bare digit, null when unreadable), `causes`, `feedback_ids`, `report` (full
text). Read rows with `uv run python`; `references/queries.md` holds the queries.

## Steps

1. **Scope.** Pick a project and a window (a session, or the rows since the last retro). Say the row count. Drop rows
   with `imported` unless the question is about past reports; keep them apart from live rows.
2. **Group by cause.** Count `causes` per cause, then per role, then per brief (the brief is the task named in the
   report's first line, `# Report: <role>, <task>`). A cause named once is a note; twice is a pattern.
3. **Read the reports behind a pattern.** Open the `report` text of at least two rows per pattern. A count with no
   quoted problem line is not a finding.
4. **Compare scores.** An auditor's report holds one line in Work, for example `Grade: 3/5 for worker fix the
   parser`, where the unit is the exact task text of the author's `# Report: <role>, <task>` title. Set that
   audit grade beside the role's self `Task` score for the same unit and report the gap per role. A role whose
   self-score exceeds its audit grade by 1 or more twice is overrating its work: the fix is a stricter judge or report
   line, not a reminder. Units with no audit grade are listed as unaudited, never scored.
5. **Check the send-backs.** `open_problems` is filled only when the gate stops sending back (the cap), so read it only
   on rows with `accepted` false; a row with `send_backs` above 0 and `accepted` true names no rule. A
   report rule failed twice is a rule agents cannot read: rewrite it in `harness:report` or give the gate a clearer message.
6. **Propose changes.** One per pattern, in the form below.
7. **Model evidence.** Update `harness:models` measured facts only from the same query output, with sample sizes.

## Proposal form

```
Pattern: <cause>, <role>, <n> rows (ids)
Evidence: <quoted problem line> (<agent_id>)
Change: <hook | gate | rule | brief template | role | skill> in <file>
Check: <how the same problem is caught next time, and how to show the check fails under a deliberate bug>
```

## Which kind of change

- A problem seen twice gets a hook or a gate: something that refuses, not a sentence an agent may skip. A hook
  needs cases in `tests/run_cases.py` (in the plugin repo, not the project), shown to fail under a deliberate bug.
- A rule is for what a tool cannot check; it must be checkable by a reviewer against code or a report.
- A brief-caused problem changes the brief template or `harness:cold-read`, not the agent.
- An `environment` or `tool` cause gets no rule unless it was seen twice; then it is the project's: report it, do not
  write a plugin rule for it.
- `the agent itself` repeated across one role is a role or model question: see `harness:models`.

## Limits

- Self-scores are the agent's opinion. Never let them stand alone; use them only beside an audit grade or a problem line.
- Causes are what the agent chose; check one against the problem text before counting it.
- Do not edit the ledger. Do not rerun `bin/harness-import` without `--dry-run` first: it appends.
- A retro writes proposals and the files they name; the owner accepts them.
- Last step: touch `${CLAUDE_PLUGIN_DATA}/retro-marker` (else `~/.cache/harness/retro-marker`), so the SessionStart "N reports since the last retro" line clears.
