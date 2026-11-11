# Refactoring

Behaviour stays; only the structure moves. Medium and large jobs follow `harness:workflows`; the judge rules are in
`harness:testing`; the area is read first (`harness:evidence`).

## Before the first edit

- Run the tests on the untouched tree and keep the result: the exit code, and the count of tests passed, failed and
  skipped. A refactor does not start on a red suite; report the failures and stop, or fix them as a separate change.
- If the code to move has no test that would fail when its behaviour changes, write a characterisation test first: it
  records what the code does today, right or wrong. Commit it apart from the move.
- Record a baseline of what must not change, whatever fits the code: the output of the command on fixed inputs saved in
  `__scratch__/`, the public names (`rg` the exports), the generated file, the schema, the log lines.
- List every caller before the change (`rg` the name over source, tests, scripts, docs, config, the build). A caller
  found late is a behaviour change found late.

## One kind of change per commit

- The kinds: a rename, a move, an extract, an inline, a split, a merge, a signature change, a delete of dead code.
  One kind per commit, so a reviewer reads the diff as one idea and a revert takes one thing out.
- No feature and no bug fix in the same commit. A bug met on the way is written down and fixed afterwards, with its
  own failing test (`harness:review` (references/debug.md)).
- Formatting-only changes are their own commit, made before or after, never inside.
- A move is `git mv` with no edits in the same commit.
- Do not tidy what you pass by. A line outside the one kind of change goes in the report, not in the diff.

## Script the mechanical part

- A rename or a move over many files is one script or one tool call (a refactoring tool, `rg -l0 PATTERN | xargs -0 ...`, or a short
  program), not forty hand edits. The script asserts what it expects: a count of matches, a name that occurs once.
- Prefer a tool that understands the language (a syntax-tree rename) over a text replace; a text replace needs a
  word-boundary pattern and a review of every hit, including strings, comments and docs.
- Run the script on the tree, read `git diff --stat`, and check that the changed file list is the one you expected.

## Every caller updated

- After the change, `rg` the old name again over the whole repository: zero hits, or each hit explained. Include
  strings, config, docs, build files and dynamic access (`getattr`, a name in a string, a registry key).
- A public name (exported, documented, used by another project or by a stored file) changes only on the owner's word.
  Without it, keep the old name as the one that works and report the proposed change under Open.

## Prove behaviour held

- Run the same tests again on the changed tree. The count of tests must equal the count before: a lower count means a
  test was lost, a higher one means the commit holds a second kind of change. Both are reported with the numbers.
- Do not edit a test to make it pass, other than the mechanical update of the name it calls. A test edited beyond that
  is a behaviour change and is reported.
- Compare the baseline: the saved output against the new output, byte for byte, for the same inputs
  (`diff` exits 0). Run the project's type check and linter too; a moved import often breaks only there.

## Stop and report when

- A test fails after the move and the cause is not the move itself: the behaviour changed, so undo the step and
  narrow it (`harness:review` (references/debug.md)).
- The change grows a second kind. Split it into units and report the split.

## What no tool checks

Whether the names after the change are better than before, and whether the caller list was complete for dynamic
access. The reviewer reads the diff for a hidden behaviour change (a reordered side effect, a changed default, a
widened visibility) that the tests do not cover (`harness:review`).
