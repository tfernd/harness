# The learning loop

1. Read each report's Problems, Next time and Feedback first. A Verdict of partial or blocked, or an auditor's grade of 3 or
   less, changes the brief template, the role or the skill it names; a role graded that low twice is `harness:retro`'s.
2. In the same turn, unasked, the orchestrator writes a prevention for each problem. A problem seen twice gets a hook or a gate,
   not a sentence (`harness:retro`).
3. Each lesson has one home: a trap for every agent, the project `AGENTS.md`; a role's craft, `agents/`; writing, tests or
   review, the skill that owns it; a decision or open question, the plan file. A line an accepted change made false is
   deleted in the same change.
4. Each Feedback item lands in `__harness__/feedback/inbox.md`: the project's own (the plugin's data folder when the start folder is `/` or the home folder). Open items stay in the report: put
   them to the owner.
5. The Stop hook files each bullet under the closing `Lessons` heading into the inbox. No item needs a verdict of its own.
   When a retro is due (10 items wait, the oldest is 3 days old, or a session ran 10 agents), launch `harness:analyst` in
   the background; the Stop hook holds the turn until every waiting item has a `handled.md` line. The trigger and the
   procedure are in `harness:retro`.
