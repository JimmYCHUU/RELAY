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

# --- heuristic (SRS FR-13) ---
K_MIN, K_MAX, K_DEFAULT = 70, 120, 95

# --- collector pacing (SRS NFR-6, hard account-safety budgets) ---
PACE_MIN_S, PACE_MAX_S = 8.0, 15.0          # authenticated FB/MBS session
X_PACE_MIN_S, X_PACE_MAX_S = 4.0, 8.0       # anonymous public X pages, no account at risk
SESSION_NAV_BUDGET = 200
CHALLENGE_MARKERS = ("checkpoint", "captcha", "login_attempt", "suspicious")

# --- collector DOM selectors, centralized for quick repair (SDD 6) ---
SELECTORS = {
    "x_views": '[data-testid="app-text-transition-container"]',
    "fb_reactions": '[aria-label*="reaction"], [aria-label*="Like"] span',
    "mbs_post_views": '[data-testid="post_insights_views"]',
}


def ensure_dirs() -> None:
    for d in (INPUT_DIR, OUTPUT_DIR, PROFILE_DIR, DB_PATH.parent, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)
