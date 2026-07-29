# Animation plans — RELAY web UI

Produced by an animation audit of `relay/web/static/{index.html, style.css, app.js}`
at commit **18848ba**. Each plan is self-contained: exact file paths, verbatim
current code, exact target values, and a feel check. An executor needs no context
beyond the plan file.

**Every plan is read-only on everything outside its listed files, and none of them
changes markup structure, adds a dependency, or introduces a build step.** RELAY
ships raw CSS and vanilla JS; that stays true.

## Plans

| # | Title | Severity | Category | Status |
| --- | --- | --- | --- | --- |
| [001](001-motion-tokens.md) | Add motion tokens and normalize duration notation | LOW | Cohesion & tokens | DONE |
| [002](002-fresh-cell-pop.md) | Stop the fresh-cell pop from restarting on every poll | **HIGH** | Interruptibility | DONE |
| [003](003-press-feedback.md) | Add press feedback to primary and ghost buttons | MEDIUM | Physicality & origin | DONE |
| [004](004-reduced-motion-floor.md) | Replace the blanket reduced-motion kill with a gentler floor | MEDIUM | Accessibility | DONE |
| [005](005-progress-fill-linear.md) | Make the collector progress bar advance linearly | MEDIUM | Easing & duration | DONE |
| [006](006-gate-hover-motion.md) | Gate hover-lift motion behind a real pointer | LOW | Accessibility | DONE |
| [007](007-error-banner-entrance.md) | Give error banners an entrance and exit | MEDIUM | Missed opportunity | DONE |
| [008](008-download-link-reveal.md) | Let the download link arrive instead of appearing | LOW | Missed opportunity | DONE |
| [009](009-progress-panel-entrance.md) | Bridge the collector progress panel in and the Stop button out | LOW | Missed opportunity | DONE |
| [010](010-cell-dialog-entrance.md) | Give the cell editor a fast entrance | LOW | Missed opportunity | DONE |
| [011](011-theme-crossfade.md) | Cross-fade the light/dark theme switch | LOW | Missed opportunity | DONE |

All eleven were applied on 2026-07-29 in the order below. Verified with the
mechanical greps in each plan, a headless-Chromium smoke check (tokens resolve,
nothing left invisible-but-clickable, reveal/conceal round-trip, `:active` present
on primary and absent on `.cell-edit`, theme toggle, dialog entrance, reduced-motion
behaviour), `node --check`, and the 159-test Python suite. The **feel checks in
each plan still need a human** — especially 002 and 005, which require watching a
live collector run.

### One correction made during implementation

Plan 007 originally specified `requestAnimationFrame` to defer the visible class by
a frame. In testing, roughly one run in four left the banner at `opacity: 0`. rAF is
throttled or paused outright in a background tab, and RELAY's scrapes run for
minutes — a user who switches tabs mid-collect would return to a progress panel that
never revealed. Replaced with a synchronous `void el.offsetHeight` style flush,
which has no timing dependency; four consecutive smoke runs then passed clean. The
plan has been updated to match the shipped code.

## Recommended execution order

```
001 ──┬── 004 ── 005 ── 006 ── 003 ── 002
      │
      ├── 010
      ├── 011
      └── 007 ──┬── 008
                └── 009
```

1. **001** first, always. Every other plan consumes `var(--ease-out)`, which does
   not exist yet.
2. **004** early. Until the blanket reduced-motion rule is fixed, every
   improvement below is silently flattened for anyone with the preference set, so
   their feel checks can't be run.
3. **005**, then **006**, then **003** — three independent, single-rule CSS
   changes. 006 before 003 keeps the button block's source order tidy, though 003
   is written to be order-independent.
4. **002** — the highest-severity finding, but sequenced here because its feel
   check needs a live collector run of at least a minute, which is the slowest
   verification in the set. Do not skip it: this is the fix that stops the table
   strobing during a scrape.
5. **007** before **008** and **009** — it defines the `reveal()` / `conceal()`
   helpers both of them call.
6. **010** and **011** are independent of everything except 001 and can be done at
   any point after it.

If you only do three: **001 → 004 → 002**.

## Dependencies

| Plan | Requires | Reason |
| --- | --- | --- |
| 002 | 001 | Uses `var(--ease-out)` |
| 003 | 001 | Uses `var(--ease-out)` |
| 007 | 001 | Uses `var(--ease-out)` |
| 008 | 001, 007 | `reveal()` helper; low-specificity class must not beat 003's `:active` |
| 009 | 001, 007 | `reveal()` / `conceal()` helpers |
| 010 | 001 | Uses `var(--ease-out)` |
| 011 | 001 | Uses `var(--ease-out)` |

**Line-number drift**: plan 007 inserts roughly 14 lines near the top of `app.js`.
Plans 008, 009 and 011 flag this and are written to be matched on content. If any
step's quoted code doesn't match what's in the file, the plan says to stop and
report rather than improvise — follow that.

## Deliberately not planned

Recorded so these aren't re-raised later:

- **Chart entrances** (donut draw, horizontal-bar grow, KPI count-up). Functional
  data being read, and `renderReview()` / `renderDashboard()` re-run on every
  2-second collector poll, so any entrance would re-fire ~30 times a minute.
- **Line-chart crosshair transition** (`app.js:432`). It tracks the pointer;
  motion there reads as lag.
- **View-switch transitions** (`showView`, `app.js:42`). Core navigation — instant
  is correct. The existing non-smooth `window.scrollTo` is also correct.
- **Progress-log entrance** (`app.js:790`). A log being read, rewritten wholesale
  every poll.
- **Rail unlock fade** (`unlockViews`, `app.js:67`). Fires in the same frame as a
  full view change, so it competes for attention and lands in peripheral vision.
- **Staggered group entrances** on `.kpi-row` / `.tiles`. Would re-fire on every
  poll and every brand-tab click.
- **`transform: scaleX()` on the progress fill**. The textbook performance fix,
  declined with reasoning in plan 005 — it would distort the bar's gradient and
  rounded end cap for no measurable gain on one 8px element updated twice a minute.

## Already correct — do not "fix"

- The custom tooltip (`app.js:1099`) appears instantly. Correct for something
  re-triggered on every mousemove.
- No `transition: all`, no `ease-in`, and no `scale(0)` anywhere in the stylesheet.
- The `.cell-edit` pencil's opacity reveal on row hover already transitions at
  150ms via the shared button rule. That is the right amount for a control pressed
  dozens of times per correction pass.
