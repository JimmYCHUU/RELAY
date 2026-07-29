# 002 — Stop the fresh-cell pop from restarting on every poll

- **Status**: DONE
- **Commit**: 18848ba
- **Severity**: HIGH
- **Category**: Interruptibility (+ Easing & duration)
- **Depends on**: 001 (needs `var(--ease-out)`)
- **Estimated scope**: 2 files (`style.css`, `app.js`), ~6 lines touched

## Problem

When a collector fills a cell, that cell is marked "fresh" and plays a pop
animation. The animation **replays on every 2-second status poll for the rest of
the run**, and fresh cells accumulate, so by the end of a scrape dozens of cells
pulse in unison every two seconds.

Three pieces combine to cause it:

```js
/* relay/web/static/app.js:729 — current: a cell is marked fresh when it fills */
          state.freshCells.add(`${fresh.run_id}:${row.no}:${slot}`);
```

```js
/* relay/web/static/app.js:816 — current: the set is only emptied 4s after the
   WHOLE run finishes, so keys survive for the entire scrape */
  setTimeout(() => state.freshCells.clear(), 4000);
```

```js
/* relay/web/static/app.js:794-798 — current: every poll re-renders the table
   wholesale, destroying and recreating every cell node */
  recomputeCoverage();
  renderReview();

  if (s.state === "running") {
    setTimeout(() => pollCollect(target), 2000);
```

`renderReview()` rebuilds `tbody.innerHTML` (`app.js:598`), so each poll gives every
still-"fresh" cell a **brand-new DOM node**. CSS keyframes restart from 0% on a new
node — unlike transitions, which retarget from the current state. Result: a cell
filled in minute one of a ten-minute scrape replays its animation roughly 300 times.

The animation itself is also outside budget and on the wrong curve:

```css
/* relay/web/static/style.css:649-650 — current */
.cellv .val.freshly { animation: pop .5s ease; color: var(--aqua); }
@keyframes pop { 0% { transform: scale(1.25); } 100% { transform: scale(1); } }
```

500ms for micro-feedback whose budget is 100–160ms, and `ease` starts slow on the
exact moment the eye is drawn to. `scale(1.25)` is also a large jump for a number
sitting in a dense table.

## Target

Each cell pops **exactly once**, on the poll where its value arrived, at 140ms with
a strong ease-out and a gentler overshoot.

```css
/* target — relay/web/static/style.css:649-650 */
.cellv .val.freshly { animation: pop 140ms var(--ease-out); color: var(--aqua); }
@keyframes pop { 0% { transform: scale(1.12); } 100% { transform: scale(1); } }
```

```js
/* target — relay/web/static/app.js, first statement inside applyRunUpdates */
function applyRunUpdates(freshRuns) {
  // each poll owns its own fresh set: a cell pops on the poll it arrives and
  // never again, even though every poll rebuilds the table's DOM
  state.freshCells.clear();
  const activeId = state.run.run_id;
```

### Deliberate behaviour change to review

Today the aqua tint from `color: var(--aqua)` persists on a filled cell for the
rest of the run. After this change it lasts one poll cycle (~2 seconds). This is
intended: "just scraped" should mean *just*, and the durable signal already exists
as the aqua provenance dot (`.p-collected`, `style.css:612`), rendered from
`c.provenance` at `app.js:614`. Confirm you are happy with this in the feel check.

### Known residual edge case — do not attempt to fix here

`renderReview()` is also called outside the poll loop, e.g. from the cell-editor
close handler (`app.js:685`) and on brand-tab switch (`app.js:563`). If the user
edits a cell in the 2 seconds between polls during an active scrape, that poll's
handful of fresh cells will pop a second time. This is rare and harmless. Fixing
it properly requires timestamping each key and emitting a negative
`animation-delay`; that complexity is not justified. Leave it.

## Repo conventions to follow

- `state` is a single plain object literal declared at `app.js:7-20`; mutate it
  directly, never reassign `state` itself. `freshCells` stays a `Set`.
- Comments in `app.js` are lowercase sentence fragments explaining *why*, placed
  directly above the code. Exemplar at `app.js:83-84`:
  `// Insights takes one export per page, so its zone accepts several files at`
  `// once and accumulates them; every other zone holds exactly one.`
- Animation values come from tokens defined in `:root` (`style.css:5`); plan 001
  adds `--ease-out` there.

## Steps

1. In `relay/web/static/app.js`, find `function applyRunUpdates(freshRuns) {` at
   line 720. Insert two comment lines and `state.freshCells.clear();` as the
   first statements in the body, above the existing
   `const activeId = state.run.run_id;`:

   ```js
   function applyRunUpdates(freshRuns) {
     // each poll owns its own fresh set: a cell pops on the poll it arrives and
     // never again, even though every poll rebuilds the table's DOM
     state.freshCells.clear();
     const activeId = state.run.run_id;
   ```

2. In `relay/web/static/style.css`, replace line 649 with:

   ```css
   .cellv .val.freshly { animation: pop 140ms var(--ease-out); color: var(--aqua); }
   ```

3. In `relay/web/static/style.css`, replace line 650 with:

   ```css
   @keyframes pop { 0% { transform: scale(1.12); } 100% { transform: scale(1); } }
   ```

4. Leave `app.js:816` and `app.js:965` (`setTimeout(() => state.freshCells.clear(), 4000)`)
   exactly as they are. They now only clear the final poll's batch after a run
   ends, which is still needed.

## Boundaries

- Do NOT change the render model. `renderReview()` staying on a 2-second full
  re-render is out of scope; this plan makes the animation correct *given* that.
- Do NOT touch `renderReviewRows` (`app.js:595`), `cellHtml` (`app.js:610`) or
  `slotRowHtml` (`app.js:1230`) — the `freshly` class logic at lines 618 and 1244
  is correct and stays.
- Do NOT remove `color: var(--aqua)` from the `.freshly` rule.
- Do NOT introduce timestamps, `animation-delay`, or a keyed/diffing renderer.
- Do NOT add new dependencies.
- If the code at these lines does not match the excerpts above (drift since
  commit 18848ba), STOP and report instead of improvising.

## Verification

- **Mechanical**: `grep -n 'freshCells.clear' relay/web/static/app.js` must return
  three lines (the new one inside `applyRunUpdates`, plus 816 and 965 unchanged).
  `grep -n 'pop ' relay/web/static/style.css` must show `140ms var(--ease-out)`.
- **Feel check**: this needs a real collector run — the bug only appears across
  multiple polls.
  1. Load a campaign sheet in **Data Sources**, run matching, go to **Match Review**.
  2. Start **Collect X views** (no login needed) and let it run for at least
     60 seconds while watching the table.
  3. Confirm: a cell pops **once** as its number lands, then sits still. Nothing
     in the table pulses on a 2-second rhythm. Cells filled a minute ago are
     completely static.
  4. Confirm the aqua tint fades out of a cell within a couple of seconds while
     its aqua provenance dot stays.
  5. In DevTools → Animations panel, set playback speed to 10% and trigger a fill:
     the number should settle down from slightly-too-large, not snap from 125%.
  6. In DevTools → Rendering, enable **Emulate CSS prefers-reduced-motion**; the
     pop should not move (plan 004 handles this — if 004 is not yet done, the
     animation will merely be near-instant, which is acceptable at this stage).
- **Done when**: a 60-second collector run shows each cell animating exactly once,
  with no repeating pulse anywhere in the table.
