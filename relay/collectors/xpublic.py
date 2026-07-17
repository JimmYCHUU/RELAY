"""Public X/Twitter view counts — no login, no stored credentials (SRS FR-17, C-3).

X removed view counts from its syndication API, so the reliable public route is
rendering the status page in a real browser and reading the "<n> Views" text.
Verified live against somoytv posts (e.g. status 2047493300572360770 → 157).
"""
from __future__ import annotations

import logging
import re

from ..models import CellValue
from .base import Pacer, parse_compact_number

log = logging.getLogger("relay.collectors")

_STATUS_ID = re.compile(r"/status/(\d+)")
# "157\nViews", "57.1K Views", Bengali digits included
_VIEWS_TEXT = re.compile(r"([\d.,০-৯]+(?:\.\d+)?[KMB]?)\s*\n?\s*Views", re.I)


def status_id(url: str) -> str | None:
    m = _STATUS_ID.search(url or "")
    return m.group(1) if m else None


def extract_views_from_text(body_text: str) -> int | None:
    m = _VIEWS_TEXT.search(body_text or "")
    return parse_compact_number(m.group(1)) if m else None


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
        views = extract_views_from_text(page.inner_text("body"))
        if views is not None:
            return CellValue(views, "collected", 1.0, "x public page")
        return CellValue.missing("no Views figure on public page (auth-walled or removed post)")
    except Exception as exc:  # never abort the report over one tweet
        log.warning("x collect failed for %s: %s", url, exc)
        return CellValue.missing(f"x collect failed: {type(exc).__name__}")
