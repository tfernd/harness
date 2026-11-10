# Shape of a dynamic workflow

Facts below are from the `workflow-authoring` skill, a Claude Code skill outside this plugin (load it with the Skill tool
before writing a script).

- A script starts with `export const meta = {name, description, phases}`, a pure literal.
- Default to `pipeline(items, stage1, stage2)`: each item moves through its stages with no barrier. Use `parallel`
  (a barrier) only when a stage needs every earlier result: dedup, early exit, comparison between findings.
- One pipeline per item: find, then verify, then act.
- Adversarial verify: several skeptics per finding, each told to refute; keep the finding when a majority fails to.
  Give each a different lens (correctness, reproduction, impact) when the finding can fail in more than one way.
- Pass a `schema` to `agent()` for structured output; it returns the validated object. Without one it returns text.
- `agent()` returns null on a skipped or dead agent: filter with `.filter(Boolean)`.
- No `Date.now()` or `Math.random()` in the script; pass timestamps through `args`.
- Resume: relaunch with `{scriptPath, resumeFromRunId}`; the unchanged prefix of calls returns cached results.
- Log what a cap drops; never truncate silently.
- Worktree isolation only for agents that edit in parallel and would conflict.
