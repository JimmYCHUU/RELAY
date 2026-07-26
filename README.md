# RELAY 📡

[![CI](https://github.com/JimmYCHUU/RELAY/actions/workflows/ci.yml/badge.svg)](https://github.com/JimmYCHUU/RELAY/actions/workflows/ci.yml)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)

Automated sponsored-content reporting for Somoy TV. RELAY ingests your per-brand
campaign sheet and the supervisor's matched files, matches every photocard to its
view counts across Facebook / Instagram / X, flags what it can't prove, and
generates the sponsor report .xlsx in exactly your current format — Sum, Total
views, Average rows, styling and all.

---

## Quick start (Docker)

```bash
docker compose up --build
# → dashboard at http://localhost:8501
```

Input/output live in `./data` (created on first run):

```
data/input/     drop monthly files here (optional — you can also upload in the UI)
data/output/    generated reports land here
data/profiles/  browser session for collectors (created by `relay login meta`)
data/db/        run history (SQLite audit log)
```

## Quick start (no Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m relay.cli serve            # dashboard on :8501
```

## The monthly workflow

1. Download the brand's campaign Google Sheet as `.xlsx`.
2. Get the three matched files from your supervisor (mainpage / subpage / insta) —
   optional, but they auto-resolve most cells. Multi-brand files with `Bkash`-style
   separator rows work as-is; RELAY finds the right section.
3. Export your content data from Meta Business Suite (Insights → Content →
   export) and drop it in too — **one file covers all your pages**, so this is a
   single download per month, not one per page. It carries Meta's **exact** Views
   per post, which is what the report's Views column has always meant.
4. Open the dashboard → drop files → pick brand + month tab → **Run matching**.
5. Review: green = matched, amber = estimated, blue = manual, red outline =
   missing. Click ✎ on any cell to estimate from reactions or type an exact value.
6. **Generate .xlsx** → download → e-mail it. Untick "mark estimated cells" for
   the sponsor-facing copy.
7. Optionally drop last cycle's hand-made report under *Cross-check* to verify
   RELAY cell-by-cell.

## CLI

```bash
# list month tabs
python -m relay.cli sheets "White Plus Updated FB Photocard Campaign _ Mar'26.xlsx"

# full run with cross-check
python -m relay.cli run \
  --campaign "White Plus Updated FB Photocard Campaign _ Mar'26.xlsx" \
  --sheet April --brand "White Plus" \
  --mainpage "white plus mainpage matched (1).xlsx" \
  --subpage  "white plus subpage matched (2).xlsx" \
  --insta    "white plus insta matched (3).xlsx" \
  --insights "WhitePlusApril.csv" \
  --reference "White Plus FB Photocard (April).xlsx"
```

`--insights` takes a Business Suite content export. One export normally covers
every page, so a single `--insights` is usually enough; the flag repeats if you
export pages separately. It is the source of exact Facebook figures — everything
below is only for what no export covers.

## Collectors (opt-in browser automation)

Collectors fill what the exports and matched files can't: real public X view
counts, resolution of `share/p` links back to a post the export knows, and the
reaction totals that feed the last-resort estimate.

```bash
python -m relay.cli login meta        # one-time headed login (2FA fine; cookies stay local)
python -m relay.cli run ... --collect-x                 # public X, no login ever
python -m relay.cli run ... --collect-fb --k 95         # MBS session + shared-post heuristic
python -m relay.cli run ... --collect-x --dry-run       # log intended visits, touch nothing
```

Account safety is enforced in code (`relay/collectors/base.py`): randomized
8–15 s pacing, a hard 200-navigation session budget, and immediate abort (with
session preserved) the moment a checkpoint/captcha appears. X credentials are
never entered or stored anywhere — X collection is public-page only.

## Matching rules (as you confirmed them)

| Report column | Source |
|---|---|
| FB Link 1 (Somoy News TV) | mainpage file `Views_Match_1` |
| FB Link 2 (Somoy Shongbad) | subpage file `Views_Match_1` |
| FB Link 3 (category subpage) | **highest** of subpage `Views_Match_2..N` (extras are scraper snapshots; discards logged) |
| …but see below | with an export loaded, these two get **reordered onto the right columns** |
| Instagram | insta file `Views_Match_1` |
| X impressions | collector only — never fabricated |

**The export also fixes which column a value belongs in.** Your supervisor's
`Views_Match_N` order doesn't track Link 2 / Link 3 — on April 2026 that put
36% of checkable cells on the wrong page's column (row totals were right, the
columns were swapped). With an export loaded, RELAY reorders their values onto
the columns the export attributes them to. It never changes a number, only which
cell it sits in, and each moved value says where it came from.

Where the supervisor's file has no value, RELAY reads the **exact** figure from
your Business Suite export. It cannot match on the link alone — Facebook's
`pfbid` blobs differ between a copied link and the export — so it joins on the
caption (scoped to the same page and ±3 days) and, for mainpage posts whose
headline was rewritten, on Meta's numeric post id read from the live page. Each
filled cell carries a comment naming the export file and post id, so the sponsor
can trace the number back to a row in the file you hand them.

The reactions × k estimate is the last resort only — for posts no export covers.
Its multiplier is fitted from your own export data rather than guessed: measured
across 1,820 real posts, reach/reactions ranged from ~294× at 1–4 reactions down
to ~61× at 500+, so a single fixed multiplier matched fewer than a fifth of them.
Posts with zero reactions are left blank rather than estimated as zero.

Anything unresolved is *flagged*, never guessed; estimates are always labeled
with the reactions and k used.

## Tests

```bash
pytest            # 153 tests, incl. cell-by-cell E2E vs the real April report
```

> **Data privacy:** the sample workbooks (campaign sheets, supervisor matched
> files, hand-made reports) contain real sponsor performance data and are
> deliberately **excluded from git** (`*.xlsx` and `*.csv` in `.gitignore`, the
> latter covering Business Suite exports). Keep them next
> to the repo locally to run the full E2E suite; without them the file-dependent
> tests skip automatically, which is what CI does.
