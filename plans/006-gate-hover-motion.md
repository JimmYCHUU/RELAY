# 006 — Gate hover-lift motion behind a real pointer

- **Status**: DONE
- **Commit**: 18848ba
- **Severity**: LOW
- **Category**: Accessibility
- **Estimated scope**: 1 file (`relay/web/static/style.css`), ~10 lines

## Problem

Two rules move an element on `:hover` without gating for pointer type. On a touch
device a tap fires a synthetic hover that persists, so the element stays lifted
after the finger leaves — it looks stuck, and the lift no longer means anything.

```css
/* relay/web/static/style.css:211 — current */
button.primary:not([disabled]):hover { background: var(--accent-strong); transform: translateY(-1px); }
```

```css
/* relay/web/static/style.css:527-529 — current */
.drop:hover, .drop.dragover, .drop:focus-visible {
  border-color: var(--accent); transform: translateY(-1px); box-shadow: var(--shadow-lift); outline: none;
}
```

RELAY is a desktop tool, but the stylesheet explicitly anticipates small screens —
it has breakpoints at 1000px and 900px that hide the icon rail and reflow the panel
(`style.css:760-770`), so touch use is a designed-for case, not a hypothetical.

The `.drop` rule needs care: it shares its selector list with `.dragover` (set from
the drag handlers at `app.js:96-99`) and `:focus-visible`. Those two must keep the
lift on every device — a drag-over state and a keyboard focus state are not hovers.

## Target

Colour, border and shadow feedback stay universal. Only the 1px translation is
gated, and only for `:hover`.

```css
/* target — replacing style.css:211 */
button.primary:not([disabled]):hover { background: var(--accent-strong); }
@media (hover: hover) and (pointer: fine) {
  button.primary:not([disabled]):hover { transform: translateY(-1px); }
}
```

```css
/* target — replacing style.css:527-529 */
.drop:hover, .drop.dragover, .drop:focus-visible {
  border-color: var(--accent); box-shadow: var(--shadow-lift); outline: none;
}
/* drag-over and keyboard focus are not hovers — they lift on every device */
.drop.dragover, .drop:focus-visible { transform: translateY(-1px); }
@media (hover: hover) and (pointer: fine) {
  .drop:hover { transform: translateY(-1px); }
}
```

## Repo conventions to follow

- Media queries in this stylesheet are written inline next to the rule they
  modify when they are behavioural, and grouped at the bottom when they are
  layout breakpoints. Exemplar of the inline form: the reduced-motion block at
  `style.css:732`. Follow the inline form here — keep each `@media` block
  immediately below the rule it qualifies, not at the end of the file.
- Two-space indentation inside blocks; declarations for short rules stay on one
  line, as at `style.css:211`.

## Steps

1. In `relay/web/static/style.css`, replace line 211 with:

   ```css
   button.primary:not([disabled]):hover { background: var(--accent-strong); }
   @media (hover: hover) and (pointer: fine) {
     button.primary:not([disabled]):hover { transform: translateY(-1px); }
   }
   ```

2. In `relay/web/static/style.css`, replace lines 527–529 with:

   ```css
   .drop:hover, .drop.dragover, .drop:focus-visible {
     border-color: var(--accent); box-shadow: var(--shadow-lift); outline: none;
   }
   /* drag-over and keyboard focus are not hovers — they lift on every device */
   .drop.dragover, .drop:focus-visible { transform: translateY(-1px); }
   @media (hover: hover) and (pointer: fine) {
     .drop:hover { transform: translateY(-1px); }
   }
   ```

3. Do not touch any other `:hover` rule. The remaining ones change only colour,
   background, border-color, box-shadow or text-decoration, which are safe on
   touch. Confirm this with
   `grep -n ':hover' relay/web/static/style.css` — none of the other matches
   contain `transform`.

## Boundaries

- Do NOT gate `.dragover` or `:focus-visible` behind the media query. A keyboard
  user on a touch-capable laptop must still see the focus lift.
- Do NOT move these media queries to the breakpoint section at the end of the
  file — they are behavioural, not layout.
- Do NOT add `@media (hover: hover)` around rules that only change colour.
- Do NOT touch `relay/web/static/app.js` or `relay/web/static/index.html`. The
  `.dragover` class toggling at `app.js:96-99` is correct.
- Do NOT add new dependencies.
- If lines 211 or 527–529 do not match the excerpts above (drift since commit
  18848ba), STOP and report instead of improvising.

## Verification

- **Mechanical**: `grep -c 'hover: hover' relay/web/static/style.css` returns `2`.
  `grep -n ':hover' relay/web/static/style.css | grep transform` returns only the
  two lines inside the new media queries.
- **Feel check**, desktop first:
  - Hover a primary button and a drop zone — both still lift 1px, exactly as before.
  - Tab to a drop zone with the keyboard — it lifts and shows its focus ring.
  - Drag a file over a drop zone without releasing — it lifts and the border turns
    accent-coloured.
- **Feel check**, touch: in DevTools, open the device toolbar (Ctrl/Cmd+Shift+M)
  and pick a phone preset, then reload so the pointer media features re-evaluate.
  - Tap a drop zone: its border and shadow may change, but it must **not** lift,
    and must not stay lifted after the tap.
  - Tap a primary button: background changes, no lift, nothing stuck.
- **Done when**: the lift appears on mouse hover, drag-over and keyboard focus, and
  never on a touch tap.
