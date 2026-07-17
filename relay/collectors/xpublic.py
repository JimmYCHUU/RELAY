"""Public X/Twitter view counts — no login, no stored credentials (SRS FR-17, C-3)."""
from __future__ import annotations

import json
import logging
import re
import urllib.request

from ..models import CellValue
from .base import Pacer, parse_compact_number

log = logging.getLogger("relay.collectors")

_STATUS_ID = re.compile(r"/status/(\d+)")
_SYNDICATION = (
    "https://cdn.syndication.twimg.com/tweet-result?id={id}&token=relay"
)
_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"


def status_id(url: str) -> str | None:
    m = _STATUS_ID.search(url or "")
    return m.group(1) if m else None


def extract_views_from_page(html: str) -> int | None:
    """Pull the public view count out of a status page's embedded data."""
    for pattern in (r'"views":\{"count":"(\d+)"', r'"viewCount":"?(\d+)'):
        m = re.search(pattern, html)
        if m:
            return int(m.group(1))
    m = re.search(r'([\d.,]+[KMB]?)\s*Views', html)
    return parse_compact_number(m.group(1)) if m else None


def collect_x_views(url: str, pacer: Pacer) -> CellValue:
    sid = status_id(url)
    if not sid:
        return CellValue.missing(f"unrecognized X url: {url}")
    pacer.before_visit(url)
    if pacer.dry_run:
        return CellValue.missing("dry-run")
    try:
        req = urllib.request.Request(_SYNDICATION.format(id=sid), headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        views = data.get("views", {}).get("count") or data.get("view_count")
        if views is not None:
            return CellValue(int(views), "collected", 1.0, "x syndication")
        return CellValue.missing("x syndication returned no view count")
    except Exception as exc:  # never abort the report over one tweet
        log.warning("x collect failed for %s: %s", url, exc)
        return CellValue.missing(f"x collect failed: {exc}")
