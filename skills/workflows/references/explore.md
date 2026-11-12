# Explore before building

Building before the look is chosen costs days. Choose the look on cheap mocks, freeze it, then build.
Designer-side rules for a variant: `harness:design`. Games: `games.md`.

## The loop

1. **Offer.** A request for something visual or interactive gets "want a few mocks first?" before any build. Skip only
   for a small change to an existing look.
2. **Diverge.** Several designers in parallel, one variant per agent, each clearly different along a named axis
   (layout, density, metaphor, flow). When the shape is new, try one agent before fanning out.
3. **Label.** Variants carry a letter or number, so the owner picks in one message. Send screenshots and links.
4. **Pick, merge, repeat.** "B with C's table" is one designer merging. Iterate until the owner says "this one".
   Many options, most of them bad, is fine: ask for many, then remix
   (https://claude.com/blog/how-the-product-designer-who-built-claude-design-uses-it-to-explore-ideas-before-building-them).
5. **Freeze.** The chosen mock plus a `SPEC.md` that holds the owner's exact words on every disputed rule. Add nothing
   the owner did not ask for: a dark mode no one asked for is scope creep. Re-read `SPEC.md` after every context
   summary.
6. **Build logic first,** with a headless check (for a game: the rules, solvability, the generator), and one checked
   milestone before any fan-out.
7. **Build the view** from the chosen mock, reusing its code, on the surface the owner will look at (a desktop app, a
   terminal, a browser): ask which before the brief, and probe that surface's richest element first, so the build does
   not fall back to a poorer one. Check it by screenshot at phone and desktop width
   against the mock, and by opening the page; tests alone do not show a look
   (https://code.claude.com/docs/en/best-practices: "A browser screenshot next to the mockup").
8. **Polish and optimize last.** One reviewer at the end (`harness:review`).

## Briefing a page or a mock

These add to the sender's checks of `harness:orchestrator` (its brief-checks reference).

- A mock brief gives placeholder data, so the look is judged and not the content, and asks for static HTML.
- It says whether the page must work opened from `file://`; a module script does not run there.
- It gives the width at the target (characters per line, px per column) and asks each text end to be checked against
  its neighbour's edge before the first render, so the first render fits.
- It says which controls are drawn shapes and which are real buttons, and whether a trace shows its states.
- A brief that asks for a browser render names the command that drives one on this machine.
- A judge of a look names how to set the theme it checks. One that adds a colour state asks for its contrast in both
  themes and on hover.
- A layout judge is checked against the reference screenshot first: it must not assert a row or an edge the reference
  does not have.
- A fix brief says what to do with a layout fault outside its items (an overflow, a cut-off popover): fix it, or list
  it under Open.

## Failure modes

| Failure | Instead |
|---|---|
| Building before the look is chosen | Steps 1-5 first |
| Many broad agents at once | One variant per agent; one agent first on a new shape |
| A vague brief ("improve the CSS") | Name the file, the element and the done check |
| Requirements drifting across summaries | Re-read `SPEC.md` after each summary |
| Reporting a publish without opening it | Open the page and look before saying it works |

## What no tool checks

Whether the variants differ in idea and not only in colour, and whether the built view matches the chosen mock.
