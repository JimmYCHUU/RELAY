"""Local sample-file names — copy to `samples_local.py` and edit.

The file-bound tests (E2E, ingest, generator, web, batch) run against the real
workbooks you keep next to the repo. Those files are git-ignored because they
hold live sponsor data — and their *filenames* are too, because a name like
"<sponsor> FB Photocard (April).xlsx" identifies the sponsor by itself.

`tests/samples_local.py` is git-ignored. Without it, every file-bound test
skips itself, which is what CI does. Names are relative to the repo root.
"""

# --- the campaign workbook (one sponsor, one tab per month) ---
CAMPAIGN = "Campaign.xlsx"
# a month tab whose Date column has blanks, for the autofill test
ELECTION_SHEET = "Election"


# --- the hand-made report the E2E test reproduces cell-by-cell ---
REPORT_APRIL = "FB Photocard (April).xlsx"

# --- a Meta Business Suite content export (.csv or .xlsx) ---
INSIGHTS_EXPORT = "insights-export.csv"

# --- the content export covering CAMPAIGN's April tab (what E2E measures) ---
INSIGHTS_APRIL = "april-insights-export.csv"
