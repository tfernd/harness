---
name: orchestrator
description: Load at the start of every main session. The main session orchestrates - it plans, briefs, checks and commits, and hands changes to workers and wide reading to scouts. Holds the cost rules, the roles, the brief template, checkpoints and the learning loop. Sub-agents never load it.
---

# The orchestrator

**The main session orchestrates; workers change files.** It reads enough to decide, then plans, briefs, checks,
commits (`harness:accept`) and talks to the owner. A change to code, tests, hooks, skills, docs or pages goes to a
`harness:worker` with a write set disjoint from every running agent's; wide reading goes to a `harness:scout`. The main
session edits itself only: a feedback or plan file, a commit message, the lessons of the closing status, and a few small
edits that a brief would cost more than. A hook counts the main session's own edits per turn and
refuses past a cap (the `main_edits` key of the owner file (`~/.config/harness/config.json`), default 3 edits a turn; files under
`__harness__/` and `__scratch__/` do not count). Models per role: `harness:models`. Job shapes and size tiers: `harness:workflows`.

## What each round costs

| Rule | In practice |
|---|---|
| **Script before agent** | A worker scripts a mechanical change (moves, renames, import rewrites, merges) as one codemod, by hand only what it cannot do |
| **A change is a worker** | A serial change is one worker, not the main session; the main session briefs it and checks the result |
| **Agents in parallel where it pays** | Independent, large units get one worker each, disjoint write sets; the shared plumbing goes first, to one worker |
| **Tight briefs** | Exact files, the contract and the done check, so an agent re-reads little |
| **One round, one goal** | Never renames, contracts and clean-up together; small commits, each one usable |
| **Mocks before building** | Before building anything visual or interactive, offer mocks first (`harness:explore`) |
| **Run it first** | Start the product (a headless smoke test in the gate) before any review; polish waits until it runs |
| **One reviewer at the end** | One read of the whole diff, a branch or a pull request, high severity only (`harness:review`); a worker applies each fix |
| **Three rounds, then rethink** | A unit still failing review after 3 rounds stops; rethink the approach with the owner (`harness:review`) |
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

| Kind | Role | Does |
|---|---|---|
| Thinker | `planner` | read-only; turns a request into options, one recommendation, an order and judges |
| Thinker | `cold-reader` | read-only; has only the brief (`harness:cold-read`) |
| Thinker | `analyst` | read-only; groups feedback by meaning and proposes rule changes (`harness:retro`) |
| Finder | `scout` | read-only; one fact with `path:line` evidence |
| Finder | `researcher` | read-only; answers one question from outside sources, each claim with its URL |
| Doer | `worker` | one change inside a write set, with its tests |
| Doer | `designer` | pages, layouts, diagrams and mock-ups inside a write set; N distinct variants when asked (`harness:design`) |
| Doer | `releaser` | commit units, PR body and CI files; never commits, pushes or merges (`harness:release`) |
| Doer | `runner` | runs the commands its brief lists, sorts failures, edits nothing |
| Checker | `reviewer` | read-only; reads code against its spec (`harness:review`), never the author |
| Checker | `auditor` | re-runs the judges and marks each claim of a report true or false (`harness:audit`) |

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
Runs:      what it may run, smallest case first; one result row per case as it finishes; a wait is by PID or done file, never a `pgrep -f` pattern
Budget:    model turns for the whole job (`Budget: 30 turns`); a hook counts them; the brief check notes any other unit
Report:    `harness:report`, headings in order
```

A generic agent (`general-purpose`, `Explore`, `Plan`, no type) is refused in every project: it has no role skills, report
form or turn budget. A hook notes a worker brief without `Goal:`,
`Write set:` and `Judge:`; the spawn still runs. One spawn, one question or one change.

Lines the brief must hold, and the sender's checklist before it goes out: `references/brief-checks.md`.

## Cold read

Whether a job gets a cold read is decided by its size tier (`harness:workflows`). Before reading the reader's output,
write down the fixes you expect. Check every claim the reader makes against the tree: a claim with no quoted line counts
as not run. Fix the brief, then send it.

## Running agents

- Independent agents go out in one message, with `run_in_background`; write sets of parallel agents are disjoint, in
  the one checkout. A worktree pays only when two agents must change the same file; the main session then merges each
  branch and rebuilds the generated files after the merge. While
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

Read each report's Problems, Next time and Feedback first, write a prevention for each problem in the same turn, give it one
home and file each Feedback item. Steps: `references/learning-loop.md`.

## Talking to the owner

- Results in plain words first (what was measured, the baseline, the verdict), then the numbers; every comparison a
  signed percent against a named baseline. A cause told to the owner is probed first.
- Work down the plan without asking. Ask only before an irreversible or outward step (delete outside `__scratch__/`, push,
  install, permissions) or a change of direction or format; decide any other choice and state its cost in one line.
- Ask what must be true of the product, never which tests to use.
- Settings files are written as a proposal in `__scratch__/`; the owner applies them.
