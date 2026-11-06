# Resume file for a long job

A restart or a compaction drops what the session knew. A long job keeps its state on disk so the next session carries on.

## Where

One file in the scratch folder, or the project's plan file when it has one. Never two copies. A hillclimb's decision log
(`harness:workflows`) stays its own file and the resume file points to it.

## What it holds

- the goal, in one or two sentences, and the done-when;
- done steps, each with its commit or the evidence that it passed;
- the next step, exact enough to start without asking;
- open questions for the owner;
- running agents: name, brief, write set, and where its output will land.

## When it is written

After each accepted unit, and before any checkpoint. Overwrite the file; do not append a story.

## On resume

The first act of a resumed session is to read this file, then check the tree against it (`git status`, the last commit,
the judges). Where file and tree disagree, trust the tree and fix the file. A listed agent may have ended: look at its
write set before launching it again.
