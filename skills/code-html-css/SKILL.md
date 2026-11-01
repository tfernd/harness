---
name: code-html-css
description: General HTML and CSS rules - plain markup, accessible controls, alt text, lang, plain CSS, custom properties, shallow selectors, visible focus. Load before writing, moving or reviewing any .html or .css file.
---

# HTML and CSS

Script side: `harness:code-js`. Comments: `harness:comments`.

## HTML

- Plain HTML, `<!doctype html>`, `<html lang>`, `charset` and `viewport` metas, a `<title>`. No framework and no build
  step for our own code unless the project has one.
- Two-space indent, lower-case tags and attributes, double-quoted values. One block element per line; inline elements may share a line
  with their text. Follow the file you edit when a long tag is kept on one line.
- Interactive controls are real `<button type="button">`, `<a href>`, `<input>` with an `aria-label` or a `<label>` (`for` or wrapping);
  a landmark (`nav`, `main`, `aside`) where it applies; `role` and `aria-*` only when no native element fits.
- Images have `alt` (empty when decorative).
- Hidden state uses the `hidden` attribute, and the base CSS keeps `[hidden] { display: none !important }`.
- Never build markup with `innerHTML` from untrusted text; build elements and set text.
- No inline `style` attributes; a value comes from a class.

## CSS

- Plain CSS, no preprocessor. Two-space indent, one declaration per line, a blank line between rules, lower-case
  hyphenated class names.
- A value used more than once (colour, size, spacing, radius, font, duration, z-index) is a custom property declared
  once on `:root`, not repeated as a literal.
- Selectors stay shallow: a class, a state class or a pseudo-class. No id selectors, and no `!important` except the
  `[hidden]` rule.
- Visible focus is kept (`:focus-visible`), and pointer-only affordances have a keyboard path.
- A comment explains a trap or why a value is what it is, one line above the rule.

## Enforcing tools

- Use the project's own gate. Without one: Biome (`harness:code-js`,
  `references/biome-tsconfig.md`) formats and lints CSS; an HTML check is a manual read. Browser check: open the page,
  read the console, and, for visual work, take a headless screenshot at a typical monitor size.

## What no tool checks

Whether the markup is semantic and accessible, whether names say what an element is, keyboard behaviour, and the visual
result. The reviewer reads the markup and looks at a screenshot.
