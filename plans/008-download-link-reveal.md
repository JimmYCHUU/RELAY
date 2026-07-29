# 008 — Let the download link arrive instead of appearing

- **Status**: DONE
- **Commit**: 18848ba
- **Severity**: LOW
- **Category**: Missed opportunity — delight (rare tier)
- **Depends on**: 001 (`var(--ease-out)`), 007 (`reveal()` helper)
- **Estimated scope**: 2 files (`index.html`, `style.css`) + 2 lines in `app.js`

## Problem

Generating the workbook is what the entire product exists to do. The moment it
succeeds is rendered flat: the download link snaps into the button row from
nothing.

```js
/* relay/web/static/app.js:1044-1052 — current */
$("#genBtn").addEventListener("click", async () => {
  const res = await fetch(`/api/report/${state.run.run_id}?comments=${$("#commentsToggle").checked}`, { method: "POST" });
  if (!res.ok) { showError(await errText(res)); return; }
  const data = await res.json();
  const dl = $("#dlBtn");
  dl.hidden = false;
  dl.href = `/api/report/${state.run.run_id}/download`;
  $("#dlText").textContent = `Download ${data.name}`;
});
```

The batch equivalent at `app.js:1054-1066` does the same for `#dlAllBtn`.

Both links live at the end of a flex row:

```html
<!-- relay/web/static/index.html:396-400 — current -->
      <button id="genAllBtn" class="ghost lg" hidden>Generate all brands (.zip)</button>
      <a id="dlAllBtn" class="ghost lg" hidden download><svg class="ic-svg"><use href="#i-download"/></svg> <span id="dlAllText">Download zip</span></a>
      <button id="genBtn" class="primary lg">Generate .xlsx</button>
      <a id="dlBtn" class="ghost lg" hidden download><svg class="ic-svg"><use href="#i-download"/></svg> <span id="dlText">Download</span></a>
```

This is the rare, first-time, high-emotion tier — the one place in a crisp
operator tool where a little delight budget is actually allowed.

## Target

The link fades and slides out of the button that produced it.

```css
/* target — appended to the report section of style.css */
.reveal-slide {
  opacity: 0; transform: scale(0.96) translateX(-8px);
  transition: opacity 300ms var(--ease-out), transform 300ms var(--ease-out);
}
.reveal-slide.in { opacity: 1; transform: none; }
```

`scale(0.96)`, never `scale(0)` — nothing in the real world appears from nothing.
The class (rather than an `#id` selector) is deliberate: it keeps specificity low
enough that the `a.ghost:active` press feedback from plan 003 still wins while the
link is held down.

```js
/* target — relay/web/static/app.js:1049 and app.js:1063 */
  reveal(dl);
```

### Layout shift to accept, not fix

`.gen-actions` is the right-hand child of a `justify-content: space-between` row
(`style.css:688-689`), so adding the link grows the group leftward and nudges the
Generate button left by the link's width. Do not try to reserve space for it: a
`min-width` placeholder would leave a permanent gap on every visit before the first
generate, which is worse than a one-time shift the user's eye isn't on. The
incoming link's own motion is what covers it.

## Repo conventions to follow

- Utility classes are appended to the section they belong to, not a global block.
  Put `.reveal-slide` in the `/* ═════════ report ═════════ */` section
  (`style.css:674-697`), after the `.gen-actions` rule at line 689.
- Multiple classes on an element are space-separated in source order
  structural → variant, as at `index.html:397` (`class="ghost lg"`).

## Steps

1. In `relay/web/static/index.html` line 397, add `reveal-slide` to the class
   list of `#dlAllBtn`:

   ```html
      <a id="dlAllBtn" class="ghost lg reveal-slide" hidden download><svg class="ic-svg"><use href="#i-download"/></svg> <span id="dlAllText">Download zip</span></a>
   ```

2. In `relay/web/static/index.html` line 399, do the same for `#dlBtn`:

   ```html
      <a id="dlBtn" class="ghost lg reveal-slide" hidden download><svg class="ic-svg"><use href="#i-download"/></svg> <span id="dlText">Download</span></a>
   ```

3. In `relay/web/static/style.css`, immediately after line 689
   (`.gen-actions { display: flex; gap: 12px; align-items: center; }`), insert the
   two `.reveal-slide` rules quoted under **Target**.

4. In `relay/web/static/app.js`, replace **both** occurrences of the exact line
   `  dl.hidden = false;` with `  reveal(dl);`. There are exactly two — one in the
   `#genBtn` click handler and one in the `#genAllBtn` click handler. (At commit
   18848ba these are lines 1049 and 1063; if plan 007 has already run it will have
   pushed them down by about 14 lines, so match on content, not line number.)

5. Leave `if (state.runs.length < 2) $("#dlAllBtn").hidden = true;` inside
   `renderReport()` (line 1009 at commit 18848ba) exactly as it is. That is a
   state reset, not a user-visible exit; animating it would make the view flicker on every
   brand-tab switch. It must stay an instant hide — and because `conceal()` is not
   used, the `.in` class is left on the element, which is correct: a later
   `reveal()` will show it immediately without re-animating a link the user has
   already seen.

## Boundaries

- Do NOT apply `.reveal-slide` to any other element.
- Do NOT use an `#id` selector for these rules — specificity would break the
  press feedback from plan 003.
- Do NOT add a `min-width`, placeholder or skeleton to `.gen-actions`.
- Do NOT call `conceal()` anywhere in this plan.
- Do NOT change the `href`/`textContent` assignments that follow the reveal.
- Do NOT add new dependencies.
- If `reveal` is not already defined in `app.js`, plan 007 has not run yet —
  STOP and report.

## Verification

- **Mechanical**: `grep -c 'reveal-slide' relay/web/static/index.html` returns `2`.
  `grep -n 'dl.hidden' relay/web/static/app.js` returns nothing.
- **Feel check**:
  1. Load a campaign sheet, run matching, continue to **Reports**.
  2. Press **Generate .xlsx**. When the server responds, the Download link should
     ease in from slightly small and slightly left, settling next to the button —
     not blink into place.
  3. Confirm the link is clickable the instant it appears and downloads the file.
  4. Press **Generate .xlsx** a second time. The link is already visible; it must
     **not** re-animate.
  5. Press and hold the Download link: it should sink slightly (plan 003's press
     feedback). This is the specificity check — if it does not sink, the rules were
     written with `#id` selectors.
  6. With two or more brands staged, repeat for **Generate all brands (.zip)**,
     then switch brand tabs and confirm the zip link disappears instantly without
     a flicker or fade.
  7. In DevTools → Rendering, enable **Emulate CSS prefers-reduced-motion**: the
     link should fade in without sliding or scaling.
- **Done when**: the download link eases into the row on first generate, never
  re-animates on subsequent ones, and press feedback still works on it.
