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
- On the desktop (2026-11-13: the "A Gutter + tiles" design, see Owner changes) everything is native Box, Text and Button; the ring, the gutter bars, the tile strips and the tiny lanes are small image Svgs (no interactive frame, so no flash), drawn from `desktop-svg.ts` with the palette of `desktop-theme.ts`. The tree is rebuilt on a state change and every 5 s while anything is live.
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
- 2026-11-09: the band agrees with the app on background work: a background Bash command (`tool.call` Bash with `run_in_background`, its id from `result.backgroundTaskId`) is tracked per owner (the agent, or the main session) until its completion notice (a `session.append` row holding `<task-notification>` with `<task-id>`) or a `TaskStop`. An agent that answered while it owns running commands stays live as `waiting` with the state word "BG n"; the main session's idle word becomes "BG n" while it owns some. A failed or killed agent drops its commands.
- 2026-11-11: the owner found the desktop band janky: "sometimes is janky, there are some missing states? alignment is still not great. the agent band in the docs/ is not the same as we get in the claude desktop." Settled: a lane is one continuous bar for the whole time its agent is alive: runs abut (no gap, no round cap between two states), the lane's two ends are rounded by one clip, and the main session's idle time is an open `launched` run in the idle grey (it ends at a session end, with every other open run). Every state has a lane colour, a pill colour and a word (`STATE_WORD`, `MAIN_STATE_WORD` in `model.ts`); `MainActivity` admits `waiting`, since NEEDS YOU is one. An open group header's "N live · M ended" sits in the STATE column, on the pill's left edge, not at the right edge of the band.
- 2026-11-11: the docs page (`docs/band.html`, `band.css`, `band.js`) is a hand-kept simulation, not built from this folder; it follows `model.ts` (six states, their words and colours, continuous lanes, the main session's idle lane, group counts in the STATE column) and is updated with them.

- 2026-11-13: the owner chose "A Gutter + tiles" (mock `band-merge.html`, variation A) for the desktop view, replacing the C1 design the same day; the terminal view is unchanged. Settled:
  - Folded is one row: the ring with its two-line legend, "main", the main state (icon and word), the tiny lane stack with a now-line (5m, main and live agents), the running, done and failed counts, the session cost and a chevron.
  - The ring is concentric arcs for the 5-hour limit, the week limit, the Fable limit (only when the host reports a `fable` kind) and context. OWNER CHANGE: each arc has its own colour (`arcFiveHour`, `arcWeek`, `arcFable`, `arcContext` in `desktop-theme.ts`, blue, magenta, teal, slate in light and dark), distinct from each other and from the state colours violet, green, red and amber, and the legend shows the same colour as a swatch beside each arc's name. A limit at 80% or more adds amber ▲ to its percent, red from 95%. Other limit kinds are not drawn. With no limits (API billing) the ring is context alone and the legend says "API billing" with tokens in and out.
  - Unfolded has no ring row: a left gutter holds each arc (swatch, name, percent, a thin bar in its colour, the reset time or the tokens), a dashed rule, then "session total", "main est." and "agents est." (API billing adds tokens in and out). The right column has the range buttons 1m, 5m, 1h and all (the shared `range` state, `session` shows as "all"), "each cell is 1/24 of the range, newest right", "agents" with the counts and the chevron, then tiles two across: main first, then the agents in the order of `orderAgents`.
  - A tile has the name, the model, the state (icon and word), the detail, a 24-cell strip for the range, the time, tokens in / out and the estimated cost; hovering it reveals the facts (now, model, ran for, tokens, cost). The strip colours a cell by what the agent did most in that slice: ink for main working, violet for an agent working (the soft shade thinking), amber waiting, green or red once ended. Idle is a light cell with a small dot, never solid ink.
  - The twelve states, each with its own icon: idle, thinking, waiting (needs you, for main or an agent with no known tool), waiting (permission: tool, an agent that waits with a tool named), bash, editing, reading, searching, web, agent, done, failed. The tool kind comes from the first word of the open call (`activity.ts`: Edit, Write, MultiEdit, NotebookEdit are editing; Read is reading; Grep, Glob, LS are searching; WebFetch, WebSearch are web; Task, Agent are agent; anything else is bash). The host does not tell a permission wait from other waits (see 2026-11-09), so "permission" is a guess from an agent that waits with a tool named. "quiet N" and "BG n" still replace the detail.
  - The main tile's time is the session's age from the session start the host reports (`usage().startedAt`), written "1h52m", and in days from 24 h ("3d10h"). An agent's time is from its own start.
  - Costs: an agent's is the estimate from its tokens (`MODEL_PRICES` in `cost.ts`), shown with `~`. "session total" is the host's cost; "main est." is the session total minus the agents' estimate, and when the host gives no total it is main's own token estimate and reads "main est. (tokens)"; "agents est." is the sum of the agents.
  - The empty slot is a ghost tile: "No agents yet this session." only when the session has had none, else "+N ended earlier" (a button that switches the range to all) for agents that ended before the range, with "+N more" when the row cap hides some.
  - Nothing is drawn twice in one view: the folded row has the ring, legend, main state, lanes, counts and cost; the unfolded body has the gutter, the tiles, the range and the counts. The "Long session" note and its Dismiss button are gone; the context arc's ▲ says it.

## Not in this version

- Hover tooltips and eased CSS transitions of the mock where the surface has no such thing; say which ones per surface.
- The mock's dashed ghost tile: a Box has no dashed border, so the ghost tile has a round dim one.
