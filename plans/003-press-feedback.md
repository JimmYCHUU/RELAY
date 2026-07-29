# 003 — Add press feedback to primary and ghost buttons

- **Status**: DONE
- **Commit**: 18848ba
- **Severity**: MEDIUM
- **Category**: Physicality & origin
- **Depends on**: 001 (needs `var(--ease-out)`)
- **Estimated scope**: 1 file (`relay/web/static/style.css`), ~8 lines added

## Problem

`relay/web/static/style.css` contains **no `:active` rule at all**. Verify before
starting: `grep -n ':active' relay/web/static/style.css` returns nothing. (The many
`.active` matches are a class used for selected tabs and rail items — unrelated.)

Buttons respond to hover but not to being pressed:

```css
/* relay/web/static/style.css:199-204 — current: the transform leg of this
   transition exists solely for the hover lift; nothing uses it on press */
button, a.ghost {
  font: inherit; font-weight: 650; border-radius: 10px; padding: 9px 16px;
  cursor: pointer; border: 1px solid transparent; text-decoration: none;
  display: inline-flex; align-items: center; justify-content: center; gap: 8px;
  transition: transform .1s, box-shadow .15s, background .15s, opacity .15s;
}
```

```css
/* relay/web/static/style.css:211 — current */
button.primary:not([disabled]):hover { background: var(--accent-strong); transform: translateY(-1px); }
```

This matters most on the app's slow actions. Pressing **Run matching →**
(`index.html:214`) starts a multi-second server round-trip whose only
acknowledgement is a text swap that arrives after the first response
(`app.js:211-212`). **Autopilot** (`index.html:243`) and **Generate .xlsx**
(`index.html:398`) have the same shape. Between click and response the interface
says nothing at all.

## Target

A subtle press-down on the two button families that carry deliberate,
cycle-level actions, at the top of the 100–160ms feedback budget.

```css
/* target — appended after the last button rule in style.css */
button.primary:not([disabled]):active,
button.ghost:not([disabled]):active,
a.ghost:active { transform: translateY(0) scale(0.97); }
```

`translateY(0)` is explicit so a press cleanly overrides the hover lift instead of
compounding with it.

The transform leg of the base transition moves to the token curve and 120ms:

```css
/* target — relay/web/static/style.css:203 */
  transition: transform 120ms var(--ease-out), box-shadow 150ms ease, background 150ms ease, opacity 150ms ease;
```

Note this same transform transition also drives the 1px hover lift. `--ease-out` on
a 1px translation is imperceptibly different from `ease`; the press is the
interaction worth tuning for.

**Deliberately excluded**: `button.cell-edit` (`style.css:651`), the pencil icon in
every table cell. It is pressed dozens of times in a single correction pass, which
is the frequency tier where press animation reads as sluggishness. Its existing
`opacity` reveal on row hover is the right amount of feedback and stays untouched.
Also excluded: `.nav-item`, `.tab`, `.segbtn`, `.ctab`, `.qa`, `.link-btn` — all
frequent toggles or navigation.

## Repo conventions to follow

- Button rules live in the `═════════ buttons & inputs ═════════` section,
  `relay/web/static/style.css:198-236`, ordered base → variants → disabled states.
- Disabled buttons are excluded with `:not([disabled])`, exactly as at
  `style.css:211` and `style.css:217`. Follow that pattern; `a.ghost` has no
  disabled variant so it takes no `:not()`.
- Multi-selector rules are written one selector per line when they exceed the
  line width — exemplar at `style.css:729-730`.

## Steps

1. In `relay/web/static/style.css`, replace line 203 with:

   ```css
     transition: transform 120ms var(--ease-out), box-shadow 150ms ease, background 150ms ease, opacity 150ms ease;
   ```

   (If plan 001 has already run, the current text will be
   `transition: transform 100ms ease, box-shadow 150ms ease, background 150ms ease, opacity 150ms ease;`
   — replace it just the same.)

2. In `relay/web/static/style.css`, find the last rule of the button block,
   currently line 218:

   ```css
   button.ghost[disabled] { opacity: .45; cursor: not-allowed; }
   ```

   Insert immediately **after** it:

   ```css
   /* press feedback — deliberately not on .cell-edit, which is pressed dozens of
      times per correction pass */
   button.primary:not([disabled]):active,
   button.ghost:not([disabled]):active,
   a.ghost:active { transform: translateY(0) scale(0.97); }
   ```

   Placement matters: this must come **after** every `:hover` rule in the block so
   it wins on equal specificity.

## Boundaries

- Do NOT add `:active` to any other selector — not `.cell-edit`, `.nav-item`,
  `.tab`, `.segbtn`, `.ctab`, `.qa`, `.link-btn`, `.iconbtn`, `.iconlink`,
  `.stop-btn`, or `.cycle-chip button`.
- Do NOT change the scale value. 0.97 is inside the 0.95–0.98 band; 0.9 is not.
- Do NOT change any `:hover` rule. Plan 006 owns those.
- Do NOT touch `relay/web/static/app.js` or `relay/web/static/index.html`.
- Do NOT add new dependencies.
- If line 203 or line 218 does not match the excerpts above (drift since commit
  18848ba), STOP and report instead of improvising.

## Verification

- **Mechanical**: `grep -c ':active' relay/web/static/style.css` returns `3`.
- **Feel check**: start the app and open **Data Sources**.
  - Press and hold **Run matching →**: it should sink slightly and stay sunk
    while held, then spring back on release. The motion must be small enough that
    you notice the *responsiveness*, not the animation.
  - Press and hold, then drag the pointer off the button before releasing: it
    should return to rest.
  - Hover **Run matching →** without pressing: it still lifts 1px as before.
  - Go to **Match Review**, hover a table row, and press the ✎ pencil: it must
    **not** scale. Confirm this explicitly — it is the main scoping risk.
  - In DevTools → Animations, set playback to 10%, then press a primary button:
    the press should decelerate into its resting sunk state, not move linearly.
  - In DevTools → Rendering, enable **Emulate CSS prefers-reduced-motion**: after
    plan 004, the press should stop moving but the button's background still
    responds.
- **Done when**: every `.primary` and `.ghost` button gives press feedback, no
  other control does, and hover behaviour is unchanged.
