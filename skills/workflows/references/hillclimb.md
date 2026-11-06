# Hillclimb: improve a metric one change at a time

Use when a number can say whether a change helped (speed, score, size, pass rate) and the way up is trial and error.

## Before the first change

1. Freeze the benchmark: the command, its inputs and its seed. Nothing in it changes during the loop; a change to it
   ends the loop and starts a new one with a new baseline.
2. Run it on the untouched tree and record the baseline. Run it twice; the gap is the noise, and a gain smaller than the
   noise is not a gain.
3. Write the stop predicate (below) and the decision log in the scratch folder.

## The loop

One change, one measurement, keep or revert. Never stack a second change on one not yet measured.

1. Make one change.
2. Run the frozen benchmark and the project's gates.
3. Better than the best kept result by more than the noise, and the gates pass: keep it (commit it when the owner has
   allowed commits). Otherwise revert it.
4. Revert through the VCS (`git restore <paths>`, or revert the commit), never by hand, so the tree is exactly the last
   kept state.
5. Write the log row, then check the stop predicate.

## The stop predicate

All three parts are written down before the loop starts:

- a target: the metric value that counts as done;
- a floor: the fewest attempts before the loop may stop, so a lucky early win cannot end it on one noisy run;
- a cap: the most attempts, so a dead end cannot run forever.

Stop when the target is met and the floor is reached, or when the cap is reached. At the cap without the target, report
the best kept result and what was tried; do not raise the cap alone.

## The decision log

One file in the scratch folder, one row per attempt, written right after the measurement:

| # | change | metric | kept or reverted | why |
|---|---|---|---|---|

A reverted row stays: it stops the next attempt repeating it. The log also lets a resumed session continue
(`harness:orchestrator`, resume file).
