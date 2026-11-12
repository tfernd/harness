# Sweeping a repo against itself

The sweep runs with the harness plugin's roles (scout, worker, reviewer), in any repo that has the plugin installed.
`review` checks a change against its spec;
the sweep checks a repo against itself: its rules, docs, config and checks against each other.

## When

Before a release, after a batch of rule changes, or on the owner's ask.

## Cost shape

One cheap scout per lens, one adversary, one verifier, then the fix workers. Tell the owner at launch.
A large repo gets one scout per lens per top folder; the coverage lists decide the second wave.

## Roles and models

| Step | Role | Model |
|---|---|---|
| 1 Map, 2 Lenses | `scout`, read-only, parallel | its default (Haiku) |
| 3 Adversarial pass | `reviewer`, lens Adversarial | its default (Sonnet) |
| 4 Verify | `reviewer`, cold, given only the finding | its default |
| 5 Rank | main session | |
| 6 Fix, 7 Prevent | `worker`, one per disjoint set of files | its default |

Briefs follow `harness:orchestrator`; the lens brief's fields are in `lenses.md`.

## Procedure

1. **Map the rule homes.** Every place a rule is written (instruction files, skills, docs, README, templates, config)
   and every place one is enforced or tested (hooks, linters, CI, tests, pre-commit). The map is a file list saved as
   `/tmp/harness/<project>/sweep/map.md`. Each scout returns the files it read and the files it did not; a second wave targets the
   unread ones, since a first pass skips whole reference folders.
2. **Lenses.** One read-only scout per lens, in parallel:
   - Contradiction: two homes give opposite instructions for the same subject, scope and condition.
   - Drift: docs, counts, names, flags and examples that disagree with the code or config.
   - Holes: one row per rule: where it is stated, what enforces it, what tests the enforcement.
   - Duplication: one fact stated in two homes, even if they agree today.
   - Dead pointers: names, paths, headings and commands that do not exist.
   - Bad examples: an example that breaks the rule it teaches.

   A finding has the one shape of `lenses.md`: both sides quoted verbatim with `path:line`, a severity and
   the side to change. A clean lens answers NOT FOUND; a guess is never a finding. What to look for per lens: the same file.
3. **Adversarial pass.** One reviewer tries to get past each enforced rule with real inputs, run against the check's own
   command on a scratch copy of its input. Never against a remote, a CI service, a deploy or real data; never pushes.
   Each bypass is a finding. Input list and matrix form: `holes.md`.
4. **Verify.** A reviewer, cold and with only the finding, re-reads each A and B finding and marks it CONFIRMED or
   REJECTED with its own quote. C findings are not verified. The main session spot-checks the A findings itself. A cheap
   scout over-calls; the boundary of a contradiction is in `lenses.md`.
5. **Rank.** One table, A first, saved as `/tmp/harness/<project>/sweep/findings.md`, so workers and the verifier read it by path.
   REJECTED findings stay in it with the verifier's reason, so a later sweep does not raise them again; they are not
   fixed. Decisions only the owner can make are listed apart, each as one question with the main session's pick first;
   they are asked, never assumed.
6. **Fix.** Workers on disjoint sets of files. Text fixes go in one pass, with checks run once at the end; C findings are
   fixed in that pass when cheap, else listed. An enforcement fix gets its test case and a deliberate-bug control
   (`harness:testing`).
7. **Prevent.** A drift that can come back is fixed by a check, or by generating the text from its source, not only by
   editing the line again.
8. **Record.** The verifier's report carries one Feedback line per CONFIRMED finding that needs a rule, naming the file
   to change and the problem it would have prevented (`harness:report`), so the main session acts on it.

## Done when

Every A and B finding is fixed (with its check run), REJECTED with a reason, or put to the owner. Then the lenses that
found A or B findings run once more over the changed files. The sweep stops when that pass finds no new A or B.

## What no tool checks

Whether a rejected finding was really wrong, whether the file map missed a rule home, and whether a decision listed
for the owner is truly theirs.
