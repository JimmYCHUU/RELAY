# 004 — Replace the blanket reduced-motion kill with a gentler floor

- **Status**: DONE
- **Commit**: 18848ba
- **Severity**: MEDIUM
- **Category**: Accessibility
- **Estimated scope**: 1 file (`relay/web/static/style.css`), ~8 lines

## Problem

```css
/* relay/web/static/style.css:732-738 — current */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important; animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
  html { scroll-behavior: auto; }
}
```

This is the widely-copied "nuke everything" snippet. It reduces motion to zero
rather than reducing it, which is not what the preference asks for: users who set
it want position changes and spinning gone, not the loss of every transition that
helps them follow what changed. Under this rule a RELAY user with the preference
set gets:

- no fade on hover feedback anywhere,
- no colour transition when a cell fills,
- and, because it uses `!important` on `*`, **every improvement made by the other
  plans in this directory is silently flattened too**.

`html { scroll-behavior: auto; }` is a no-op here — the stylesheet never sets
`scroll-behavior: smooth`, and `app.js:50` already scrolls without `behavior`.
It is harmless and can stay as a guard.

## Target

Keep opacity and colour transitions — the ones that aid comprehension — at a
calm 120ms. Drop everything that moves.

```css
/* target — relay/web/static/style.css:732-738 */
@media (prefers-reduced-motion: reduce) {
  /* reduced motion means gentler, not none: colour and opacity feedback stays,
     everything that moves is dropped */
  *, *::before, *::after {
    animation-duration: 120ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 120ms !important;
    transition-property: opacity, color, background-color, border-color,
                         box-shadow, fill, stroke !important;
  }
  /* keyframes ignore transition-property, so neutralize the one that moves */
  .cellv .val.freshly { animation: none; color: var(--aqua); }
  html { scroll-behavior: auto; }
}
```

Restricting `transition-property` is what removes movement: `transform` and
`width` are simply not in the allowed list, so they jump to their end value while
colour and opacity still ease.

### Two consequences to accept deliberately

1. **The collector progress bar steps instead of sliding.** `.progress-fill`
   animates `width` (`style.css:592`), which the allow-list excludes, so it will
   jump to each new percentage. That is correct — it is movement — and a stepping
   progress bar remains perfectly legible.
2. **The fresh-cell pop stops scaling but keeps its aqua tint.** That is the
   intended trade: the state change stays visible, the motion does not.

## Repo conventions to follow

- The reduced-motion block lives at the end of the
  `/* quality floor */` section, `relay/web/static/style.css:728-738`, directly
  after the shared `:focus-visible` rule.
- The stylesheet uses two-space indentation inside blocks and groups related
  declarations on one line only when they are short and clearly paired
  (exemplar: `style.css:733`).
- Comments explain intent, not mechanics — exemplar at `style.css:294-296`.

## Steps

1. In `relay/web/static/style.css`, replace lines 732–738 in their entirety with
   the target block quoted above under **Target**.

2. Nothing else changes. Do not add per-component reduced-motion overrides in
   this plan.

## Boundaries

- Do NOT remove the `@media (prefers-reduced-motion: reduce)` block or narrow it
  to specific selectors — the universal selector with `!important` is deliberate,
  it is only its *values* that are wrong.
- Do NOT add `transform` to the `transition-property` allow-list.
- Do NOT touch `relay/web/static/app.js`. JS-side reduced-motion branching
  (`matchMedia`) belongs to plan 011 only.
- Do NOT add new dependencies.
- If lines 732–738 do not match the excerpt above (drift since commit 18848ba),
  STOP and report instead of improvising.

## Verification

- **Mechanical**: `grep -n '0.01ms' relay/web/static/style.css` returns nothing.
- **Feel check**: in DevTools → Rendering, set **Emulate CSS media feature
  prefers-reduced-motion** to `reduce`, then:
  - Hover a rail icon and a table row — the background/colour still eases in,
    it does not snap. This is the main thing being restored.
  - Hover a drop zone on **Data Sources** — the border and shadow change, but the
    card does **not** lift.
  - Press a primary button (after plan 003) — the background changes, the button
    does **not** sink.
  - Run **Collect X views** and watch the progress bar — it steps to each new
    percentage instead of sliding. Expected.
  - Watch a cell fill — the number turns aqua but does not scale.
  - Set the emulation back to `no-preference` and confirm all motion returns.
- **Done when**: with reduced motion on, no element changes position or size, and
  every colour/opacity transition still runs at 120ms.
