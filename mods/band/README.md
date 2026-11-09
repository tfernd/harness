# harness-band

A Claude Code mod: a band above the prompt with status, context, cache, the 5-hour and week limits, agent counts and a
fold toggle; unfolded it adds a moving timeline of the main session and its agents (ranges 1m 5m 15m 1h session, groups by workflow
and direct); folded it keeps the band row and one thin live trace per agent. Look and contract: `SPEC.md`.

## Install it

```
claude plugin marketplace add https://github.com/tfernd/harness.git
claude plugin install harness-band@harness --scope user
```

Then restart Claude Code or run `/reload-plugins`. Update with `claude plugin update harness-band@harness`.

## Develop it

```
claude --plugin-dir <absolute path to this folder>
```

The folder is hot-reloaded while the session runs. Check it with `claude plugin validate <folder>` and
`claude plugin test <folder>`.

## Painting

- The moving parts (lanes, traces, elapsed clocks) are `Raster`s repainted by `$.ui.blit` every 200 ms (5 a second,
  inside the 60 a second the surface shows). A blit is sent only when a raster's cells changed.
- The tree is rebuilt only when an agent joins or ends, or the range, a fold, a gauge or the turn changes. Card, state, command, elapsed and reset texts are rasters painted by the tick, so a sub-agent's tool call rebuilds nothing.
- Everything the drawing reads lives in `$.state`; the two clocks start on the first event or render after a load and are cancelled at `session.end`, except on `/clear`.

## Narrow widths

The layout follows `bodyColumns`. As it shrinks the band drops, in order: the detail text (used/window, resets in),
the week gauge, the 5h gauge, the cache gauge, the context gauge. Status, counts and the toggle stay. The timeline
drops its state column under 60 columns and the cards go from three to fewer.

## Known limits

- Rasters exist on the terminal surface only; the desktop surface draws the lanes as coloured text, repainted when the
  tree is rebuilt, not on the tick.
- Raster cells take raw colours, so lanes use a light and a dark palette chosen from the `theme` setting; text and
  borders use the theme's own names.
- Each agent keeps at most 200 segments; past that the shortest neighbouring pair merges, so old history turns coarse.
- Segment history lives in `$.state` for the session; it is not kept across sessions.
