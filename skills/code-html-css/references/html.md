# HTML reference

## Page skeleton
```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Page name</title>
  </head>
  <body>
    <header>...</header>
    <nav aria-label="Main">...</nav>
    <main>
      <h1>Page name</h1>
    </main>
  </body>
</html>
```

## Controls
- Several `nav` landmarks each get a distinct `aria-label`.
- A group of radios or checkboxes sits in `<fieldset>` with a `<legend>`.
- Input `type` matches the data (`email`, `number`, `search`), with `autocomplete` where it applies; the error message
  is linked with `aria-describedby`.
- Icon-only button: `<button type="button" aria-label="Close">` with the icon marked `aria-hidden="true"`.
- A link that opens in a new tab says so in its text, and carries `rel="noopener"`.
- A dialog is `<dialog>`; focus moves in on open and returns to the opener on close.
- Live updates that the user must hear use `aria-live="polite"` on a container that exists from page load.

## Images and media
- Informative: `alt` states the content or the action ("Download report"). Decorative: `alt=""`. A chart: `alt` gives
  the conclusion, the data sits in a table or the text beside it.
- Set `width` and `height` (or an aspect ratio) so the page does not shift while loading; `loading="lazy"` below the
  fold.
- Video with speech has captions.

## Headings and structure
- Outline check: list the headings in order; each is the same level or one deeper than the last.
- A `section` or `article` has a heading; otherwise use `div`.

## Hooks and state
- Script finds elements by a `data-*` hook (`data-part="list"`), CSS styles by class; neither crosses.
- State read by assistive tech is an ARIA attribute (`aria-expanded`, `aria-pressed`, `aria-current`); styling may use
  the same attribute selector. Visual-only state is a class.
- Tooltips: text lives in an attribute or element the script reads; the control still has its own accessible name.

## Framework markup
Components render the same elements; a prop that renders a `div` with a click handler is replaced by a `button`.
Keys, ids and `htmlFor` follow the framework; ids stay unique when a component repeats.
