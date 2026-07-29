# 009 — Bridge the collector progress panel in and the Stop button out

- **Status**: DONE
- **Commit**: 18848ba
- **Severity**: LOW
- **Category**: Missed opportunity — state indication
- **Depends on**: 001 (`var(--ease-out)`), 007 (`reveal()` / `conceal()` helpers)
- **Estimated scope**: 2 files (`style.css`, `app.js`), ~12 lines

> **Line numbers below are as of commit 18848ba.** Plan 007 inserts about 14 lines
> near the top of `app.js`, so if it has already run, every `app.js` line number
> here is shifted down by roughly that much. Always match on the quoted content.

## Problem

Starting a collector drops an entire progress panel — heading, percentage track,
counter, event log — into the middle of the page in a single frame:

```js
/* relay/web/static/app.js:764-775 — current */
  state.collecting[target] = true;
  $(COLLECT_BTN[target]).disabled = true;
  $("#autopilotBtn").disabled = true;
  $("#collectProgress").hidden = false;
  const el = puEls(target);
  el.u.hidden = false;
  el.fill.style.width = "0%";
  el.text.textContent = COLLECT_LABEL[target];
  el.count.textContent = "";
  el.log.innerHTML = "";
  el.stop.hidden = false;
  el.stop.disabled = false;
```

At the other end, the Stop button is yanked out of a flex row, so the counter
beside it snaps sideways:

```js
/* relay/web/static/app.js:809-817 — current */
function finishCollect(target, message) {
  state.collecting[target] = false;
  $(COLLECT_BTN[target]).disabled = false;
  if (!anyCollecting() && !state.autopilot) $("#autopilotBtn").disabled = false;
  const el = puEls(target);
  el.stop.hidden = true;
  el.text.textContent = message;
  setTimeout(() => state.freshCells.clear(), 4000);
}
```

`.progress-unit` (`index.html:277, 290, 302, 314`) currently has **no CSS rule at
all** — the stylesheet styles its children (`.progress-head` at `style.css:582`,
`.progress-track` at 588) but never the unit itself.

## Target

The panel eases down into place; the Stop button fades rather than being cut out.

```css
/* target — new rules in the collect-panel section of style.css */
.progress-unit {
  opacity: 0; transform: translateY(-10px);
  transition: opacity 260ms var(--ease-out), transform 260ms var(--ease-out);
}
.progress-unit.in { opacity: 1; transform: none; }
```

```css
/* target — style.css:596, adding one declaration to the existing rule */
.stop-btn { padding: 4px 12px; font-size: 12.5px; border-color: color-mix(in srgb, var(--critical) 45%, transparent); color: var(--critical); opacity: 0; }
.stop-btn.in { opacity: 1; }
```

The Stop button's fade rides the `opacity 150ms ease` already declared on the
shared `button` rule (`style.css:203`) — no new transition is needed for it.

## Repo conventions to follow

- Progress styles live in the `collect-panel` group, `style.css:562-606`, ordered
  outermost-first: `.collect-progress` → `.progress-head` → `.progress-track` →
  `.progress-fill` → `.progress-meta`. `.progress-unit` belongs directly after
  `.collect-progress` (line 581), matching that nesting order.
- `puEls(target)` (`app.js:713-717`) is the single accessor for a progress unit's
  parts; always go through it rather than re-querying the DOM.

## Steps

1. In `relay/web/static/style.css`, immediately after line 581
   (`.collect-progress { … }`), insert the two `.progress-unit` rules quoted under
   **Target**.

2. In `relay/web/static/style.css`, append `opacity: 0;` to the existing
   `.stop-btn` rule at line 596, then add `.stop-btn.in { opacity: 1; }` on the
   following line, before the existing `.stop-btn:not([disabled]):hover` rule.

3. In `relay/web/static/app.js`, replace all **three** occurrences of
   `  el.u.hidden = false;` with `  reveal(el.u);`. They are in `startCollect`
   (line 768), `metaSignInThenCollect` (line 835) and `resetApUnit` (line 879).

4. In `relay/web/static/app.js`, replace the Stop-button show calls:
   - `  el.stop.hidden = false;` (line 773) → `  reveal(el.stop);`
   - `  $("#apStop").hidden = false;` (line 911) → `  reveal($("#apStop"));`

5. In `relay/web/static/app.js`, replace the Stop-button hide calls:
   - `  el.stop.hidden = true;` (lines 814 and 839) → `  conceal(el.stop);`
   - `  $("#apStop").hidden = true;` (lines 963 and 975) → `  conceal($("#apStop"));`

6. Leave every `$("#collectProgress").hidden = false;` (lines 766, 833, 884) as it
   is. That is the outer container; the animated units live inside it, and
   animating both would double the motion.

## Boundaries

- Do NOT animate `.collect-progress`, `.progress-log`, `.progress-track` or
  `.progress-fill`. The log is a live feed the user reads and is rewritten
  wholesale every two seconds (`app.js:790-792`); any entrance on it would replay
  on every poll. The fill is owned by plan 005.
- Do NOT touch `el.stop.disabled` assignments — enabled state and visibility are
  separate concerns.
- Do NOT add an exit animation to `.progress-unit`. Units are hidden only on a
  fresh start, where an exit would fight the entrance that follows.
- Do NOT change `puEls` or the markup in `index.html`.
- Do NOT add new dependencies.
- If `reveal`/`conceal` are not defined in `app.js`, plan 007 has not run yet —
  STOP and report.

## Verification

- **Mechanical**: `grep -c 'u.hidden = false' relay/web/static/app.js` returns `0`.
  `grep -c 'stop.hidden' relay/web/static/app.js` returns `0`.
  `grep -c 'apStop").hidden' relay/web/static/app.js` returns `0`.
  `grep -c 'collectProgress").hidden' relay/web/static/app.js` returns `3`.
- **Feel check**: needs a live collector run.
  1. Load a campaign sheet, run matching, open **Match Review**.
  2. Press **Collect X views**. The progress unit should ease down into place, not
     appear instantly. The Stop button should fade in with it.
  3. Let the run finish (or press **Stop**). The Stop button should fade out; watch
     the counter beside it — it will still reflow, but the button should no longer
     be cut away mid-frame.
  4. Start a second collector (**Resolve Facebook posts**) while the first unit is
     still on screen: the new unit animates in below without disturbing the first.
  5. Press **Autopilot** on a fresh page load and confirm its unit animates the
     same way.
  6. Confirm the event log inside the unit does **not** animate on each 2-second
     poll — lines should simply update in place.
  7. In DevTools → Rendering, enable **Emulate CSS prefers-reduced-motion**: the
     unit fades in without sliding, and the Stop button still fades.
- **Done when**: progress units ease in, Stop buttons fade out, the log is
  motionless between polls, and nothing is left invisible-but-clickable.
