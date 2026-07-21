"""Instagram post metrics via the user's own Meta session — for cycles where
no supervisor match file exists and every cell must be scraped.

Reels/videos expose a real play/view count (embedded JSON first, plain page
text second); photo posts have no view figure at all, so likes are returned
for the reactions × k estimate fallback, exactly like Facebook shared posts.
Same sanity rule as FB: a views figure below the post's own like count means
we read the wrong element — discard it.
"""
from __future__ import annotations

import logging
import re

from ..models import CellValue
from .base import Pacer, parse_compact_number

log = logging.getLogger("relay.collectors")

# server-rendered JSON blobs carry the exact count
_JSON_VIEWS = re.compile(
    r'"(?:video_view_count|video_play_count|play_count|view_count)"\s*:\s*(\d+)')
_JSON_LIKES = re.compile(
    r'"(?:edge_media_preview_like|edge_liked_by)"\s*:\s*\{\s*"count"\s*:\s*(\d+)')
# visible text fallbacks ("12.5K views", "1,234 likes", Bengali digits OK)
_VIEWS_TEXT = re.compile(r"([\d.,০-৯]+(?:\.\d+)?[KMB]?)\s*(?:views|plays)", re.I)
_LIKES_TEXT = re.compile(r"([\d.,০-৯]+(?:\.\d+)?[KMB]?)\s*likes", re.I)


def extract_ig_views(content: str, likes: int | None = None) -> int | None:
    """View/play count from page HTML; candidates below the like count are
    other elements (suggested reels, comment attachments) — skipped."""
    for rx in (_JSON_VIEWS, _VIEWS_TEXT):
        for m in rx.finditer(content):
            v = parse_compact_number(m.group(1))
            if v is None:
                continue
            if likes and v < likes:
                continue
            return v
    return None


def extract_ig_likes(content: str) -> int | None:
    for rx in (_JSON_LIKES, _LIKES_TEXT):
        m = rx.search(content)
        if m:
            return parse_compact_number(m.group(1))
    return None


def collect_ig_post(page, url: str, pacer: Pacer) -> tuple[CellValue, int | None]:
    """Return (views CellValue, likes or None) for one Instagram post."""
    pacer.before_visit(url)
    if pacer.dry_run:
        return CellValue.missing("dry-run"), None
    page.goto(url, wait_until="domcontentloaded")
    pacer.check_challenge(page.url, page.content()[:2000])

    if "accounts/login" in page.url:
        return CellValue.missing(
            "instagram sign-in required — open instagram.com in the Meta "
            "sign-in window once; the session is remembered"), None

    content = page.content()
    likes = extract_ig_likes(content)
    views = extract_ig_views(content, likes)
    if views is not None:
        return CellValue(views, "collected", 1.0, "instagram post page"), likes
    note = ("photo post or no view figure visible; likes available for the "
            "estimate fallback" if likes
            else "no view figure and no likes found on the post page")
    return CellValue.missing(note), likes


def extract_ig_caption(page) -> str | None:
    """Post caption for rows whose campaign sheet left Content empty —
    read from the page already open, no extra navigation."""
    try:
        el = page.locator('meta[property="og:title"]').first
        if el.count():
            cap = (el.get_attribute("content") or "").strip()
            # og:title looks like `somoytv on Instagram: "caption text"`
            m = re.search(r':\s*[""]?(.+?)[""]?$', cap)
            if m and m.group(1).strip():
                return m.group(1).strip()[:300]
            if cap:
                return cap[:300]
    except Exception:
        pass
    return None
