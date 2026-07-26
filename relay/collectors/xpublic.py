"""Public X/Twitter view counts — no login, no stored credentials (SRS FR-17, C-3).

X removed view counts from its syndication API, so the reliable public route is
rendering the status page in a real browser and reading the "<n> Views" text.
Verified live against somoytv posts (e.g. status 2047493300572360770 → 157).
"""
from __future__ import annotations

import logging
import re

from ..models import CellValue
from .base import NUM_TOKEN, Pacer, parse_compact_number

log = logging.getLogger("relay.collectors")

_STATUS_ID = re.compile(r"/status/(\d+)")
# "157\nViews", "57.1K Views", Bengali digits included
_VIEWS_TEXT = re.compile(NUM_TOKEN + r"\s*\n?\s*Views", re.I)


def status_id(url: str) -> str | None:
    m = _STATUS_ID.search(url or "")
    return m.group(1) if m else None


def extract_views_from_text(body_text: str) -> int | None:
    m = _VIEWS_TEXT.search(body_text or "")
    return parse_compact_number(m.group(1)) if m else None


def _tweet_scope_text(page) -> str:
    """Text of the displayed tweet's own article. Scanning the whole body can
    pick up a Views figure (or a date) from replies and related posts below —
    the status page's main tweet is always the first article."""
    try:
        art = page.locator('article[data-testid="tweet"]').first
        if art.count():
            return art.inner_text(timeout=3000)
    except Exception:
        pass
    return page.inner_text("body")


def extract_tweet_text(page) -> str | None:
    """Tweet text for rows whose campaign sheet left Content empty —
    read from the page already open, no extra navigation."""
    try:
        el = page.locator('div[data-testid="tweetText"]').first
        if el.count():
            return el.inner_text(timeout=3000).strip()[:300] or None
    except Exception:
        pass
    return None


def collect_x_views(page, url: str, pacer: Pacer) -> CellValue:
    """Read the public view count from a status page. `page` is a Playwright
    page in a logged-OUT browser context — X credentials are never used."""
    sid = status_id(url)
    if not sid:
        return CellValue.missing(f"unrecognized X url: {url}")
    pacer.before_visit(url)
    if pacer.dry_run:
        return CellValue.missing("dry-run")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        try:
            page.wait_for_selector('a[href*="/analytics"], span:text("Views")', timeout=12000)
        except Exception:
            pass  # fall through to text scan; some layouts label views differently
        views = extract_views_from_text(_tweet_scope_text(page))
        if views is None:
            # the Views span often hydrates after the selector wait times out —
            # one bounded retry before declaring the figure missing
            page.wait_for_timeout(2500)
            views = extract_views_from_text(_tweet_scope_text(page))
        if views is not None:
            return CellValue(views, "collected", 1.0, "x public page")
        return CellValue.missing("no Views figure on public page (auth-walled or removed post)")
    except Exception as exc:  # never abort the report over one tweet
        log.warning("x collect failed for %s: %s", url, exc)
        return CellValue.missing(f"x collect failed: {type(exc).__name__}")
