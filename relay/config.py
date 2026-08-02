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
# against a full month of hand-made figures: they track the export's **Views**
# column, not Reach — near-exactly, the small residual being drift, since a
# figure read by hand earlier keeps accruing views afterwards. So the report
# column has always meant Views.
INSIGHTS_METRIC = "views"           # "reach" | "views"
# Meta renames and localizes export headers, so they are matched tolerantly.
# Order matters: the first alias that matches exactly wins. "reactions" must
# stay ahead of nothing else in its own list, but note the real export also has
# a "Reactions, comments and shares" column — resolve_headers() claims exact
# matches first so that one can never be mistaken for "Reactions".
# The Instagram export is the same shape with different words for the same
# things — "Account name" for the page, "Likes" for reactions, "Description" for
# the caption — so one alias table serves both rather than two parsers.
INSIGHTS_HEADERS = {
    "post_id":    ("post id", "post_id"),
    "page_id":    ("page id", "page_name id", "page_id", "account id"),
    "page_name":  ("page name", "account name", "account username", "page"),
    "title":      ("title", "message", "post message", "description"),
    "permalink":  ("permalink", "permalink url", "post link", "url", "link"),
    "published":  ("publish time", "publish date", "created time", "date published"),
    "views":      ("views", "impressions", "post impressions", "total views", "plays"),
    "reach":      ("reach", "post reach", "people reached", "accounts reached"),
    # "likes" last: on a Facebook export "Likes and reactions" must still win, and
    # exact matches are claimed before any substring pass (see resolve_headers).
    "reactions":  ("reactions", "post reactions", "likes and reactions", "likes"),
    # Engagement is Meta's own combined column, not a figure RELAY adds up — the
    # export already publishes reactions + comments + shares as one number and
    # that is the one a sponsor can check against Business Suite. `comments` and
    # `shares` are carried only so the combined figure can still be reconstructed
    # from an export that omits it (older files, some IG exports).
    #
    # These three sit after "reactions" deliberately. The exact pass claims a
    # column before any substring pass sees it, so "Reactions, comments and
    # shares" is taken by `engagement` and "Reactions" by `reactions`, whichever
    # order they appear in the file.
    "engagement": ("reactions, comments and shares", "reactions, comments, and shares",
                   "likes, comments and shares", "engagement", "post engagement",
                   "total engagement", "interactions"),
    "comments":   ("comments", "post comments"),
    "shares":     ("shares", "post shares", "reshares"),
    "post_type":  ("post type", "type", "media type"),
    "is_share":   ("is share", "shared post"),
}
# Bar for the boilerplate-stripped caption key (matching.normalize.strip_boilerplate).
# Deliberately far above FUZZY_HIGH: stripping the tail leaves a short token set,
# and token_set_ratio on a short set can miss the single word that reverses a
# headline's meaning. Near-identity only — see that function's docstring.
INSIGHTS_STRIPPED_HIGH = 0.98
# How far a campaign row's date may sit from the export row's publish time.
CAPTION_WINDOW_DAYS = 3
# `/share/p/…` and `/photo/?fbid=…&set=a.…` links name no page, so the page is
# inferred from where that slot's other links in the same sheet point. The
# inference is only used when the winning page outweighs its nearest rival by
# this factor; below it the cell is left empty and the reason recorded. Measured
# on June: at 3x the inference stays right for 99.5% of cells it accepts, and
# raising it further only declines more without correcting anything.
SLOT_PAGE_DOMINANCE = 3.0

# --- caption repair (SRS FR-13b) ---
# Campaign sheets are hand-maintained: a caption gets edited on the post and
# nobody updates the sheet, so the caption join fails for that row's every slot
# at once. One browser visit identifies one post; the row's other posts are then
# found offline, because Somoy cross-posts a story to several pages minutes
# apart and the export records each.
#
# These three compare one export title against another — both Meta's own text —
# so the bar is near-identity, unlike the sheet-caption comparison in `_score`.
# A genuine cross-post is usually verbatim (median agreement 1.000), which is
# what leaves room to set the bar this high.
#
# Measured over 481 already-matched June cells, at MARGIN 0.05 and a 90-minute
# window: 0.95 gives 445 right / 3 wrong / 33 declined, and 0.98 gives 447 / 3 /
# 31 — a tighter bar declines *less*, because it stops near-misses from
# crowding the runner-up margin. 0.99 starts losing real cross-posts.
#
# 0.98 is also what it takes to keep "স্বর্ণের দাম … বাড়ানোর" (raised) away from
# "… কমানোর" (cut): one word apart in a ten-word headline, a different post, and
# they agree 0.954. Dropping the runner-up margin costs accuracy on its own
# (7 wrong) — it is the guard against Somoy running one story twice on a page.
# Widening the window past 90 minutes changes nothing.
REPAIR_SIBLING_HIGH = 0.98
REPAIR_SIBLING_MARGIN = 0.05
REPAIR_SIBLING_WINDOW_MIN = 90


# --- collector pacing (SRS NFR-6, hard account-safety budgets) ---
PACE_MIN_S, PACE_MAX_S = 8.0, 15.0          # authenticated FB/MBS session — do not lower
X_PACE_MIN_S, X_PACE_MAX_S = 2.5, 5.0       # anonymous public X pages: no account exists to
                                            # flag; only IP-level rate limits apply
SESSION_NAV_BUDGET = int(os.environ.get("RELAY_NAV_BUDGET", 200))
# Nothing refills the budget on a timer — it is a counter on one Pacer, and a
# fresh run starts a fresh one. What the 200 really buys is a ceiling on how
# long a single unbroken burst of Facebook navigation lasts: at PACE_MIN_S..
# PACE_MAX_S that is roughly 27-50 minutes. Autopilot can now sit out a
# cooldown and carry on by itself rather than making the user restart it; the
# pause is the part that matters for account safety, not the restart.
NAV_BUDGET_COOLDOWN_S = float(os.environ.get("RELAY_NAV_COOLDOWN_S", 900))
# How many further bursts autopilot may take before it stops for good. 0 keeps
# the old behaviour: exhaust the budget once and halt.
NAV_BUDGET_MAX_LAPS = int(os.environ.get("RELAY_NAV_MAX_LAPS", 6))
CHALLENGE_MARKERS = ("checkpoint", "captcha", "login_attempt", "suspicious")
# Relaunch the persistent Meta context after this many page visits: a single
# Chromium context navigated through hundreds of heavy MBS/IG SPA pages grows
# its renderer heap until the machine swaps. The login lives in the on-disk
# profile, so recycling never costs the session.
CONTEXT_RECYCLE_EVERY = 25
# The same guard for the logged-out X session. It has by far the most visits to
# make in a cycle — 427 against Facebook's 150 in a real July — and used to hold
# one page open for all of them. Higher than the Meta figure because a public
# status page is a fraction of the weight of an MBS one.
X_CONTEXT_RECYCLE_EVERY = int(os.environ.get("RELAY_X_RECYCLE_EVERY", 40))
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
