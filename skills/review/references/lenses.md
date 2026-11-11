# The lens brief, the finding shape and the six lenses

## The brief for one lens scout

Field names follow the brief template of `harness:orchestrator`; `Lens:` through `Output:` are added lines.

```
Role:      scout
Goal:      find every <lens> finding in <scope>, so the sweep can rank them
Tree:      base commit; nobody editing
Input:     /tmp/harness/<project>/sweep/map.md and the files of the map that belong to the scope (paths only)
Lens:      the lens name and its paragraph below
Scope:     the folders or file list this scout may read
Quote:     both sides verbatim with path:line; the line's text, not a paraphrase
Clean:     NOT FOUND for a lens with nothing; never a guess
Coverage:  files read, then files in scope not read
Output:    the finding table below
Report:    harness:report, headings in order
```

## The finding shape

One shape in every file of the sweep:

| ID | lens | severity | side 1 path:line "quote" | side 2 path:line "quote" | side to change |
|---|---|---|---|---|---|

For a bypass, side 2 is the input and the result. For a dead pointer, side 2 is the failed `ls` or `rg` and its output.

## Severity for rule text

This is how the scale of `harness:review` maps onto rule text:

- **A:** following the text gets the reader refused, breaks a build, or loses work.
- **B:** the text misleads; the reader does the wrong thing and something later catches it.
- **C:** wording, duplication, a stale count.

## Contradiction

Same subject, same scope, same condition, opposite instruction. A narrower rule, or an exception that names the broader
rule, is not a contradiction. "Run the tests before each commit" and "run the full suite once before a push" differ in
scope and do not conflict. Name the shared subject, scope and condition before calling one.

## Drift

A count, name, flag, default, path or example in prose that the code or config no longer matches. Read the code or
config side, then the text; the text usually changes. Include tables listing things (commands, options, roles).

## Holes

Build the enforcement matrix (`holes.md`). A rule only text enforces, a check no stated rule asks for, and
an enforcement with no test are each a hole. A rule every document states and nothing enforces is the worst kind.

## Duplication

One fact written in two homes, even when both agree today; they will part. The finding names the better home and the
copy to replace with a pointer.

## Dead pointers

A path, skill name, heading, command, flag or link that does not exist. Resolve each one: list the folder, run the
command with `--help`, search the heading. Side 2 is the listing or search that shows it missing.

## Bad examples

An example that breaks the rule it sits under: a snippet with a comment under a no-comments rule, a name the naming
rule forbids, a command the safety rule refuses. Side 1 is the rule, side 2 the example.
