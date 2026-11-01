---
name: cold-read
description: How a cold reader checks a brief or spec using only that text - goal, files touched, done-when, a GUESS list and a quoted line for every name. Load when you are the cold reader, or when you judge a cold reader's report.
---

# The cold read

A cold reader has only the brief (or spec) and the repository, none of the author's reasoning. It finds gaps in the
text so the worker does not have to guess. It never does the job and edits nothing.

## What the reader does

1. Read the brief once, whole. Open only the files it names.
2. Write the **read-back**, in this order:
   - **Goal:** one sentence.
   - **Files touched:** every file you would create or change, from the brief alone.
   - **Done when:** the judge and the result that counts as done.
   - **GUESS list:** every decision you would have to guess: a name, a signature, a default, an order, a file the
     brief does not assign, a word with two readings ("or", "maybe", "similar"). Empty is allowed, and suspect.
3. **Names:** for every path, function, command, test id, flag and skill the brief mentions, say whether it exists. A
   claim of existence quotes the matching line with `path:line`. A claim with no quoted line counts as not checked.
   A name the brief says is new is checked only for a clash with an existing one.
4. **Verdict:** `ready` (no GUESS, every name found) or `needs_work`, with the gaps ranked: a gap that would make two
   workers diverge first.

Report in the short form of `harness:report`: Answer holds the verdict, the four-part read-back and the GUESS list; Work
holds one line per name with its quote.

## Rules for the reader

- Do not fill a gap from the repository's habits and call it clear: if the brief did not say it, it is a GUESS.
- Do not run builds or tests; run only the commands that read (`ls`, `grep`, `git show`).
- A name you cannot find is reported as missing, not guessed around. Say where you looked.
- You judge the text, never the owner's intent: if the goal looks wrong, say it is ambiguous, not mistaken.

## Rules for the orchestrator

- **Two readers on a large job,** run separately, neither seeing the other. Where their read-backs differ, the brief is
  ambiguous there: fix the text, never pick a reader.
- **Check the report against the tree.** A reader's claim that a name exists or is missing is checked by one grep
  before the brief changes. Count false claims; a reader with many false claims is rerun on a stronger model
  (`harness:models`).
- **Scope.** The cold read finds brief gaps. It does not find a misreading of the owner: that is the one-sentence
  read-back to the owner before any work (`harness:orchestrator`).
- Fix the brief, then rerun the reader on the fixed text only if the gaps were many; log one line per read.
