"""Meta Business Suite / Facebook post metrics via the user's own session
(SRS FR-16, FR-18). Selectors centralized in config.SELECTORS for quick repair.
"""
from __future__ import annotations

import logging
import re

from .. import config
from ..models import CellValue
from .base import Pacer, parse_compact_number

log = logging.getLogger("relay.collectors")

_REACT = re.compile(r"([\d.,]+[KMB]?)\s*(?:reactions|likes|others)", re.I)
_VIEWS_TEXT = re.compile(r"([\d.,০-৯]+(?:\.\d+)?[KMB]?)\s*(?:views|plays)", re.I)


def extract_reactions(html_or_text: str) -> int | None:
    m = _REACT.search(html_or_text)
    if m:
        return parse_compact_number(m.group(1))
    return None


def collect_fb_post(page, url: str, pacer: Pacer) -> tuple[CellValue, int | None]:
    """Return (views CellValue, reactions or None) for one FB post.

    Views come from the MBS insights surface when the page belongs to the
    user's portfolio; reactions from the public post as heuristic input.
    """
    pacer.before_visit(url)
    if pacer.dry_run:
        return CellValue.missing("dry-run"), None
    page.goto(url, wait_until="domcontentloaded")
    pacer.check_challenge(page.url, page.content()[:2000])

    views = None
    source = "meta business suite"
    sel = config.SELECTORS["mbs_post_views"]
    try:
        el = page.locator(sel).first
        if el.count():
            views = parse_compact_number(el.inner_text(timeout=5000))
    except Exception:
        pass

    content = page.content()
    if views is None:
        # Many post surfaces expose the view count in plain text ("76.4K views",
        # Bengali digits included) — a REAL number, tried before any estimate.
        m = _VIEWS_TEXT.search(content)
        if m:
            views = parse_compact_number(m.group(1))
            source = "post page views figure"

    reactions = extract_reactions(content)
    if views is not None:
        return CellValue(views, "collected", 1.0, source), reactions
    note = ("no views figure visible to this session; reactions available for "
            "heuristic fallback" if reactions
            else "no views figure and no reactions found")
    return CellValue.missing(note), reactions


def extract_caption(page) -> str | None:
    """Post caption for rows whose campaign sheet left Content empty —
    read from the page already open, no extra navigation."""
    try:
        el = page.locator('meta[property="og:description"]').first
        if el.count():
            cap = (el.get_attribute("content") or "").strip()
            if cap:
                return cap[:300]
    except Exception:
        pass
    try:
        title = re.sub(r"\s*[|\-–]\s*Facebook.*$", "", (page.title() or "").strip())
        return title[:300] or None
    except Exception:
        return None


def resolve_share_link(page, url: str, pacer: Pacer) -> str:
    """Follow a facebook.com/share/p/ redirect to the canonical permalink."""
    pacer.before_visit(url)
    if pacer.dry_run:
        return url
    page.goto(url, wait_until="domcontentloaded")
    pacer.check_challenge(page.url, page.content()[:2000])
    return page.url
