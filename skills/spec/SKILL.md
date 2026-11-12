---
name: spec
description: How a spec is written for a large or public-contract job - a file with goal, non-goals, decisions with every "or" settled, files and judges. Load before writing a spec, or before reviewing one or briefing workers from one.
---

# A spec

A spec is a file in the repo (`~/.local/state/harness/<project>/<topic>/SPEC.md` unless the project names a place), written before any
worker starts. Workers and readers get its path in the brief. A spec that lives only in chat is not a spec.
The orchestrator decides what goes in and briefs a worker to write the file. Tiers that need one: `harness:workflows`.

## Sections, in this order

1. **Goal:** one sentence with the why. A reader who stops here knows what is being built.
2. **Non-goals:** what a reasonable worker might add and must not. Each is a thing someone could be tempted to do.
3. **Decisions:** one line per choice, already made: names, signatures, formats, file locations, defaults, error
   behaviour. Every "or", "maybe", "TBD", "probably" and "should" is settled here or moved to Open questions.
4. **Files:** one list per unit: the files it may create or change, as paths or globs. Lists are disjoint. A file two
   units need is assigned to one of them, and the other gets the change under Open.
5. **Judges:** per unit, the commands that decide done, with the expected result; for an "unchanged" result, the value measured before the change.
   Every decision that can break has a judge (`harness:testing`).
6. **Contract:** only for a public interface: its exact shape, so two units written apart still fit.
7. **Open questions:** only what the owner must answer. Work that depends on one does not start.

## Rules

- **One home per fact.** A fact is stated once, in the contract or the decision that owns it; other units point to it.
- **No unsettled choice.** Search the draft for "or", "either", "if possible", "etc.", "similar". Each hit is a
  decision to make or a sentence to cut.
- **Names exist.** Every path, function, command and test id the spec cites is checked in the tree (`harness:evidence`)
  or marked NEW with the file that will define it.
- **Facts carry evidence.** A claim about the existing code has `path:line`; a claim about a tool or model has the doc
  or command that showed it.
- **Short.** A spec states decisions, not reasoning; the reasoning goes in a line after the decision, only where a
  worker would otherwise undo it.
- **Frozen once started.** A change after workers start is an edit by the orchestrator, and every unit it
  touches is re-briefed.

## Checking a spec

A spec is accepted only after a cold read and a review
(`harness:review`, Interface lens). The reviewer checks that the file lists are disjoint, that every unit has a judge, and
that no decision contradicts another.

## The cold read

A cold reader is a `scout` that has only the spec (or brief) and the tree, none of the author's reasoning; it edits
nothing and runs only commands that read. Two readers on a large job, run apart. It returns: the goal in one sentence;
the files it would touch; the judge and result that count as done; a GUESS list of every decision it would have to
guess (a name, a signature, a default, an order, a file not assigned, a word with two readings); and for every path,
function, command, test id and flag the spec names, whether it exists, with the matching `path:line` quoted (a claim
with no quoted line counts as not checked). Where two readers differ, the text is ambiguous there: fix the text. The
main session checks a claimed name by one grep before changing the spec. A cold read finds gaps in the text, not a
misreading of the owner (that is the read-back in `harness:orchestrator`).
