# The enforcement matrix and the adversary's inputs

## The matrix

One row per rule, from the files of the map. A blank cell in a column is a hole.

| Rule | Stated at | Enforced by | Tested by | Hole |
|---|---|---|---|---|
| short text of the rule | path:line | hook, linter, CI step or pre-commit entry, with path:line | test file and case | none, text only, no test, or no stated rule |

Three holes: a rule only text enforces; a check that no stated rule asks for; an enforcement with no test that fails
when it is removed. For the last, name the test and the bug it would catch; one that cannot fail is no test
(`harness:testing`).

## The adversary's inputs

The adversary is a reviewer. It runs the check's own command on a scratch copy of its input, never
against a remote, a CI service, a deploy or real data, and never pushes. It records the input and the result for each try. For each enforced rule try:

- other spellings: case, a long option written short, a path with `./`, `..` or a trailing slash, quoting, unicode
- wrappers: `sh -c '...'`, `bash -c`, `env X=1 cmd`, `xargs`, `sudo`, a script file that runs the command
- prefixes and chains: an env assignment before the command, `&&`, `;`, a subshell, a pipe, a heredoc
- flags: the same effect through another flag, a flag after the arguments, `--` before them
- edge values: empty, one, the limit, one past it, a very long input, a name with spaces or a leading dash
- a rule's own allowed case moved one step toward the forbidden one

Each bypass is a finding in the shape of `references/lenses.md`: side 1 is the rule, side 2 the input and the result, and
the side to change is the check or the rule.
A refused input is not a finding; list the inputs tried and refused in the coverage so the verifier can see the reach.
