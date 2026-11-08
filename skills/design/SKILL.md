---
name: design
description: General design rules for pages, layouts, diagrams and mock-up rounds - reading order, density, progressive disclosure, plain words, light and dark themes, contrast, focus, motion. Load before designing or reviewing a visual deliverable. Code rules are in harness:code-html-css.
---

# Design

How a page should read. How it is written in HTML and CSS is `harness:code-html-css`; this skill never repeats it.

## Reading order and hierarchy

- One page, one point. The title says it; the first screen answers it.
- The eye goes top-left to bottom-right: the most important thing comes first, the detail after it.
- Three levels of emphasis at most (title, section, body). Size, weight and space carry hierarchy; colour only backs it.
- Group by meaning. Space between groups is larger than space inside one.

## Look and reference

Before building, write two lines: the look (theme, palette, density) and the structure of one real product or page it
follows, in words (for example "a sidebar of grouped items, one wide table, a sticky header"). Take the structure, never
brand art. A page with no tokens starts from `references/tokens.md`.

## Focal point

- One leading element per screen: the one the page exists for, larger, heavier or higher in contrast than the rest.
- Filler (placeholder rows, secondary lists, chrome) sits at the edges and stays quiet, never where the eye lands.
- Self-test, asked of every screen: "Where does the eye land first?" and "Is one thing clearly leading?" A doubtful
  answer sends you back to size, weight and space.

## Density

- Use the width: a reader on a wide screen sees columns, tables and side-by-side parts, not a narrow strip of text.
- Little scroll. If the page needs a long scroll, cut or fold it.
- One idea per area: a card, a row or a panel holds one thing, with a short heading.
- A line of running text stays readable (about 60 to 80 characters); wide space goes to layout, not to longer lines.

## Progressive disclosure

- Show the answer first, the proof on demand (a fold, a tab, a link). The reader who stops early still has the point.
- A tab or fold hides detail, never the thing the page exists to say.
- Never hide content behind hover alone; touch and keyboard users cannot reach it.

## Component states

Design each state of every interactive part, not the browser default: default, hover, focus, active, disabled, empty,
error, loading. Empty says what goes here and the next step; error sits beside the cause and says how to fix it;
loading keeps the final layout (a skeleton of the real geometry); disabled stays readable and says why when it can.

## Anti-patterns

- Every object the same weight in the same bordered card: the eye has nowhere to land. Vary size and surface.
- A window shrunk into a card with even margins: a pasted screenshot. Let it fill the area and run off an edge.
- Generic AI styling: purple gradients, sparkles, a letter in a coloured square standing for a logo.
- Grey text everywhere, so hierarchy is flat. Body text is strong; only captions are muted.
- Busy rows with uneven insets: one inset per row type, text on a shared baseline and edge.
- Loud decoration (gradients, glows, big icons) that outweighs the content.
- Controls floating alone with no alignment to the grid or to a neighbour's edge.
- Real words in every row and numbers everywhere: real text only where the point is, placeholders elsewhere.
- A border and a shadow and a fill on one shape: pick one.

## Words

- Plain, didactic words for a reader who will not deep dive: say what it is, what it does, why it matters.
- Short sentences, active voice, the same word for the same thing. Define a term where it first appears.
- A label says what the control does; a heading says what the section holds.

## Colour, contrast, focus, motion

- A light theme by default and a dark theme beside it (`prefers-color-scheme`, and a visible switch if the page has one).
  Both are designed, not inverted.
- Text meets contrast 4.5:1 (3:1 for large text and interface parts), in both themes. Meaning never rides on colour alone.
- Focus is always visible and follows reading order.
- Motion is small and has a purpose; `prefers-reduced-motion` turns it off.
- No brand art and no logos: shapes, type and space only.

## A diagram

- Draw only a mechanism a sentence cannot carry. Label the arrows; one flow direction; few boxes.
- It reads in both themes and at 320px, or is replaced there by a list.

## A mock-up round

The process around a round (offer, brief, pick, freeze, build) is `harness:explore`. When the owner wants options, make N variants, each a different idea named by it (for example "one dense table",
"cards by audience", "a guided path"), not N palettes of one layout. Each opens on the same real content, so the
difference is the design. End with one line per variant: the idea, what it does best, what it gives up. Recommend one
and say why; the owner chooses.

## Checking

- A parser confirms the markup is well formed; a width of 320px confirms nothing overflows sideways.
- A parser and a narrow-width check settle structure; they cannot judge looks.
- In a visual round, each variant gets a screenshot at about 1280px and one at the narrowest width the renderer allows.
  View both and critique them against Anti-patterns and Focal point before the report. The report names what the
  critique changed. Outside a visual round, a screenshot only when asked: it is slow.
