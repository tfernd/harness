---
name: explore
description: The mock-first process for anything visual or interactive: offer mocks, diverge, pick and merge, freeze a spec, build logic then view, polish last. Load before building a game, page, dashboard, UI or diagram.
---

# Explore before building

Building before the look is chosen costs days. Choose the look on cheap mocks, freeze it, then build.
Designer-side rules for a variant: `harness:design`. Games: `references/games.md`.

## The loop

1. **Offer.** A request for something visual or interactive gets "want 3-5 mocks first?" before any build. Skip only
   for a small change to an existing look.
2. **Diverge.** 3-5 designers in parallel, one variant per agent (two at most), each clearly different along a
   named axis (layout, density, metaphor, flow). Each brief gives:
   - placeholder data, so the look is judged and not the content;
   - static HTML that opens from `file://`;
   - a width budget at the target width (characters per line, px per column), so the first render fits;
   - the first tool call is a Write of the mock file.
   After 2-3 minutes an agent with no Write is stopped and relaunched smaller. When the shape is new, try one agent
   before fanning out.
3. **Label.** Variants carry a letter or number, so the owner picks in one message. Send screenshots and links.
4. **Pick, merge, repeat.** "B with C's table" is one designer merging. Iterate until the owner says "this one".
   Many options, most of them bad, is fine: ask for ten, then remix
   (https://claude.com/blog/how-the-product-designer-who-built-claude-design-uses-it-to-explore-ideas-before-building-them).
5. **Freeze.** The chosen mock plus a `SPEC.md` that holds the owner's exact words on every disputed rule. Add nothing
   the owner did not ask for: a dark mode no one asked for is scope creep. Re-read `SPEC.md` after every context
   summary.
6. **Build logic first,** with a headless check (for a game: the rules, solvability, the generator). At most four
   workers, one unit each, and one checked milestone before any fan-out.
7. **Build the view** from the chosen mock, reusing its code. Check it by screenshot at phone and desktop width
   against the mock, and by opening the page; tests alone do not show a look
   (https://code.claude.com/docs/en/best-practices: "A browser screenshot next to the mockup").
8. **Polish and optimize last.** One auditor per built unit (`harness:audit`).

## Failure modes

| Failure | Instead |
|---|---|
| Building before the look is chosen | Steps 1-5 first |
| Ten broad agents at once | One variant per agent; one agent first on a new shape |
| A vague brief ("improve the CSS") | Name the file, the element and the done check |
| Requirements drifting across summaries | Re-read `SPEC.md` after each summary |
| Reporting a publish without opening it | Open the page and look before saying it works |

## What no tool checks

Whether the variants differ in idea and not only in colour, and whether the built view matches the chosen mock.
