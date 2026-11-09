# Agent band: spec

The frozen look is `__scratch__/band-mocks/v4.html` (screenshots `v4-unfolded-light.png`, `v4-folded-dark.png`).
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
- On the desktop, text, pills and cards are native Box/Text; each ring is its own small Svg, rebuilt only on a
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
  question (`AskUserQuestion`, a `tool.call`) is open or `tool.check` answered `ask` to a person, and any live row with
  no state or command change for 2 minutes says "quiet 2m" (minutes counting up) in its state cell until its next change.
  NEEDS YOU from a permission ask clears when that tool call ends, not at the answer: no event marks the answer.
- 2026-11-09: desktop polish: the state cell of a quiet row is a muted amber pill and NEEDS YOU a strong amber one; a
  folded group header is a 24px chevron button, a label piece, a density strip exactly as wide as the track (its left
  edge on the track's left edge, its right on the now line, half the row high, centred) and a counts piece in the state
  column ("N tool · N think · N wait"); the range control is plain text, the active one bold and underlined.

## Not in this version

- Hover tooltips and eased CSS transitions of the mock where the surface has no such thing; say which ones per surface.
