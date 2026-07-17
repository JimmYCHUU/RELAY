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
    sel = config.SELECTORS["mbs_post_views"]
    try:
        el = page.locator(sel).first
        if el.count():
            views = parse_compact_number(el.inner_text(timeout=5000))
    except Exception:
        pass

    reactions = extract_reactions(page.content())
    if views is not None:
        return CellValue(views, "collected", 1.0, "meta business suite"), reactions
    note = "no views element; reactions available for heuristic" if reactions else \
           "no views element and no reactions found"
    return CellValue.missing(note), reactions


def resolve_share_link(page, url: str, pacer: Pacer) -> str:
    """Follow a facebook.com/share/p/ redirect to the canonical permalink."""
    pacer.before_visit(url)
    if pacer.dry_run:
        return url
    page.goto(url, wait_until="domcontentloaded")
    pacer.check_challenge(page.url, page.content()[:2000])
    return page.url
