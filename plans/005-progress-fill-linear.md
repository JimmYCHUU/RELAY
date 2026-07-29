# 005 — Make the collector progress bar advance linearly

- **Status**: DONE
- **Commit**: 18848ba
- **Severity**: MEDIUM
- **Category**: Easing & duration (+ a Performance finding deliberately declined)
- **Estimated scope**: 1 file (`relay/web/static/style.css`), 1 line

## Problem

```css
/* relay/web/static/style.css:588-593 — current */
.progress-track { height: 8px; background: var(--surface-2); border-radius: 999px; overflow: hidden; border: 1px solid var(--ring); }
.progress-fill {
  height: 100%; width: 0%;
  background: linear-gradient(90deg, var(--accent), var(--aqua));
  border-radius: 999px; transition: width .4s ease;
}
```

This bar tracks real collector progress. Its width is set from poll data every two
seconds:

```js
/* relay/web/static/app.js:787-788 — current */
  const pct = s.total ? Math.round((s.done / s.total) * 100) : 0;
  el.fill.style.width = pct + "%";
```

Constant, monotonic motion should be `linear`. `ease` accelerates out of each poll
step and decelerates into it, so a scrape that is advancing at a steady rate is
rendered as a series of little lurches — the bar looks like it is hesitating when
the collector is not.

## Target

```css
/* target — relay/web/static/style.css:592 */
  border-radius: 999px; transition: width 400ms linear;
```

400ms is kept deliberately: it is well inside the 2-second poll interval, so each
step completes and rests before the next arrives, while being long enough that the
advance reads as movement rather than a jump.

### A performance finding we are declining, on purpose

Animating `width` triggers layout and paint rather than compositing, and the
textbook fix is `transform: scaleX()` with `transform-origin: left`. **Do not do
that here.** This element carries a `linear-gradient(90deg, …)` and a
`border-radius: 999px` end cap; `scaleX` would stretch the gradient and squash the
rounded cap into an ellipse, and correcting that needs a counter-scaled inner
wrapper. For a single 8px-tall element updated twice a minute, the layout cost is
not measurable and the visual cost of the "fix" is. The `width` transition stays.

## Repo conventions to follow

- After plan 001, durations in this stylesheet are written in `ms` with the
  timing function always stated explicitly — exemplar at `style.css:248`:
  `transition: background 120ms ease, box-shadow 120ms ease, color 120ms ease;`
- The progress components live in the `collect-panel` group,
  `relay/web/static/style.css:581-606`.

## Steps

1. In `relay/web/static/style.css`, replace line 592:

   ```css
     border-radius: 999px; transition: width .4s ease;
   ```

   with:

   ```css
     border-radius: 999px; transition: width 400ms linear;
   ```

## Boundaries

- Do NOT convert `width` to `transform: scaleX()` — see the reasoning above.
- Do NOT change the 400ms duration.
- Do NOT touch `.progress-track` (line 588) or any other rule in the block.
- Do NOT touch `relay/web/static/app.js` — the percentage calculation at
  `app.js:787` and `app.js:932` is correct.
- Do NOT add new dependencies.
- If line 592 does not match the excerpt above (drift since commit 18848ba), STOP
  and report instead of improvising.

## Verification

- **Mechanical**: `grep -n 'transition: width' relay/web/static/style.css` returns
  exactly one line reading `transition: width 400ms linear;`.
- **Feel check**: this requires a live collector run.
  1. Load a campaign sheet, run matching, open **Match Review**.
  2. Start **Collect X views** and watch the progress bar for at least four polls
     (~8 seconds).
  3. Confirm each advance is a steady slide at constant speed — no perceptible
     speeding-up at the start or easing-off at the end of each step.
  4. In DevTools → Animations, set playback to 10% during a step and confirm the
     leading edge travels at a uniform rate.
  5. Confirm the gradient still runs smoothly from accent to aqua across the full
     filled width, and both ends of the bar are still round.
- **Done when**: the bar advances at constant speed between polls, with the
  gradient and rounded caps unchanged.
