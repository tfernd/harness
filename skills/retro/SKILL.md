---
name: retro
description: Turns the ledger of past agent reports into rule changes - groups problems by cause, role and brief, compares verdicts with audit grades, proposes a hook or gate for a problem seen twice. Load for a retrospective, after a big job, or when the same problem comes back.
---

# Retro

A retro reads facts from the ledger and ends with changes to a rule, hook, gate, brief template or role. A lesson that
stays a sentence is not a result.

## The checkpoint

A retro is due when 10 or more items wait in `__harness__/feedback/inbox.md` past the count in `__harness__/feedback/retro-mark`,
or the oldest waiting item is 3 or more days old. The number of agents a session ran triggers nothing. The Stop hook files
each bullet under the main session's closing `Lessons` heading into the inbox (`agent=main`), once per bullet. SessionStart
and the Stop hold tell the main session to launch `harness:analyst` in the background; the hold fires for any session, once
per turn, at the end of a turn with no agent running, never in a sub-agent. The owner saying "skip retro" silences it for
that session. Apply or reject each proposal; keep its open problems in
`__harness__/feedback/open.md`, one `- <role or all>: <problem>` per line, and delete a line once a rule fixes it. Then add the
line per waiting item id to `__harness__/feedback/handled.md`, the ids the hold lists: `<id>: rule written in FILE` (FILE is a rule
file changed this turn), `<id>: fixed in FILE` or `<id>: covered by FILE` (FILE exists inside the project or the plugin; a path
that resolves elsewhere, `..` or `/etc/hostname` included, fails), or `<id>: rejected: REASON` of 3 or more words that no other line uses.
A `retro-<N>:` line closes nothing, and neither does `filed` or `applied: open.md`: open.md keeps a problem in front of agents, it
does not settle the item, so an item whose problem no rule fixes yet is rejected with the reason and the problem goes to open.md. The hold names each line it ignores,
with the reason. The hold clears when every waiting item has its own line. The hook moves the mark only then; with no
mark yet, the window is every inbox item `handled.md` does not close. Write these files with Write or Edit, not the shell. The folder is ignored by git, so `rg` and Glob skip it: read the files by path.
`retro-mark` (in the project's `__harness__/feedback/`) and `retro-marker` (in the plugin data folder, touched in the last
step) are different files.

## The ledger

`ledger.jsonl` in the plugin's data folder (`$CLAUDE_PLUGIN_DATA`; `~/.cache/harness` when unset). One JSON row per
stopped agent, written by `hooks/report_gate.py`; past reports come in through `bin/harness-import` (rows carry
`"imported": true`, `accepted` true and `send_backs` 0, so they say nothing about the gate).

Fields: `time`, `project`, `session`, `agent_id`, `role`, `accepted`, `send_backs`, `open_problems`, `verdict`
(`done`, `partial` or `blocked`, null on an old row), `causes`, `feedback_ids`, `tool_turns` (`turns`, `calls`,
`one_call_turns`, `longest_small_run`, `small_reads`, `repeats`), `report` (full text). Read rows with `uv run python`; `references/queries.md` holds the queries.

## Steps

1. **Scope.** Pick a project and a window (a session, or the rows since the last retro). Keep the last row per `agent_id` (a sent-back report is written again). Say the row count. Drop rows
   with `imported` unless the question is about past reports; keep them apart from live rows.
2. **Group by cause.** Count `causes` per cause, then per role, then per brief (the brief is the task named in the
   report's first line, `# Report: <role>, <task>`). A cause named once is a note; twice is a pattern.
3. **Read the reports behind a pattern.** Open the `report` text of at least two rows per pattern. A count with no
   quoted problem line is not a finding.
4. **Compare verdicts.** An auditor's report holds one line, for example `Grade: 3/5 for worker fix the parser`, where the unit
   is the exact task text of the author's `# Report: <role>, <task>` title. A role whose `done` gets a grade of 3 or less twice is
   overrating its work: the fix is a stricter judge or report line, not a reminder. Units with no grade are listed as unaudited.
5. **Check the send-backs.** `open_problems` is filled only when the gate stops sending back (the cap), so read it only
   on rows with `accepted` false; a row with `send_backs` above 0 and `accepted` true names no rule. A
   report rule failed twice is a rule agents cannot read: rewrite it in `harness:report` or give the gate a clearer message.
6. **Check the tool turns.** Per role, from `tool_turns`: calls per turn, repeats per agent and the share of calls that are
   small reads, each beside the last retro's value. One-call turns alone prove nothing, since many need the previous
   result. A figure that got worse is a pattern; read two of its transcripts.
7. **Check the rules.** In the project's `AGENTS.md`, each rule has an enforcer in its rule-to-enforcer table (hook, test,
   lint, review or none). A rule broken again whose enforcer is none is a repeat: raise it a level in the same change. A
   rule whose mistake can no longer happen is dropped.
8. **Find no-ops and bloat.** Steering lines that change no behaviour (no row, no reviewer finding, no hook ever tied to
   them) and an `AGENTS.md` that grew since the last retro: propose deleting them. A line kept must earn its place.
9. **Propose changes.** One per pattern, in the form below.

## Proposal form

```
Pattern: <cause>, <role>, <n> rows (ids)
Evidence: <quoted problem line> (<agent_id>)
Level: <cause removed | types or lint | hook or test | text>, and why a higher one did not work
Change: <hook | gate | rule | brief template | role | skill> in <file>
Check: <how the same problem is caught next time, and how to show the check fails under a deliberate bug>
```

## Which kind of change

Pick the highest level that fits, and say why a higher one did not work:

1. Remove the cause: one owner for the fact, and delete the old way an agent would copy.
2. Types or lint: make the mistake unrepresentable or a tool failure.
3. A hook or a test.
4. Text, last, and only for judgement calls no tool can check.

- A problem seen twice gets a hook or a gate: something that refuses, not a sentence an agent may skip. Waste that is
  sometimes right, such as tool turns, gets a nudge and a figure in the ledger, not a refusal (`hooks/nudge.py`). A hook
  needs cases in `tests/run_cases.py` (in the plugin repo, not the project), shown to fail under a deliberate bug.
- A rule is for what a tool cannot check; it must be checkable by a reviewer against code or a report.
- A brief-caused problem changes the brief template or `harness:cold-read`, not the agent.
- Missing information (the agent could not see a log, a service or a file outside its tree; filed as `environment`) is
  fixed by access, a path in the brief or a tool, not by a rule.
- An `environment` or `tool` cause gets no rule unless it was seen twice; then it is the project's: report it, do not
  write a plugin rule for it.
- `the agent itself` repeated across one role is a role or model question: see `harness:models`.

## Limits

- A Verdict is the agent's opinion. Never let it stand alone; use it only beside an audit grade or a problem line.
- Causes are what the agent chose; check one against the problem text before counting it.
- Do not edit the ledger. Do not rerun `bin/harness-import` without `--dry-run` first: it appends.
- A retro writes proposals and the files they name; the owner accepts them.
- Last step: touch `${CLAUDE_PLUGIN_DATA}/retro-marker` (else `~/.cache/harness/retro-marker`), so the SessionStart "N reports since the last retro" line clears.
