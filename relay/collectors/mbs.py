"""Meta Business Suite / Facebook post metrics via the user's own session
(SRS FR-16, FR-18). Selectors centralized in config.SELECTORS for quick repair.
"""
from __future__ import annotations

import base64
import logging
import re

from .. import config
from ..models import CellValue
from .base import NUM_TOKEN, Pacer, head_text, parse_compact_number

log = logging.getLogger("relay.collectors")

_VIEWS_TEXT = re.compile(NUM_TOKEN + r"\s*(?:views|plays)", re.I)

# The total sits in different places depending on the surface FB serves.
# Tier 0 — the Comet UFI summary payload. A permalink page embeds feedback
# for the displayed post AND for other preloaded stories (verified live: a
# 199-reaction post's page also carried 47- and 329-total stories — the exact
# garbage that used to land in reports). The DISPLAYED post's
# comet_ufi_summary_and_actions_renderer comes first in the payload, and story
# totals use the object form {"count":N} while per-type edge counts are plain
# ints — so anchor on the first renderer and read its object-form total.
_UFI_ANCHOR = re.compile(r"comet_ufi_summary_and_actions_renderer")
_REACT_TOTAL = re.compile(r'"reaction_count"\s*:\s*\{\s*"count"\s*:\s*(\d+)')
_UFI_WINDOW = 12000
# The displayed story's identity, in priority order:
# 1. The routing config's base64 storyID ("S:_I<actor>:<id>:<id>") — part of
#    the initial server HTML, so it CANNOT be corrupted by streaming order.
# 2. The first "post_id" — order-dependent (feedback chunks stream in
#    completion order and each carries post_ids), so last resort only.
_STORY_ID_B64 = re.compile(r'"storyID"\s*:\s*"([A-Za-z0-9+/=]+)"')
_POST_ID = re.compile(r'"post_id"\s*:\s*"(\d+)"')


def _target_story_id(content: str) -> str | None:
    m = _STORY_ID_B64.search(content)
    if m:
        try:
            raw = base64.b64decode(m.group(1)).decode("utf-8", "ignore")
            tail = raw.rsplit(":", 1)[-1]
            if tail.isdigit():
                return tail
        except Exception:
            pass
    m = _POST_ID.search(content)
    return m.group(1) if m else None


def _reactions_anchored(content: str, tid: str | None = None) -> int | None:
    """Total from the renderer that belongs to the displayed post itself.

    A permalink page embeds UFI renderers for the displayed post AND other
    preloaded stories, arriving in COMPLETION order — so both 'first renderer'
    and 'first post_id' can point at the wrong story (the recurring 47).
    Anchor on the routing storyID and match it against each renderer's window;
    verified live on rows 1/7/11/15 captures (657/199/308/204 vs garbage
    29/47/329/392/486/741)."""
    tid = tid or _target_story_id(content)
    if not tid:
        return None
    starts = [a.start() for a in _UFI_ANCHOR.finditer(content)]
    for i, s in enumerate(starts):
        # window bounded by the NEXT renderer so neighbours never bleed in
        end = min(s + _UFI_WINDOW, starts[i + 1] if i + 1 < len(starts) else len(content))
        if tid in content[max(0, s - 2000):end]:
            t = _REACT_TOTAL.search(content[s:end])
            if t and int(t.group(1)) > 0:
                return int(t.group(1))
    return None

# Tier 1 — the visible counter span next to the reaction icons (its class
# name is per-bundle; lives in config.SELECTORS for quick repair). Present in
# desktop sessions, often empty in the headless container's bundle.
_REACT_VISIBLE = re.compile(
    r'class="[^"]*' + re.escape(config.SELECTORS["fb_reaction_count_class"])
    + r'[^"]*"[^>]*>\s*([\d.,০-৯]+(?:\.\d+)?[KMB]?)\s*<')
# Tier 1 — exact server JSON. Unreliable alone: the permalink page embeds
# blobs for comments AND for suggested/related posts, so a 199-reaction post
# can read as a stray 405. Max-within-tier only fixes the comment case —
# hence tier 0 above.
_REACT_JSON = (
    re.compile(r'"(?:reaction_count|unified_reactors|reactors)"\s*:\s*\{\s*"count"\s*:\s*(\d+)'),
    re.compile(r'"i18n_reaction_count"\s*:\s*"([\d.,]+[KMB]?)"'),
)
# Tier 2 — the reactions dialog header text.
_REACT_ALL = re.compile(r'All reactions:?\s*([\d.,]+[KMB]?)', re.I)
# Tier 3 — aria-labels list each type separately ("Like: 89 people" +
# "Love: 25 people"); the total is their sum.
_REACT_PER_TYPE = re.compile(
    r'(?:Like|Love|Haha|Wow|Care|Sad|Angry):\s*([\d.,]+[KMB]?)\s*(?:people|person)', re.I)
# Tier 4 — loose visible-text shapes, LAST resort only: this one can also
# match the page's follower figure ("somoynews.tv · 12M likes"), so it must
# never outrank the tiers above, and max would be poison here.
_REACT_LOOSE = re.compile(
    r"([\d.,]+[KMB]?)\s*(?:reactions|likes|others|people reacted)", re.I)


def extract_reactions(html_or_text: str) -> int | None:
    n = _reactions_anchored(html_or_text)
    if n:
        return n
    m = _UFI_ANCHOR.search(html_or_text)
    if m:
        t = _REACT_TOTAL.search(html_or_text[m.start():m.start() + _UFI_WINDOW])
        if t and int(t.group(1)) > 0:
            return int(t.group(1))
    m = _REACT_VISIBLE.search(html_or_text)
    if m:
        n = parse_compact_number(m.group(1))
        if n:
            return n
    json_hits = [parse_compact_number(m.group(1))
                 for rx in _REACT_JSON for m in rx.finditer(html_or_text)]
    json_hits = [n for n in json_hits if n]
    if json_hits:
        return max(json_hits)
    m = _REACT_ALL.search(html_or_text)
    if m:
        n = parse_compact_number(m.group(1))
        if n:
            return n
    per_type = [parse_compact_number(x.group(1)) for x in _REACT_PER_TYPE.finditer(html_or_text)]
    total = sum(n for n in per_type if n)
    if total:
        return total
    m = _REACT_LOOSE.search(html_or_text)
    if m:
        return parse_compact_number(m.group(1))
    return None


def collect_fb_post(page, url: str,
                    pacer: Pacer) -> tuple[CellValue, int | None, str | None]:
    """Return (views CellValue, reactions or None, numeric post id or None).

    The post id is the valuable part now: it is the one identifier shared with
    the Business Suite export, so the caller can look the post's exact Views up
    there. `pfbid` blobs differ between a copied link and the export, and
    mainpage posts often carry a rewritten headline, so neither the URL nor the
    caption can join those rows — this can.

    This reads the **public permalink**, not an insights surface — post-level
    Reach/Views are not rendered there for any visitor, admin included. Exact
    figures come from the Business Suite export instead
    (`ingest.insights`), which is consulted before this collector ever runs.

    What survives here is what a permalink genuinely exposes: a plain-text view
    count on videos/reels, and the reaction total (via the story-anchored
    cascade below) as input to the last-resort estimate.
    """
    pacer.before_visit(url)
    if pacer.dry_run:
        return CellValue.missing("dry-run"), None, None
    page.goto(url, wait_until="domcontentloaded")
    pacer.check_challenge(page.url, head_text(page))

    # FB hydrates the page AFTER domcontentloaded, and the feedback payloads
    # stream in completion order — the displayed post's chunk can land after
    # other preloaded stories'. Poll until the chunk anchored to the post's
    # own id is present; one early snapshot is exactly how the recurring
    # wrong-story totals (47, 329, ...) got into reports.
    cls = config.SELECTORS["fb_reaction_count_class"]
    try:
        page.wait_for_selector(f"span.{cls}", timeout=10000)
    except Exception:
        pass
    reactions = None
    content = ""
    tid = None
    last_size = None
    for _ in range(5):
        # snapshotting a multi-MB permalink page and regex-scanning it is the
        # expensive step — skip both when the document hasn't grown since the
        # previous poll iteration
        try:
            size = page.evaluate("document.documentElement.outerHTML.length")
        except Exception:
            size = None
        if size is None or size != last_size:
            last_size = size
            content = page.content()
            # the routing storyID sits in the initial server HTML, so it never
            # changes across the poll — derive it from the first snapshot only
            tid = tid or _target_story_id(content)
            reactions = _reactions_anchored(content, tid)
            if reactions is not None:
                break
        try:
            page.wait_for_timeout(1500)
        except Exception:
            break

    # secondary: the visible counter in the live DOM (desktop bundles)
    if reactions is None:
        try:
            el = page.locator(f"span.{cls}").first
            if el.count():
                reactions = parse_compact_number(el.inner_text(timeout=2000))
        except Exception:
            pass

    if reactions is None:
        reactions = extract_reactions(content)

    # Video/reel surfaces expose the view count in plain text ("76.4K views",
    # Bengali digits included) — a REAL number, tried before any estimate.
    # Photo posts carry no such string, which is why the export matters.
    # The page can carry several "N views" strings (related reels, comment
    # attachments…); take the first one that is plausible for THIS post —
    # a view count can never be below the post's own reaction count.
    views = None
    source = "post page views figure"
    for m in _VIEWS_TEXT.finditer(content):
        candidate = parse_compact_number(m.group(1))
        if candidate is None:
            continue
        if reactions and candidate < reactions:
            continue
        views = candidate
        break

    if views is not None and reactions and views < reactions:
        # Same sanity gate for the selector path: 190 "views" on a 400-like
        # post means we scraped the wrong element, not a real figure.
        log.warning("discarding implausible views %s < reactions %s at %s",
                    views, reactions, url)
        views = None

    if views is not None:
        return CellValue(views, "collected", 1.0, source), reactions, tid
    note = ("no views figure on the public post (normal for photo posts) — "
            "not in the insights export either; reactions available for the estimate"
            if reactions else
            "no views figure and no reactions found")
    # tid may still be usable by the caller for an export lookup even when
    # nothing could be read off the page itself
    return CellValue.missing(note), reactions, tid


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
    pacer.check_challenge(page.url, head_text(page))
    return page.url
