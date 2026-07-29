# 010 — Give the cell editor a fast entrance

- **Status**: DONE
- **Commit**: 18848ba
- **Severity**: LOW
- **Category**: Missed opportunity — preventing a jarring change
- **Depends on**: 001 (needs `var(--ease-out)`)
- **Estimated scope**: 1 file (`relay/web/static/style.css`), ~10 lines

## Problem

The cell editor is the app's only modal. It and its blurred backdrop appear over
the review table in a single frame, with no bridge:

```js
/* relay/web/static/app.js:650 — current, at the end of openCellEditor */
  dialog.showModal();
```

```css
/* relay/web/static/style.css:741-745 — current */
dialog {
  border: 1px solid var(--grid); border-radius: 16px; background: var(--surface); color: var(--ink);
  padding: 22px 24px; width: min(440px, 92vw); box-shadow: var(--shadow-lift);
}
dialog::backdrop { background: rgba(12,14,22,.45); backdrop-filter: blur(2px); }
```

## Target

An entrance at **150ms** — deliberately below the usual 200–500ms modal budget.
This dialog is not opened once and considered; it is reopened in a tight loop by
the **Apply → next missing** button, which chains straight into the next unresolved
cell:

```js
/* relay/web/static/app.js:686-689 — why the budget is tight */
  if (wantNext) {
    const next = nextMissingCell(rowNo, slot);
    if (next) setTimeout(() => openCellEditor(next.rowNo, next.slot), 0);
  }
```

Anything slower turns a forty-cell correction pass into a slog.

```css
/* target — relay/web/static/style.css:741-745 */
dialog {
  border: 1px solid var(--grid); border-radius: 16px; background: var(--surface); color: var(--ink);
  padding: 22px 24px; width: min(440px, 92vw); box-shadow: var(--shadow-lift);
  opacity: 1; transform: scale(1);
  transition: opacity 150ms var(--ease-out), transform 150ms var(--ease-out);
}
@starting-style {
  dialog[open] { opacity: 0; transform: scale(0.97); }
}
dialog::backdrop {
  background: rgba(12,14,22,.45); backdrop-filter: blur(2px);
  opacity: 1; transition: opacity 150ms var(--ease-out);
}
@starting-style {
  dialog[open]::backdrop { opacity: 0; }
}
```

Three deliberate choices:

- **`scale(0.97)`, not `scale(0)`** — nothing appears from nothing.
- **No `transform-origin`** — modals are the exception to the scale-from-trigger
  rule; they belong in the centre of the viewport, and the default
  `transform-origin: center` is correct here. Do not add one.
- **Entrance only.** Closing stays instant. An exit animation would need
  `transition-behavior: allow-discrete` plus `overlay`, and would add latency to
  every step of the Apply → next chain — the opposite of what this dialog needs.

`@starting-style` needs Chrome 117+, Safari 17.5+ or Firefox 129+. RELAY runs in
the operator's local browser and already depends on Playwright's Chromium, so this
is safe; on anything older the dialog simply appears instantly, as it does today.

## Repo conventions to follow

- Dialog styles live in the `/* ═════════ dialog & tooltip ═════════ */` section
  at the end of `style.css` (lines 740-758). Keep both `@starting-style` blocks in
  that section, each directly beneath the rule it initialises.
- The stylesheet already uses modern CSS without fallbacks where the target
  browser supports it — `color-mix(in srgb, …)` at `style.css:275` and
  `@media (prefers-reduced-motion)` at 732. `@starting-style` fits that bar.

## Steps

1. In `relay/web/static/style.css`, replace lines 741–745 in their entirety with
   the target block quoted above under **Target** (the `dialog` rule, the first
   `@starting-style` block, the `dialog::backdrop` rule, and the second
   `@starting-style` block).

2. Change nothing in `relay/web/static/app.js`. The `showModal()` call at line
   650 and the `close` handler at line 673 stay exactly as they are.

## Boundaries

- Do NOT add `transform-origin` to the dialog.
- Do NOT add an exit/close animation, `transition-behavior: allow-discrete`, or
  `overlay` to the transition list.
- Do NOT increase the 150ms duration.
- Do NOT touch the `.tooltip` rules at `style.css:751-758` — the tooltip follows
  the pointer on every mousemove (`app.js:1114-1118`) and must stay instant.
- Do NOT touch `relay/web/static/app.js` or `relay/web/static/index.html`.
- Do NOT add new dependencies.
- If lines 741–745 do not match the excerpt above (drift since commit 18848ba),
  STOP and report instead of improvising.

## Verification

- **Mechanical**: `grep -c '@starting-style' relay/web/static/style.css` returns
  `2`. `grep -n 'transform-origin' relay/web/static/style.css` returns nothing.
- **Feel check**:
  1. Load a campaign sheet, run matching, open **Match Review**.
  2. Hover a table row and click the ✎ pencil in any cell. The dialog should grow
     very slightly into place as the backdrop darkens — quick enough that it reads
     as responsiveness, not as an animation.
  3. Type a number and press **Apply → next missing** several times in a row. The
     chained reopenings must still feel immediate. If the loop starts to feel
     laggy, the duration is too long — report it rather than raising it.
  4. Press **Cancel** or Escape: the dialog closes instantly. That is intended.
  5. In DevTools → Animations, set playback to 10% and reopen: confirm the dialog
     scales up from slightly small and does not start from nothing, and that the
     backdrop fades in alongside it rather than after it.
  6. In DevTools → Rendering, enable **Emulate CSS prefers-reduced-motion**: the
     dialog and backdrop should fade without scaling.
- **Done when**: the dialog and its backdrop ease in together at 150ms, closing is
  instant, and the Apply → next chain still feels immediate.
