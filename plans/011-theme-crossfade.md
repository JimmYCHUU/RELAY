# 011 — Cross-fade the light/dark theme switch

- **Status**: DONE
- **Commit**: 18848ba
- **Severity**: LOW
- **Category**: Missed opportunity — preventing a jarring change
- **Depends on**: 001 (needs `var(--ease-out)`)
- **Estimated scope**: 2 files (`app.js`, `style.css`), ~12 lines

> **Line numbers below are as of commit 18848ba.** If plan 007 has already run it
> added about 14 lines near the top of `app.js`; match on content, not line number.

## Problem

The theme button inverts every colour token in the app in a single frame — page,
panel, ink, all six series colours, all shadows:

```js
/* relay/web/static/app.js:1295-1303 — current */
/* ═════════ theme ═════════ */
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  localStorage.setItem("relay-theme", t);
  $("use", $("#themeBtn")).setAttribute("href", t === "dark" ? "#i-sun" : "#i-moon");
}
applyTheme(document.documentElement.dataset.theme || "light");
$("#themeBtn").addEventListener("click", () =>
  applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
```

A full-viewport inversion with no bridge is the textbook jarring change, and this
is a rare action — comfortably in the tier where an animation is affordable.

## Target

A 200ms cross-fade via the View Transitions API, applied **only to the button
click**, never to the initial call on page load.

```js
/* target — relay/web/static/app.js, replacing the click listener */
/* a full-page colour inversion is jarring with no bridge; the View Transitions
   API cross-fades it without transitioning colours on every element */
function toggleTheme() {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  if (document.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    document.startViewTransition(() => applyTheme(next));
  } else {
    applyTheme(next);
  }
}
$("#themeBtn").addEventListener("click", toggleTheme);
```

```css
/* target — new rules at the end of the dialog & tooltip section in style.css */
::view-transition-old(root),
::view-transition-new(root) {
  animation-duration: 200ms;
  animation-timing-function: var(--ease-out);
}
```

### The approach that must not be used

Do **not** implement this as a global colour transition — no
`* { transition: background-color 200ms, color 200ms; }` and no transition on
`:root`. That taxes every hover, every table-row highlight and every chart
re-render in the app, forever, to buy one rare moment. The View Transitions API
snapshots the page once and cross-fades the snapshots, costing nothing between
theme switches.

`document.startViewTransition` is Chrome 111+ and Safari 18+; Firefox falls
through the `else` branch and switches instantly, exactly as today.

## Repo conventions to follow

- Theme handling lives in the `/* ═════════ theme ═════════ */` section at the
  very end of `app.js` (lines 1295-1303). Keep the new function there.
- Event listeners are attached with `$("#id").addEventListener("click", fn)` at
  module scope directly under the function they call — exemplar at
  `app.js:869` (`$("#autopilotBtn").addEventListener("click", startAutopilot);`).
- Reduced-motion branching in JS does not exist elsewhere in this file yet; use
  `matchMedia("(prefers-reduced-motion: reduce)").matches` inline as shown, and do
  not add a cached module-level variable — the preference can change mid-session.

## Steps

1. In `relay/web/static/app.js`, leave `function applyTheme(t)` (lines 1296-1300)
   completely unchanged, and leave the bare
   `applyTheme(document.documentElement.dataset.theme || "light");` call on line
   1301 unchanged. That runs on page load, where a cross-fade would be wrong.

2. Replace the two-line click listener at the end of the file:

   ```js
   $("#themeBtn").addEventListener("click", () =>
     applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
   ```

   with the `toggleTheme` function and its listener, quoted verbatim under
   **Target**.

3. In `relay/web/static/style.css`, append the `::view-transition-old(root)` /
   `::view-transition-new(root)` rule to the end of the
   `/* ═════════ dialog & tooltip ═════════ */` section, after the `.tooltip .sw`
   rule at line 758 and before the `@media (max-width: 1000px)` block at line 760.

## Boundaries

- Do NOT add `view-transition-name` to any element. The default root snapshot is
  exactly what a whole-page cross-fade needs; naming elements would opt them into
  separate, independently-animating transitions.
- Do NOT add colour transitions to `*`, `:root`, `body`, or any component.
- Do NOT wrap the page-load `applyTheme` call in a view transition.
- Do NOT change what `applyTheme` does, including the `localStorage` write and the
  sun/moon icon swap.
- Do NOT touch the inline theme bootstrap script in `index.html:9-12` — it runs
  before first paint to avoid a flash and must stay synchronous.
- Do NOT add new dependencies.
- If the click listener does not match the excerpt above (drift since commit
  18848ba), STOP and report instead of improvising.

## Verification

- **Mechanical**: `grep -c 'startViewTransition' relay/web/static/app.js` returns
  `2` — the feature check and the call, both inside `toggleTheme`.
  `grep -c '::view-transition' relay/web/static/style.css` returns `2`.
- **Feel check**, in Chrome:
  1. Start the app and click the moon button in the topbar. The whole page should
     cross-fade rather than snap. Click again to go back.
  2. Reload the page with dark theme stored. It must render dark immediately, with
     **no** fade from light on load — this is the main regression risk.
  3. Click the toggle rapidly five or six times. It should stay responsive and end
     on the correct theme; view transitions skip rather than queue.
  4. Toggle while a collector is running and the progress bar is advancing —
     confirm the cross-fade does not freeze or duplicate the bar.
  5. In DevTools → Rendering, enable **Emulate CSS prefers-reduced-motion**, then
     toggle: the theme must switch instantly with no cross-fade.
  6. Open in Firefox (or any browser without View Transitions) and toggle: it
     switches instantly with no error in the console.
- **Done when**: clicking the theme button cross-fades at 200ms in Chrome, page
  load never fades, reduced motion switches instantly, and no browser errors.
