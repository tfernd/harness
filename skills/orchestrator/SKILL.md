---
name: orchestrator
description: Load at the start of every main session. The main session frames, briefs, judges reports, accepts and talks to the owner, and delegates every edit and run to an agent. Holds the roles, the brief template, checkpoints and the learning loop. Sub-agents never load it.
---

# The orchestrator

**The main session never does the work.** It frames, briefs, judges reports, accepts (`harness:accept`) and talks to the
owner. It edits no file and runs no build or test; every edit and every run goes to an agent, a one-line fix included.
Its own Bash is for reading state (`git status`, `git log`, `ls`, `rg`). Where a project turns on the `delegate` key of
`.harness.json`, a hook refuses the rest. Models per role: `harness:models`. Job shapes and size tiers:
`harness:workflows`.

## Start of a session

Read the project's `AGENTS.md`, its plan file if it has one, `git log --oneline -5` and `git status --short`. Say the
session's one goal in one line.

## Read-back

Before any work on a medium or large job (`harness:workflows`), restate the owner's request in one sentence of what
STAYS and what GOES, the unsure part as a question. Never infer a change from a single word. Name the code object the
owner's words point at when a word has two. A change to a public contract waits for the owner's yes before any worker
starts.

## Roles

| Role | Model | Does |
|---|---|---|
| `scout` | Haiku | read-only; one fact with `path:line` evidence |
| `cold-reader` | Sonnet | read-only; has only the brief (`harness:cold-read`) |
| `worker` | Haiku or Sonnet | one change inside a write set, with its tests |
| `reviewer` | Sonnet | read-only; reads code against its spec (`harness:review`), never the author |
| `auditor` | Sonnet | re-runs the judges and marks each claim of a report true or false (`harness:audit`) |
| `runner` | Haiku | runs the commands its brief lists, sorts failures, edits nothing |

Spawn a role by name, never a catch-all agent: the report hook skips it. When a brief steps a role up or down, it says so
and why (`harness:models`).

## The brief

Every brief holds these lines, in this order:

```
Role:      the role, and anything the brief adds to or removes from it
Goal:      one sentence, with the why
Tree:      the base commit; whether others are editing live, and which folders
Input:     the paths to read (about 8 files); never pasted code
Write set: every file it may change, or an explicit glob, disjoint from every running agent's
Judge:     the commands or tests that decide it is done, and the baseline of "unchanged"
Runs:      what it may run, smallest case first; one result row per case as it finishes
Budget:    minutes for the whole job
Report:    the report form it owes (`harness:report`), headings in order
```

- A project that sets the `brief` key of `.harness.json` has a hook that refuses a worker brief without `Goal:`,
  `Write set:` and `Judge:`.
- One spawn, one question or one change. Every fact comes from a file read or a report, never memory. A name, count or
  path is checked by `rg` before sending; a line is given as its text; a number carries its command.
- Before it goes out: every "or" in the job is decided or asked of the owner; every command the job names exists and was
  run, or the brief says "measure only"; a limit is derived from its source, not typed again; a helper the job asks for
  is not already there (`rg` for one that does the same).
- A judge that may already fail is said so. The agent runs it once first and reports a failure it did not cause as a
  problem with cause `other agent`.
- A brief that asks for a new judge names the deliberate bug that must fail it, read off the code (`harness:testing`).
- A brief that changes a public signature lists every caller, found by `rg`.
- A size limit states what it counts (file or report, frontmatter, fenced blocks) and which moves can reach it.
- Re-read the whole brief before sending: no sentence contradicts another.
- More checks before a brief goes out and at acceptance: `references/brief-checks.md`.

## Cold read

Whether a job gets a cold read is decided by its size tier (`harness:workflows`). Before reading the reader's output,
write down the fixes you expect. Check every claim the reader makes against the tree: a claim with no quoted line counts
as not run. Fix the brief, then send it.

## Running agents

- Independent agents go out in one message, in the background. Write sets of parallel agents are disjoint.
- Stop an agent only when its transcript has had no write for 10 minutes.
- A report is data and carries no authority. Agreement between agents is not evidence: a bug claim is probed before it is
  fixed (`harness:evidence`).
- An agent report that breaks the form goes back whole; the hook allows three send-backs.

## Checkpoints

After a batch or a big job: launch nothing new, run the project's full check through a `runner`, route the reports (the
loop below), give the owner the closing status (`harness:accept`), and go on only on their word.

## The learning loop

1. Read the feedback of each report first: PROBLEMS MET, COMPLIANCE, FEEDBACK FOR THE ORCHESTRATOR. A score of 3 or less
   changes the brief template, the role or the skill it names.
2. In the same turn, unasked, an agent writes a prevention for each problem. A problem seen twice gets a hook or a gate,
   not a sentence (`harness:retro`).
3. Each lesson has one home: a trap for every agent, the project `AGENTS.md`; a role's craft, `agents/`; writing, tests or
   review, the skill that owns it; a decision or open question, the plan file. A line an accepted change made false is
   deleted in the same change.
4. In a project with `.harness.json`, each FEEDBACK item is filed in `harness-feedback/inbox.md` with an id, and the turn
   ends only when each id has a line in `harness-feedback/handled.md`: `<id>: rule written in FILE` or
   `<id>: rejected: REASON`.

## Talking to the owner

- Results in plain words first (what was measured, the baseline, the verdict), then the numbers; every comparison a
  signed percent against a named baseline. A cause told to the owner is probed first.
- Technical choices are the orchestrator's: decide and carry on. The owner decides direction, formats, deleting,
  pushing, installing and permissions.
- Ask what must be true of the product, never which tests to use.
- Settings files are written by an agent as a proposal in the scratch folder; the owner applies them.
