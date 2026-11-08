# A starter system for a page with no tokens

Use this only when the project defines none; a project's own tokens win. Name and write them as custom properties by
`harness:code-html-css`. Values below are a start: change a value, keep the ratios.

## Type scale (5 to 6 steps)

| Step | Size | Line height | Use |
|---|---|---|---|
| caption | 12px | 16px | labels, meta, table footers |
| body | 14px or 16px | 1.5 | running text, controls |
| lead | 18px | 1.45 | the sentence under a title |
| title | 24px | 1.3 | section heading |
| display | 36px | 1.15 | page title, one per page |
| hero | 56px | 1.05 | only a landing view, with tight tracking |

- Big text gets a tighter line height and slightly negative tracking; small text gets looser line height.
- Two weights (regular 400, strong 600) carry most pages. One family; a second only for code (monospace).

## Spacing (4/8 px)

Steps: 4, 8, 12, 16, 24, 32, 48, 64. Inside a component use 4 to 16; between components 24 to 32; between sections
48 to 64. Equal insets on every side of a card unless the content is a row, which gets block inset smaller than inline.

## Radii and borders

- Two radii: small (6px) for controls and chips, large (12px) for cards and panels. A pill (999px) only for status chips.
- A nested shape has a radius equal to the outer radius minus the gap between them.
- A border is 1px in a low-contrast neutral. Separate by space or a surface step before adding a border; never box every item.

## Colour

- One accent, used for the primary action, the selected state and links. Everything else is neutral.
- A neutral ramp of about 9 steps from the ground to the strongest text, each theme its own ramp:

| Role | Light | Dark |
|---|---|---|
| ground | #ffffff | #0f1115 |
| surface (card) | #f6f7f9 | #171a21 |
| raised (popover) | #ffffff | #1e222b |
| line | #e3e6eb | #2a2f3a |
| muted text | #5b6472 | #9aa3b2 |
| text | #14171c | #eceff4 |
| accent | #2f5bea | #7d9bff |

- Check contrast per theme (`harness:design`). Muted text is for captions only; body text uses the strong step so
  hierarchy comes from size and weight, not from grey.
- A dark theme steps surfaces lighter as they rise; it does not use shadows for depth.

## A hue for each kind of thing

- Give each kind of thing (for example a type of record, a person, a status) one hue, fixed everywhere it appears: same
  chip, dot, row marker and chart colour.
- At most 5 hues beside the accent, spaced round the wheel, at equal lightness and chroma so none shouts.
- Status uses the conventional hues (success green, warning amber, error red) with a text or icon beside them.
- Show a hue as a small mark (dot, 3px edge, tinted chip), not a filled block.

## Shadow

- Two levels: a small one for cards that lift on hover (soft, 0 1px 2px at 8% black) and a large one for popovers and
  dialogs (0 8px 24px at 12% black). Never a coloured or hard shadow.
- A card at rest uses a surface step or a hairline border, not both and not a shadow.
