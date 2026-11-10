---
name: code-html-css
description: HTML and CSS rules for any web repo, with or without a framework - semantic accessible markup, tokens, shallow class selectors, layers, visible focus, reduced motion, narrow screens. Load before writing, moving or reviewing .html or .css.
---

# HTML and CSS

Script side: `harness:code-js`. No comments or docstrings: `harness:comments`. Long lists and examples: `references/html.md`,
`references/css.md`. A rule marked (if) applies only when the project has the thing it names.

## HTML

- `<!doctype html>`, `<html lang>`, `charset` and `viewport` metas, a `<title>`. No build step for our own code unless
  the project has one. In a framework, the same rules apply to the markup its templates produce.
- Two-space indent, lower-case tags and attributes, double-quoted values. Follow the file you edit for long tags.
- Semantic elements first: `header`, `nav`, `main`, `aside`, `footer`, `section` with a heading, `ul`/`ol` for lists,
  `table` for tabular data. `div` and `span` only when nothing else fits. `role` and `aria-*` only when no native
  element fits.
- One `<h1>` per page; heading levels descend without a skip, chosen by structure and not by size.
- Action is a `<button type="button">`; navigation is an `<a href>`. A clickable `div` is a defect.
- Every control has a name: a `<label>` (`for` or wrapping) or an `aria-label`; an icon-only button always has one.
- Images have `alt` saying what they show or do; empty `alt=""` when decorative. Never "image of".
- Hidden state uses the `hidden` attribute; the base CSS keeps `[hidden] { display: none !important }` (one of the two allowed
  `!important` uses, the other being the reduced-motion block).
- No inline `style` attribute, no inline event handlers (`onclick=`), no `title` as the only label.
- Script hooks are `data-*` attributes (or ids used only by `for`, anchors and `aria-*`), not styling classes; CSS does
  not select by them, except state exposed as `[data-state]`-style attributes the project documents.
- Never build markup with `innerHTML` from untrusted text; build elements and set text.
- Do not use `tabindex` above 0. Do not remove an element from the tab order to hide a focus problem.

## CSS

- Plain CSS unless the project has a preprocessor. Two-space indent, one declaration per line, a blank line between
  rules, lower-case hyphenated class names.
- Name by one scheme per project (component prefix such as `card`, `card-title`; or BEM): a selector starts with its
  component's name or is a state class (`is-open`, `has-error`). State is set by toggling a class, not by inline style.
- Selectors stay shallow: at most 3 compound parts. No id selectors, no element-qualified classes (`div.card`), no
  `!important` except the `[hidden]` rule and the reduced-motion block. Fix a specificity clash by lowering the other selector or by layer order.
- (if the project defines tokens) every colour, space, radius, font size, weight, duration and z-index is `var(--name)`
  from the tokens file; a raw hex or a non-zero `px` (except 1px borders and hairlines) appears only there. Without tokens: a value used more than once is a
  custom property on `:root`.
- (if the project uses `@layer`) the order is declared once, lowest first (reset, tokens, base, components, utilities);
  a rule goes in the layer of its kind and never reaches into another component's classes.
- (if the project has a shared stylesheet) reuse its class before writing one; a new look is a variant there, not a
  copy in a component; a component only adds layout on top of a shared class.
- Logical properties (`margin-inline`, `padding-block`, `inset-inline-start`) over left/right. Spacing with `gap` and
  padding, not margin hacks, spacer elements or `&nbsp;`.
- Responsive: mobile first; a component that sits in several widths uses a container query, the page frame uses media
  queries. Relative units (`rem`, `%`, `fr`, `ch`) for type and layout; `px` for borders and hairlines.
- Visible focus is kept: `:focus-visible` has a clear outline and is never `outline: none` without a replacement. A
  hover affordance has a keyboard path.
- Motion honours `@media (prefers-reduced-motion: reduce)`; animate `opacity` and `transform`, short durations.
- Text colour against its background meets WCAG AA (4.5:1 body, 3:1 large text and controls); state is never colour
  alone.
- One component per CSS file; split by component, not by line count. A value's meaning goes in its custom property's name.

## Order of work for a new fragment

1. Read the neighbours: the nearest component's HTML and CSS, and the shared stylesheet and tokens if any.
2. Reuse a shared class; a missing token or class is added where the project keeps it, not hard-coded.
3. Write the markup (semantic, labelled), then layout, then states by class.
4. Check by keyboard (tab order, focus visible, Escape closes), at the narrow width of `harness:design` (Checking), with reduced motion, and the contrast
   of each text colour.
5. Run the project's gate; look at the page (console clean; a screenshot only when the owner or the brief asks).

## Enforcing tools

- Use the project's own gate first. Biome (its starter is in `harness:code-js`) formats and lints CSS;
  Prettier formats HTML and CSS; Stylelint (with its standard config) can flag id selectors, `!important`,
  duplicate selectors and unknown properties, and with plugins or rules can ban raw colours or enforce a class pattern;
  html-validate (or the W3C validator) flags invalid nesting, missing `alt`, missing `lang`, duplicate ids and
  unlabelled controls.
- Browser check: open the page, read the console, and, only when the owner or the brief asks, take a headless screenshot at a typical
  monitor size and at a narrow one.

## What no tool checks

Whether the markup is semantic, whether names say what an element is, heading structure, alt text quality, keyboard
behaviour, contrast in context, reduced-motion behaviour and the visual result. The reviewer reads the markup and looks
at screenshots.
