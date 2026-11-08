# CSS reference

## Naming
- Component prefix: `.card`, `.card-title`, `.card-actions`; modifiers `.card-wide`; states `.is-open`, `.has-error`.
  BEM (`.card__title--wide`) is equally valid; one scheme per project, and the existing one wins.
- Names say what the thing is, not how it looks (`.alert`, not `.red-box`). No abbreviations.
- Ids are never selectors; element selectors only in the reset or base layer.

## Specificity budget
- Target one class (0,1,0); a state adds one class or pseudo-class (0,2,0); stop there.
- Never raise specificity to win: change the order, the layer, or the other selector. Use `:where()` to lower a reset
  or base rule to zero.
- `!important` only on `[hidden]` and the reduced-motion block of the base.

## Layers
```css
@layer reset, tokens, base, components, utilities;
```
Unlayered CSS beats layered CSS, so a project that uses layers puts all its CSS in one. Later layers win regardless of
specificity, which is why a component cannot restyle a shared piece by selector weight.

## Tokens
- Groups: colour (semantic: `--color-text`, `--color-border`, `--color-danger`), space (`--space-1..n` on one scale),
  radius, type size and weight, line height, duration, easing, z-index, shadow.
- Name by role, not value (`--color-danger`, not `--color-red-500` in components). Components read semantic tokens
  only; palette tokens feed semantic ones.
- Zero, `auto`, `100%`, unitless line-heights and `1px` borders are not tokens.
- Dark mode, if supported, redefines semantic tokens under `@media (prefers-color-scheme: dark)` or a root attribute;
  components do not change.

## Layout
- `display: flex` and `grid` with `gap`; avoid negative margins, floats and fixed heights.
- `min-width: 0` on flex or grid children that hold long text; wrap long strings with `overflow-wrap: anywhere`
  instead of cutting them when the text matters.
- Container query: `container-type: inline-size` on the wrapper, `@container (min-width: 30rem)` in the component.
  Media queries for page-level changes. Breakpoints are tokens-by-convention: declare them once and reuse the same values.
- `aspect-ratio` over padding hacks. `100dvh` over `100vh` for full-height mobile layouts.
- `z-index` values come from a scale; a new stacking context is made on purpose (`isolation: isolate`).

## Focus, motion, contrast
```css
:focus-visible { outline: 2px solid var(--color-focus); outline-offset: 2px; }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
}
```
- Animate `opacity` and `transform`; keep durations short (about 100 to 300 ms) and use duration tokens.
- Do not set `outline: none` on a control unless `:focus-visible` gives an equal or stronger indicator.
- Check contrast in each state (hover, disabled text may be exempt, selected, error) and on every surface the text
  sits on.

## Shared styles (when the project has them)
- A component sets layout only (flex, width, margin, position) on an element that also carries a shared class; to
  change colour, weight or opacity it drops the shared class and styles its own.
- Before writing a class, search the shared files for it; no hit means add it there first, in the same change.
- A shared file carries no component names; variants are modifiers of the shared class.

## Size and files
- One component per file.
- JavaScript never writes colours or looks through `element.style`; a run-time size may be handed over with
  `style.setProperty("--name", value)` and read by CSS.

## Checkable greps
- Raw colours outside the tokens file: `rg -n '#[0-9a-fA-F]{3,8}\b|(rgba?|hsla?|oklch|oklab)\(' --glob '*.css'`.
- `!important`, id selectors and `outline: none`: `rg -n '!important|^\s*#[A-Za-z]|outline:\s*(none|0)' --glob '*.css'`.
