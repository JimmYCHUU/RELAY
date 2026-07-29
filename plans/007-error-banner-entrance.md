# 007 — Give error banners an entrance and exit

- **Status**: DONE
- **Commit**: 18848ba
- **Severity**: MEDIUM
- **Category**: Missed opportunity — preventing a jarring change
- **Depends on**: 001 (needs `var(--ease-out)`)
- **Blocks**: 008, 009 (both use the `reveal()` / `conceal()` helpers added here)
- **Estimated scope**: 2 files (`style.css`, `app.js`), ~20 lines

## Problem

Both error banners appear and disappear with no bridge at all. An error that
arrives while the user is looking at another part of the page is never seen — it
materialises and self-destructs within eight seconds, with nothing to catch the eye
in either direction.

```js
/* relay/web/static/app.js:245-250 — current */
function showError(msg) {
  const el = $("#runError");
  el.textContent = msg;
  el.hidden = false;
  setTimeout(() => { el.hidden = true; }, 8000);
}
```

The collector banner is toggled the same way in twelve places, e.g.:

```js
/* relay/web/static/app.js:757-762 — current */
  if (!res.ok) {
    errEl.textContent = await errText(res);
    errEl.hidden = false;
    return;
  }
  errEl.hidden = true;
```

Both elements carry the `.error` class (`index.html:217` and `index.html:327`),
which has no transition:

```css
/* relay/web/static/style.css:106-109 — current */
.error {
  color: var(--critical); font-size: 13.5px; background: var(--critical-soft);
  border-radius: 10px; padding: 10px 14px; margin-top: 12px;
}
```

A plain CSS transition cannot fix this on its own, because the stylesheet forces
hidden elements out of the layout with `!important`:

```css
/* relay/web/static/style.css:84 — current */
[hidden] { display: none !important; }
```

## Target

Two small helpers in `app.js` that un-hide first, force a synchronous style flush,
then apply the visible class — so the transition has a state to move from. Every
`.error` show/hide goes through them.

The flush is `void el.offsetHeight`, **not** `requestAnimationFrame`. rAF is
throttled or paused entirely in a background tab, and RELAY's collector runs take
minutes, so a user who switches tabs mid-scrape would come back to a progress panel
or error banner that never revealed. The synchronous read has no such dependency.

```js
/* target — relay/web/static/app.js, immediately above showError */
/* [hidden] removes the element from layout, so a transition has nothing to run
   from: un-hide first, force a style flush so that state is the transition's
   start, then add the visible class; on the way out drop the class and re-hide
   once the transition has had time to finish. */
const CONCEAL_MS = 320;
function reveal(el) {
  clearTimeout(el._concealTimer);
  el.hidden = false;
  void el.offsetHeight;  // flush the un-hidden state; rAF would stall in a
                         // background tab, and scrapes run for minutes
  el.classList.add("in");
}
function conceal(el) {
  if (el.hidden) return;
  el.classList.remove("in");
  clearTimeout(el._concealTimer);
  el._concealTimer = setTimeout(() => { el.hidden = true; }, CONCEAL_MS);
}
```

```js
/* target — relay/web/static/app.js:245-250 */
function showError(msg) {
  const el = $("#runError");
  el.textContent = msg;
  reveal(el);
  clearTimeout(el._dismissTimer);
  el._dismissTimer = setTimeout(() => conceal(el), 8000);
}
```

The `_dismissTimer` guard is part of the fix: today a second error arriving five
seconds after the first inherits the first one's three-second countdown and
vanishes early.

```css
/* target — relay/web/static/style.css:106-109 */
.error {
  color: var(--critical); font-size: 13.5px; background: var(--critical-soft);
  border-radius: 10px; padding: 10px 14px; margin-top: 12px;
  opacity: 0; transform: translateY(-6px);
  transition: opacity 240ms var(--ease-out), transform 240ms var(--ease-out);
}
.error.in { opacity: 1; transform: none; }
```

It enters downward from above and leaves back up the same way — the same path in
both directions.

## Repo conventions to follow

- `app.js` defines small helpers just above their first use, not in a utilities
  block. Exemplars: `errText` at `app.js:251`, `puEls` at `app.js:713`,
  `isMulti` at `app.js:84`.
- Helper comments are a lowercase `/* … */` block above the function explaining
  *why*, as at `app.js:719` (`/* merge freshly-scraped runs from a status poll
  into state, marking new cells */`).
- Section dividers use the `/* ═════════ name ═════════ */` form; do not add a new
  section for these helpers — they belong in the existing flow above `showError`.

## Steps

1. In `relay/web/static/app.js`, insert the `CONCEAL_MS` constant and the
   `reveal` / `conceal` helpers (quoted verbatim under **Target**) immediately
   above `function showError(msg) {` at line 245, separated by a blank line.

2. Replace the body of `showError` (lines 245–250) with the target version above.

3. Replace **every** `errEl.hidden = false;` in `relay/web/static/app.js` with
   `reveal(errEl);`. There are exactly **8**, at lines 759, 804, 831, 852, 902,
   953, 972, 988. Two of them (831 and 972) sit inside single-line `if` statements
   of the form:

   ```js
   if (!res.ok) { errEl.textContent = await errText(res); errEl.hidden = false; return; }
   ```

   which becomes:

   ```js
   if (!res.ok) { errEl.textContent = await errText(res); reveal(errEl); return; }
   ```

4. Replace **every** `errEl.hidden = true;` with `conceal(errEl);`. There are
   exactly **4**, at lines 762, 832, 905 and 973.

5. In `relay/web/static/style.css`, replace lines 106–109 with the target `.error`
   rule and add the `.error.in` rule directly beneath it.

## Boundaries

- Do NOT convert any other `.hidden = ` assignment in `app.js`. In particular
  leave `tooltip.hidden` (`app.js:1101, 1104`) alone — the tooltip is re-triggered
  on every mousemove and must stay instant. Plans 008 and 009 own the download
  links and the progress panel.
- Do NOT rename `reveal` / `conceal` or change `CONCEAL_MS` — plans 008 and 009
  depend on both names and on 320ms covering their transitions.
- Do NOT use `@starting-style` or `transition-behavior: allow-discrete` here. The
  `!important` on `[hidden]` makes the flush-then-class approach the reliable one.
- Do NOT swap `void el.offsetHeight` for `requestAnimationFrame` — see **Target**.
- Do NOT change the 8000ms dismissal delay.
- Do NOT touch `relay/web/static/index.html` — both banners already have the
  `.error` class.
- Do NOT add new dependencies.
- If the counts in steps 3 and 4 do not come out at exactly 8 and 4 (drift since
  commit 18848ba), STOP and report instead of improvising.

## Verification

- **Mechanical**: `grep -c 'errEl.hidden' relay/web/static/app.js` returns `0`.
  `grep -c 'reveal(errEl)' relay/web/static/app.js` returns `8`.
  `grep -c 'conceal(errEl)' relay/web/static/app.js` returns `4`.
- **Feel check**:
  1. Start the app, go to **Data Sources**, and click **Run matching →** with no
     campaign file loaded, or upload a non-spreadsheet file, to force an error.
  2. The red banner should slide down a few pixels as it fades in, not blink into
     place. After eight seconds it should fade back up, not vanish.
  3. Trigger a second error about five seconds after the first: the banner must
     stay visible for a full eight seconds from the *second* error, not disappear
     three seconds later.
  4. Go to **Match Review** and press **Resolve Facebook posts** with no Meta
     session and no network, to exercise `#collectError` — same behaviour.
  5. In DevTools → Animations, set playback to 10% and confirm the banner
     decelerates into place rather than moving at a constant rate.
  6. In DevTools → Rendering, enable **Emulate CSS prefers-reduced-motion**: the
     banner should fade without sliding, and must still disappear afterwards
     (the 320ms conceal timer is independent of the transition).
- **Done when**: both error banners fade and slide in and out, the layout below
  them does not jump, and no banner is ever left stuck visible.
