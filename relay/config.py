"""Central configuration: paths, thresholds, pacing budgets, selectors."""
from __future__ import annotations

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("RELAY_DATA_DIR", "./data")).resolve()
INPUT_DIR = DATA_DIR / "input"
OUTPUT_DIR = DATA_DIR / "output"
PROFILE_DIR = DATA_DIR / "profiles"
DB_PATH = DATA_DIR / "db" / "runs.db"
LOG_DIR = DATA_DIR / "logs"

# --- matching thresholds (SRS FR-6) ---
FUZZY_HIGH = 0.90       # >= high  -> provenance "matched", tier "fuzzy"
FUZZY_REVIEW = 0.75     # >= this  -> tier "review"
PREFIX_MIN_LEN = 25     # min chars for truncated-title prefix matching

# --- insights export (SRS FR-16; the only source of exact Facebook figures) ---
# Which export column becomes the report's "Views" value. Settled empirically
# against April 2026: of the supervisor's own figures, 100% of mainpage and 94%
# of subpage values land within 2% of an export **Views** figure and 0% match
# Reach. (The small residual is drift — the supervisor scraped earlier and views
# kept accruing.) So the report column has always meant Views, not Reach.
INSIGHTS_METRIC = "views"           # "reach" | "views"
# Meta renames and localizes export headers, so they are matched tolerantly.
# Order matters: the first alias that matches exactly wins. "reactions" must
# stay ahead of nothing else in its own list, but note the real export also has
# a "Reactions, comments and shares" column — resolve_headers() claims exact
# matches first so that one can never be mistaken for "Reactions".
INSIGHTS_HEADERS = {
    "post_id":    ("post id", "post_id"),
    "page_id":    ("page id", "page_name id", "page_id"),
    "page_name":  ("page name", "page"),
    "title":      ("title", "message", "post message", "description"),
    "permalink":  ("permalink", "permalink url", "post link", "url", "link"),
    "published":  ("publish time", "publish date", "created time", "date published"),
    "views":      ("views", "impressions", "post impressions", "total views"),
    "reach":      ("reach", "post reach", "people reached", "accounts reached"),
    "reactions":  ("reactions", "post reactions", "likes and reactions"),
    "post_type":  ("post type", "type", "media type"),
    "is_share":   ("is share", "shared post"),
}

# --- heuristic (SRS FR-13; last resort only — see docs/SRS.md) ---
# Measured against a real export (1,820 posts): views/reactions has a median of
# 261x and reach/reactions 181x, and the ratio falls as engagement rises
# (~413x at 1-4 reactions, ~64x at 500+). A flat multiplier therefore cannot be
# right for most posts — these bounds are only the fallback used when the
# export supplies no data to fit against. 70-120 is the user's own stated rule
# (System Design Request.md).
K_MIN, K_MAX, K_DEFAULT = 70, 120, 95
# Reaction-count buckets used to fit k from real export data, coarse enough
# that each bucket keeps a usable sample on a normal month.
K_BUCKETS = ((1, 4), (5, 9), (10, 24), (25, 49), (50, 99), (100, 249),
             (250, 499), (500, 10**9))
K_BUCKET_MIN_SAMPLES = 12           # below this a bucket falls back to K_DEFAULT

# --- collector pacing (SRS NFR-6, hard account-safety budgets) ---
PACE_MIN_S, PACE_MAX_S = 8.0, 15.0          # authenticated FB/MBS session — do not lower
X_PACE_MIN_S, X_PACE_MAX_S = 2.5, 5.0       # anonymous public X pages: no account exists to
                                            # flag; only IP-level rate limits apply
SESSION_NAV_BUDGET = 200
CHALLENGE_MARKERS = ("checkpoint", "captcha", "login_attempt", "suspicious")
# Relaunch the persistent Meta context after this many page visits: a single
# Chromium context navigated through hundreds of heavy MBS/IG SPA pages grows
# its renderer heap until the machine swaps. The login lives in the on-disk
# profile, so recycling never costs the session.
CONTEXT_RECYCLE_EVERY = 25
# Skip images/video/fonts on the Meta session — every extraction path is
# text/HTML-based, so nothing breaks; big memory + load-time win on long
# batches. Set False if MBS pages ever misbehave.
BLOCK_MEDIA_META = True

# --- collector DOM selectors, centralized for quick repair (SDD 6) ---
SELECTORS = {
    # the span FB renders the post's visible reaction total in (verified live
    # 2026-07 on somoynews.tv permalinks) — update here when FB rotates it
    "fb_reaction_count_class": "x135b78x",
}


def ensure_dirs() -> None:
    for d in (INPUT_DIR, OUTPUT_DIR, PROFILE_DIR, DB_PATH.parent, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)
