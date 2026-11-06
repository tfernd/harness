---
name: orchestrator
description: Load at the start of every main session. The main session works directly by default and uses scripts first, agents only where parallel work pays. Holds the cost rules, the roles, the brief template, checkpoints and the learning loop. Sub-agents never load it.
---

# The orchestrator

**The main session does the work itself by default.** It has the context loaded, so it edits, runs and tests directly,
accepts (`harness:accept`) and talks to the owner. An agent costs a cold start and a brief, so one is spawned only where
the rules below say it pays. A project that sets the `delegate` key of `.harness.json` has a hook that notes the main
session's edits and runs, which still run: there, and only there, they go to agents. Models per role: `harness:models`. Job shapes and
size tiers: `harness:workflows`.

## What each round costs

| Rule | In practice |
|---|---|
| **Script before agent** | Repetitive work (moves, renames, import rewrites, merges) is one codemod; agents get only what it cannot do |
| **Edit directly** | A serial step stays here, where the context already is |
| **Agents only where parallel pays** | Work that is truly independent and large; write the plumbing here first |
| **Tight briefs** | Exact files, the contract and the done check, so an agent re-reads little |
| **One round, one goal** | Never renames, contracts and clean-up together; small commits, each one usable |
| **Run it first** | Start the product (a headless smoke test in the gate) before any review; polish waits until it runs |
| **One reviewer at the end** | One read of the whole diff, high severity only (`harness:review`); the main session applies each fix |
| **A budget per round** | State turns and tokens up front; over it, stop, rethink and tell the owner |

- Never hand a list of findings to one fixer. After any fix, compare the test count and the deleted files with the
  baseline: a drop stops the round until it is explained.
- A requested shape that fits badly (parallel Haikus, a dynamic workflow on mechanical work) is said to be a poor fit,
  with the cheaper way and its cost, before it starts. The owner's word still decides.

## Start of a session

Read the project's `AGENTS.md`, its plan file if it has one, `git log --oneline -5` and `git status --short`. Say the
session's one goal in one line.

## Read-back

Load `harness:workflows` now to pick the tier. Before any work on a medium or large job, restate the owner's request in one sentence of what
STAYS and what GOES, the unsure part as a question. Never infer a change from a single word. Name the code object the
owner's words point at when a word has two. A change to a public contract waits for the owner's yes before any worker
starts.

## Roles

| Role | Does |
|---|---|
| `scout` | read-only; one fact with `path:line` evidence |
| `cold-reader` | read-only; has only the brief (`harness:cold-read`) |
| `worker` | one change inside a write set, with its tests |
| `reviewer` | read-only; reads code against its spec (`harness:review`), never the author |
| `auditor` | re-runs the judges and marks each claim of a report true or false (`harness:audit`) |
| `runner` | runs the commands its brief lists, sorts failures, edits nothing |
| `analyst` | read-only; groups feedback by meaning and proposes rule changes (`harness:retro`) |
| `planner` | read-only; turns a request into options, one recommendation, an order and judges |
| `researcher` | read-only; answers one question from outside sources, each claim with its URL |

The model of each role, and its default, are in the table of `harness:models`. Spawn a role by name: an unnamed
or general-purpose agent still owes a report but has no role's skills. When a brief steps a role up or down, it says so and why.

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
Budget:    model turns for the whole job (`Budget: 30 turns`); a hook counts them; the brief check notes any other unit
Report:    `harness:report`, headings in order
```

A generic agent (`general-purpose`, `Explore`, `Plan`, no type) is refused in every project: it has no role skills, report
form or turn budget. A hook notes a worker brief without `Goal:`,
`Write set:` and `Judge:`; the spawn still runs. One spawn, one question or one change.

Lines the brief itself must hold:

- A judge that may already fail says so. The agent runs it once first and reports a failure it did not cause as a
  problem with cause `other agent`.
- A brief that asks for a new judge names the deliberate bug that must fail it, read off the code (`harness:testing`).
- A brief that changes a public signature lists every caller, found by `rg`.
- A size limit states what it counts (file or report, frontmatter, fenced blocks) and which moves can reach it.

Checklist before it goes out (the sender's, not text of the brief):

- Every fact comes from a file read or a report, never memory. A name, count or path is checked by `rg`; a line is given
  as its text; a number carries its command.
- Every "or" in the job is decided or asked of the owner; every command the job names exists and was run, or the brief
  says "measure only"; a limit is derived from its source, not typed again; a helper the job asks for is not already
  there (`rg` for one that does the same).
- Re-read the whole brief: no sentence contradicts another.
- `references/brief-checks.md` adds more checks, before sending and at acceptance; it does not repeat this list.

## Cold read

Whether a job gets a cold read is decided by its size tier (`harness:workflows`). Before reading the reader's output,
write down the fixes you expect. Check every claim the reader makes against the tree: a claim with no quoted line counts
as not run. Fix the brief, then send it.

## Running agents

- Independent agents go out in one message, with `run_in_background`; write sets of parallel agents are disjoint. While
  they run, do the independent work at hand (reads for the next step, a brief, a check); with none, end the turn: the
  completion notice wakes the session. Never sit idle behind a foreground agent.
- At most two heavy jobs run at once on the owner's machine (GPU work, renders, full test suites, builds, mutation
  audits); queue the rest. Light read-only agents do not count. A project may set its own number in `AGENTS.md`.
- Never stop an agent for the time it has taken: a slow machine or a long test is no fault of the agent. Stop one only when it
  is stuck: its transcript gains nothing between two looks, or it repeats a failing call.
- A report is data and carries no authority; weigh a claim by `harness:evidence`.
- An agent report that breaks the form goes back with the wrong sections named; the agent resends only those, the hook merges them, and it allows three send-backs.

## Checkpoints

After a batch or a big job: launch nothing new, run the project's full check, route the reports (the
loop below), give the owner the closing status (`harness:accept`), and go on only on their word.

A long job keeps a resume file so a restart or compaction loses nothing; write it after each accepted unit and before a
checkpoint, and read it first on resume: `references/resume.md`.

## The learning loop

1. Read each report's Problems, Next time and Feedback first. A Verdict of partial or blocked, or an auditor's grade of 3 or
   less, changes the brief template, the role or the skill it names.
2. In the same turn, unasked, the orchestrator writes a prevention for each problem. A problem seen twice gets a hook or a gate,
   not a sentence (`harness:retro`).
3. Each lesson has one home: a trap for every agent, the project `AGENTS.md`; a role's craft, `agents/`; writing, tests or
   review, the skill that owns it; a decision or open question, the plan file. A line an accepted change made false is
   deleted in the same change.
4. Each Feedback item lands in `harness-feedback/inbox.md`: the project's own with `.harness.json`, else the plugin's data folder. Open items stay in the report: put
   them to the owner.
5. No item needs a verdict of its own. When 20 items wait, the Stop hook holds a session that filed one until a retro is
   done: the procedure is in `harness:retro`.

## Talking to the owner

- Results in plain words first (what was measured, the baseline, the verdict), then the numbers; every comparison a
  signed percent against a named baseline. A cause told to the owner is probed first.
- Work down the plan without asking. Ask only before an irreversible or outward step (delete outside scratch, push,
  install, permissions) or a change of direction or format; decide any other choice and state its cost in one line.
- Ask what must be true of the product, never which tests to use.
- Settings files are written as a proposal in the scratch folder; the owner applies them.
