# The resume file

A restart, a compaction or a fresh session drops what the session knew. The resume file keeps the job's state on disk
so the next session carries on.

## Where

One file in the state folder `~/.local/state/harness/<project>/`, or the project's plan file when it has one. Never two
copies. A hillclimb's decision log (`harness:workflows`) stays its own file and the resume file points to it.

## What it holds

- the goal, in one or two sentences, and the done-when;
- done steps, each with its commit or the evidence that it passed;
- the next step, exact enough to start without asking;
- open questions for the owner;
- running agents: name, brief, and where its output will land.

## When it is written

- On a medium or large job (tiers in `harness:workflows`): after each accepted unit.
- On any job: when the session's goal is met or the owner's next ask is another subject, so a fresh session can start
  from it.

Overwrite the file; do not append a story.

## On resume

Read this file first, then check the tree against it (`git status`, the last commit, the judges). Where file and tree
disagree, trust the tree and fix the file. A listed agent may have ended: look at its output before launching it again.
