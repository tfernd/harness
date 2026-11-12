# Agent band: spec

The frozen look is `docs/band.html`.
This file holds the owner's words and what they settle. Nothing goes in that the owner did not ask for.

## The owner's words

- "a nice good looking BAR on the top then we can expand the view of the agents with this timeline that MOVES"
- "we deal with agents, named ones or not and dynamic workflows too. we show some dots about agents overall status, how many in the session"
- "show context. where we are in compaction, from how much, how hot the cache is. 5 and week limits what sub-agents are doing ... launched, not launched, thinking (blinking), running bash, waiting, finished, failed"
- "minimizing show the timetraces compact is AMAZING"
- "live wrapper between the top and the agents when unfolded is nice"
- "agent starting unfolded is better"
- "timeline is nice, could be 1m, 5m, 15m, 1h, session"
- "just pay attention to dom rewrites, because this causes flicker, we need to be careful with painting!"

## What it is

A Claude Code mod: a `ui.render` hook on `AbovePrompt` (the band above the prompt).

1. **Band row:** status (working, waiting, idle, with time this turn); context ring (percent, used / window); cache;
   5-hour limit and week limit (percent, resets in); agent counts (live, done, failed, this session); a fold toggle.
2. **Folded:** the band row plus the compact live traces: one thin lane per live agent over the last minute, now at the right.
   Nothing leaves the band the instant it ends: a trace, a row past the time window and a row the store would evict stay
   `LINGER_MS` (5 s) in their ended look, then go; counts never change by it.
3. **Unfolded (the start state):** the band row, then the live strip (one card per live agent: name, state, elapsed,
   current command or "thinking..."; three cards and "+N"), then the timeline: range 1m 5m 15m 1h session, agents
   grouped by workflow and direct, one row per agent with its bar (thinking, tool, waiting, done, failed) and a state
   column; groups fold.

## Painting

- The moving parts (lanes, bars) are a `Raster` repainted with `$.ui.blit` on a `$.clock.every` tick: no render pass,
  no tree rebuilt per frame. The tree is rebuilt only when an agent, a state or a fold changes.
- On the desktop (2026-11-13: the C1 design, see Owner changes) everything is native Box, Text and Button; the limit bars and the tiny lanes are small image Svgs (no interactive frame, so no flash). The tree is rebuilt on a state change and every 5 s while anything is live. The older description that follows is the previous desktop view.
- Previous desktop view: text, pills and cards are native Box/Text; each ring is its own small Svg, rebuilt only on a
  whole-percent, tone or theme change; the traces and the timeline are image Svgs (no interactive frame, so no flash;
  timeline hover was given up for that). The timeline is several pieces, top to bottom: the axis header and main row
  (one Svg), then per group a native header Button (chevron, tag, name; the "N live · M ended" count sits beside it,
  since a Button holds only text) that folds the group, and that group's rows with "+N earlier" (one Svg, none when
  folded), then the "+N more agents not drawn" line. The only group toggle is that header Button.
- The timeline shows an agent only if its life overlaps the chosen range (live ones always); per group the rest show
  as one dim "+N earlier" line, and a group with nothing at all is not drawn.
- Inside a group, live agents come first (oldest start on top), then ended ones, most recently ended first; the row limit cuts after that order, through one function (`orderAgents`) for every view.
- Values the drawing reads live in `$.state`, so a write redraws only its readers.

## Owner changes

- 2026-11-09: the owner removed the live agent cards from the desktop view: "this line with the agent tool thing, is
  not adding anything... can you just remove it ... this makes things shorter and better". The timeline row and its
  STATE column stay; the terminal view keeps its strip.
- 2026-11-09: the owner asked for the main session row in the timeline: "the timeline show agents, but not the main sessions, fix that?"
- 2026-11-09: the owner asked to spot stuck work and to know when he is needed: the main row says NEEDS YOU while a
  question (`AskUserQuestion` or `ExitPlanMode`, a `tool.call` that blocks until answered) is open, and any live row with
  no state or command change for 2 minutes says "quiet 2m" (minutes counting up) in its state cell until its next change.
  A permission `ask` from `tool.check` does not show NEEDS YOU: the verdict goes to the mode's decider (dialog,
  auto-mode classifier, headless host), and the session's current mode cannot be read (only `agent.spawn` carries
  `permissionMode`, and `approver` says only that a person can be asked), so a person cannot be told to be asked.
- 2026-11-09: desktop polish: the state cell of a quiet row is a muted amber pill and NEEDS YOU a strong amber one; a
  folded group header is a 24px chevron button, a label piece, a density strip exactly as wide as the track (its left
  edge on the track's left edge, its right on the now line, half the row high, centred) and a counts piece in the state
  column ("N tool · N think · N wait"); the range control is plain text, the active one bold and underlined.
- 2026-11-09: the band agrees with the app on background work: a background Bash command (`tool.call` Bash with `run_in_background`, its id from `result.backgroundTaskId`) is tracked per owner (the agent, or the main session) until its completion notice (a `session.append` row holding `<task-notification>` with `<task-id>`) or a `TaskStop`. An agent that answered while it owns running commands stays live as `waiting` with the state word "BG n"; the main session's idle word becomes "BG n" while it owns some. A failed or killed agent drops its commands.
- 2026-11-11: the owner found the desktop band janky: "sometimes is janky, there are some missing states? alignment is still not great. the agent band in the docs/ is not the same as we get in the claude desktop." Settled: a lane is one continuous bar for the whole time its agent is alive: runs abut (no gap, no round cap between two states), the lane's two ends are rounded by one clip, and the main session's idle time is an open `launched` run in the idle grey (it ends at a session end, with every other open run). Every state has a lane colour, a pill colour and a word (`STATES` in `svg-theme.ts`, `STATE_WORD`, `MAIN_STATE_WORD`); `MainActivity` admits `waiting`, since NEEDS YOU is one. An open group header's "N live · M ended" sits in the STATE column, on the pill's left edge, not at the right edge of the band.
- 2026-11-11: the docs page (`docs/band.html`, `band.css`, `band.js`) is a hand-kept simulation, not built from this folder; it follows `svg-theme.ts` and `model.ts` (six states, their words and colours, continuous lanes, the main session's idle lane, group counts in the STATE column) and is updated with them.

- 2026-11-13: the owner chose the "C1 Live timeline" design for the desktop view (the terminal view is unchanged). Settled:
  - Folded is one row: running, done and failed counts (glyph and number), a tiny lane stack with a now-line (5m), the session cost, `ctx N%` (amber ▲ at 80% and over), then a mini bar for every rate limit.
  - Unfolded, the top line keeps only the counts, the cost and the fold chevron. Every limit shows once, as a full block (name, %, bar, "Resets ..."), then Context; the tiny lane stack and the mini bars are not drawn, since the timeline and the blocks say it.
  - Limits: every `rateLimits` entry is a bar. `five_hour` is "Session", `seven_day` is "Week", any other kind is its own bar named from the kind string (`fable_weekly` reads "Fable weekly"). With no limits (API billing) the blocks are session cost (`session.usage().cost.usd`) with the agents' estimate, tokens in / out, turns and elapsed.
  - The timeline: a legend ("main session", "agents") with the range buttons 1m, 5m, 1h, session (the shared `range` state; the terminal still has 15m), an axis ("1h ago ... now"), the main session as its own lane at the top (label "main", neutral ink), then one lane per agent: state glyph and word, name and type, model badge, a bar from its start to its end (running violet with its tool inside, done green, failed red with "failed: reason" beside it, waiting amber), time, tokens in / out, estimated cost. Colour always comes with a glyph or a word. A native Box, Text and Button tree, with bar Svgs for the limit bars and the tiny lanes; no Raster and no interactive Svg.
  - Per-agent cost is an estimate: the tokens of its `turn.complete` usage times a price per model family kept in one table (`MODEL_PRICES` in `cost.ts`), shown with `~`. A model not in the table shows tokens only.
  - When context use is 80% or more, an amber line says "Long session: each turn re-reads Nk tokens. A fresh session is cheaper." with a Dismiss button. There is no Start fresh button: a mod cannot start a session.
  - The group headers, the density strips, the quiet pill and the cached ring pieces of the old desktop view are not drawn; the states "quiet N" and "BG n" still replace the state word, and NEEDS YOU still shows on the main lane.

## Not in this version

- Hover tooltips and eased CSS transitions of the mock where the surface has no such thing; say which ones per surface.
- 2026-11-09: live desktop fixes (a desktop draws every Button as a native button with its own chrome): the range control
  is one Button "range 1m ▾" that cycles on press; a group header is one Button holding "∨ DIRECT direct agents" in a
  fixed-width label column, the strip (12px, centred) and the counts (zeros dropped) beside it; under the auto theme the
  band paints no surface, tints rows with a translucent grey and frames with the theme key `promptBorder`; one frame, no
  border of our own; gauges sit left with equal gaps and the ring-less cache keeps a ring-wide slot; the folded traces
  budget counts the native Button and the real gaps.
- 2026-11-09: owner fixes to the folded band: the live traces shrink to the width that is left (56 to 360 px) before they drop; live, done and failed are one three-row icon Svg (a blue dot, a check, a cross, numbers only, zero dim) in the folded and the open band; the cache gauge reads "cache" over "warm ~56m", "cold" or "84% hit".
- 2026-11-09: nothing on the folded line is cropped: the counts Svg always reserves three digits and never shrinks; the traces sit in a Box that may shrink (`flexShrink` 1, `minWidth` 0, hidden overflow), and their width estimate assumes wider text, status and unfold button, so the strip gives way first.
