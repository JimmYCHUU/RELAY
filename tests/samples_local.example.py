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

# --- the supervisor's matched files for the month under test ---
MAINPAGE_MATCHED = "mainpage matched.xlsx"
SUBPAGE_MATCHED = "subpage matched.xlsx"
INSTA_MATCHED = "insta matched.xlsx"

# --- multi-brand matched files (several sponsors, separator rows between) ---
ALL_MAIN_APRIL = "April social card mainpage matched.xlsx"
ALL_MAIN_PENDING = "Pending social card mainpage matched.xlsx"
ALL_SUB_PENDING = "pending social card subpage matched.xlsx"
# a brand section that exists in ALL_MAIN_APRIL, lowercased
SECTION_BRAND = "acme"

# --- the hand-made report the E2E test reproduces cell-by-cell ---
REPORT_APRIL = "FB Photocard (April).xlsx"

# --- a Meta Business Suite content export (.csv or .xlsx) ---
INSIGHTS_EXPORT = "insights-export.csv"
