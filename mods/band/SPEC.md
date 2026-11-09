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
3. **Unfolded (the start state):** the band row, then the live strip (one card per live agent: name, state, elapsed,
   current command or "thinking..."; three cards and "+N"), then the timeline: range 1m 5m 15m 1h session, agents
   grouped by workflow and direct, one row per agent with its bar (thinking, tool, waiting, done, failed) and a state
   column; groups fold.

## Painting

- The moving parts (lanes, bars) are a `Raster` repainted with `$.ui.blit` on a `$.clock.every` tick: no render pass,
  no tree rebuilt per frame. The tree is rebuilt only when an agent, a state or a fold changes.
- On the desktop, text, pills and cards are native Box/Text; each ring is its own small Svg, rebuilt only on a
  whole-percent, tone or theme change; the traces and the timeline are image Svgs (no interactive frame, so no flash;
  timeline hover was given up for that).
- The timeline shows an agent only if its life overlaps the chosen range (live ones always); per group the rest show
  as one dim "+N earlier" line, and a group with nothing at all is not drawn.
- Values the drawing reads live in `$.state`, so a write redraws only its readers.

## Owner changes

- 2026-11-09: the owner removed the live agent cards from the desktop view: "this line with the agent tool thing, is
  not adding anything... can you just remove it ... this makes things shorter and better". The timeline row and its
  STATE column stay; the terminal view keeps its strip.
- 2026-11-09: the owner asked for the main session row in the timeline: "the timeline show agents, but not the main sessions, fix that?"

## Not in this version

- Hover tooltips and eased CSS transitions of the mock where the surface has no such thing; say which ones per surface.
