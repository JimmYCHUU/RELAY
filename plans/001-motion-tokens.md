# 001 — Add motion tokens and normalize duration notation

- **Status**: DONE
- **Commit**: 18848ba
- **Severity**: LOW
- **Category**: Cohesion & tokens
- **Estimated scope**: 1 file (`relay/web/static/style.css`), ~14 lines touched

## Problem

`relay/web/static/style.css` tokenizes colour, shadow and spacing rigorously in
`:root` (lines 5–81) but has **no motion tokens at all**. Every transition names
its duration inline, in two different notations for the same value, and most omit
the timing function entirely (so they silently fall back to the CSS initial value,
`ease`).

Shorthand-seconds dialect:

```css
/* relay/web/static/style.css:130 — current */
  transition: background .12s, color .12s, border-color .12s, box-shadow .12s;
/* relay/web/static/style.css:203 — current */
  transition: transform .1s, box-shadow .15s, background .15s, opacity .15s;
/* relay/web/static/style.css:637 — current */
tbody tr { transition: background .12s; }
```

Explicit-milliseconds dialect, same 120ms value:

```css
/* relay/web/static/style.css:248 — current */
  transition: background 120ms ease, box-shadow 120ms ease, color 120ms ease;
/* relay/web/static/style.css:273 — current */
  transition: color 120ms ease, background 120ms ease;
```

This blocks every other plan in `plans/`, all of which reference `var(--ease-out)`.

## Target

Two curve tokens in `:root`, and one consistent notation across the stylesheet.

```css
/* target — relay/web/static/style.css, inside :root */
  --ease-out: cubic-bezier(0.23, 1, 0.32, 1);
  --ease-in-out: cubic-bezier(0.77, 0, 0.175, 1);
```

**This plan must not change how anything feels.** Hover and colour transitions
correctly use `ease` and keep using `ease` — written out explicitly instead of
relied on as a default. The new tokens are *added* for later plans to consume;
this plan does not apply `--ease-out` to any existing rule.

Do **not** add these tokens to the `:root[data-theme="dark"]` block
(`style.css:46`) — easing curves do not vary by theme.

## Repo conventions to follow

- All design tokens live in the single `:root` block at `relay/web/static/style.css:5–45`,
  one `--name: value;` per line, two-space indent, grouped by kind with a trailing
  `/* comment */` on the group's first line where the purpose isn't obvious
  (exemplar: `--brand: #ef5a2e;` with `/* coral — brand identity (logo, warm accents) */`
  at `style.css:17`).
- The dark-theme block at `style.css:46` overrides only the tokens that actually
  differ. Exemplar of a token deliberately *not* repeated there: `--page` is
  overridden, but `--chev` is redefined only because its embedded stroke colour
  changes.

## Steps

1. In `relay/web/static/style.css`, immediately after the `--shadow-tab:` line
   (currently line 43) and before the `--chev:` line, insert:

   ```css
     /* motion — entering/exiting uses --ease-out; on-screen movement --ease-in-out.
        Hover and colour changes deliberately keep the built-in `ease`. */
     --ease-out: cubic-bezier(0.23, 1, 0.32, 1);
     --ease-in-out: cubic-bezier(0.77, 0, 0.175, 1);
   ```

2. Normalize the seconds-shorthand durations to milliseconds and write the
   implicit `ease` explicitly. Apply exactly these replacements, changing nothing
   else on those lines:

   | Line | Current | Replace with |
   | --- | --- | --- |
   | 130 | `transition: background .12s, color .12s, border-color .12s, box-shadow .12s;` | `transition: background 120ms ease, color 120ms ease, border-color 120ms ease, box-shadow 120ms ease;` |
   | 167 | `transition: border-color .12s, color .12s;` | `transition: border-color 120ms ease, color 120ms ease;` |
   | 203 | `transition: transform .1s, box-shadow .15s, background .15s, opacity .15s;` | `transition: transform 100ms ease, box-shadow 150ms ease, background 150ms ease, opacity 150ms ease;` |
   | 223 | `transition: border-color .15s, box-shadow .15s;` | `transition: border-color 150ms ease, box-shadow 150ms ease;` |
   | 353 | `transition: border-color .12s, box-shadow .12s;` | `transition: border-color 120ms ease, box-shadow 120ms ease;` |
   | 395 | `transition: color .12s, border-color .12s;` | `transition: color 120ms ease, border-color 120ms ease;` |
   | 525 | `transition: border-color .15s, transform .12s, box-shadow .15s;` | `transition: border-color 150ms ease, transform 120ms ease, box-shadow 150ms ease;` |
   | 637 | `tbody tr { transition: background .12s; }` | `tbody tr { transition: background 120ms ease; }` |
   | 679 | `... min-width: 2px; transition: background .15s; }` | `... min-width: 2px; transition: background 150ms ease; }` |

3. Leave lines 248, 261 and 273 alone — they already use the target notation.

4. Leave line 592 (`transition: width .4s ease`) and line 649
   (`animation: pop .5s ease`) alone. Plans 002 and 005 rewrite those rules
   entirely; touching them here would cause a conflict.

## Boundaries

- Do NOT touch `relay/web/static/app.js` or `relay/web/static/index.html`.
- Do NOT change any duration *value* — `.12s` becomes `120ms`, never `150ms`.
- Do NOT replace any existing `ease` with `var(--ease-out)`. That is a feel change
  and belongs to the plans that own those rules.
- Do NOT touch lines 592 or 649 (owned by plans 005 and 002).
- Do NOT add new dependencies or a build step. This project ships raw CSS.
- If a line's current content does not match the "Current" column above (drift
  since commit 18848ba), STOP and report instead of improvising.

## Verification

- **Mechanical**: `grep -nE '\.[0-9]+s' relay/web/static/style.css` must return
  exactly two lines (the `pop` animation and the progress-fill `width`, which
  plans 002 and 005 own). `grep -c '^  --ease' relay/web/static/style.css` must
  return `2`.
- **Feel check**: start the app (`python -m relay.cli serve` or
  `uvicorn relay.web.app:app`), open it, and confirm **nothing changed**:
  - Rail icons, table rows and drop zones highlight on hover exactly as before.
  - Toggle to dark theme via the moon button in the topbar; colours still swap.
  - In DevTools → Rendering, nothing new appears in the Animations panel.
- **Done when**: the two tokens exist in `:root`, the grep above returns only
  lines 592 and 649, and the UI is visually identical to before the change.
