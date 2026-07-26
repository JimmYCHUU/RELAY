"""Facebook permalink parsing — page slug, post token, canonical URL.

**`pfbid` tokens are not stable identifiers.** Measured on April 2026: the
campaign sheet's copied links and Meta's own export use *different* `pfbid`
blobs for the same post — 58 campaign links against 5,551 export rows on the
same pages and dates gave a token intersection of exactly **zero**, while the
captions matched at 1.00. Facebook mints `pfbid` per viewing context, so it
cannot be used to join the two sources.

What is still reliable here:

  * `page_slug()` — which page a post lives on. Stable, and the key that scopes
    caption matching in `resolve.insights_fill` so a post can only ever match
    rows from its own page.
  * `normalize_fb_url()` / `post_token()` — exact joins for the URL shapes that
    *do* carry a durable id (`/videos/<id>`, `/<page>/<numeric-id>`,
    `permalink.php?story_fbid=`), and for resume/link-identity checks.

The numeric `Post ID` export column is no help either: only 36 of 1,820
permalinks contained it.

Observed permalink shapes (real export, 1,820 posts):

    1,725  facebook.com/<page>/posts/<pfbid…>
       59  facebook.com/<page>/<numeric-id>/
       36  facebook.com/<page>/videos/<numeric-id>/
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

# Host prefixes that all address the same site.
_HOST_PREFIXES = ("www.", "m.", "web.", "mbasic.", "touch.")
_FB_HOSTS = ("facebook.com", "fb.com", "fb.me")

# The token that actually identifies a post: FB's opaque pfbid blob, or a bare
# numeric id. Case matters for pfbid, so tokens are never lowercased.
_PFBID = re.compile(r"^pfbid[A-Za-z0-9]+$")
_NUMERIC_ID = re.compile(r"^\d{6,}$")

# Path segments that are route furniture, never the post's identity.
_ROUTE_WORDS = {"posts", "videos", "video", "photos", "photo", "reel", "reels",
                "permalink.php", "story.php", "watch", "p", "pfbid"}


def is_share_link(url: str | None) -> bool:
    """A facebook.com/share/… short link, which must be resolved to a real
    permalink before it can be looked up (see `mbs.resolve_share_link`)."""
    if not url:
        return False
    return "/share/" in urlsplit(url.strip()).path


def _host_and_path(url: str) -> tuple[str, list[str]] | None:
    raw = (url or "").strip()
    if not raw:
        return None
    if "//" not in raw:
        raw = "https://" + raw.lstrip("/")
    parts = urlsplit(raw)
    host = parts.netloc.lower().split("@")[-1].split(":")[0]
    for prefix in _HOST_PREFIXES:
        if host.startswith(prefix):
            host = host[len(prefix):]
            break
    if not any(host == h or host.endswith("." + h) for h in _FB_HOSTS):
        return None
    segments = [s for s in parts.path.split("/") if s]
    # permalink.php?story_fbid=<id>&id=<page> — identity lives in the query
    if segments and segments[-1] in ("permalink.php", "story.php"):
        q = parse_qs(parts.query)
        story = (q.get("story_fbid") or q.get("fbid") or [None])[0]
        page = (q.get("id") or [None])[0]
        if story:
            segments = ([page] if page else []) + ["posts", story]
    return host, segments


def post_token(url: str | None) -> str | None:
    """The post's own identifier, independent of which page slug addresses it.

    A page can be referenced by vanity name or numeric id, so the token is the
    more forgiving of the two keys — used as a fallback when the full
    normalized URL doesn't match.
    """
    parsed = _host_and_path(url or "")
    if not parsed:
        return None
    _, segments = parsed
    for seg in reversed(segments):
        if seg in _ROUTE_WORDS:
            continue
        if _PFBID.match(seg) or _NUMERIC_ID.match(seg):
            return seg
    return None


def page_slug(url: str | None) -> str | None:
    """The page the post lives on ('somoysongbad360' or a numeric page id).

    Used to scope the caption fallback in `resolve.insights_fill` so a post can
    only ever be matched against rows from its own page.
    """
    parsed = _host_and_path(url or "")
    if not parsed:
        return None
    _, segments = parsed
    for seg in segments:
        if seg in _ROUTE_WORDS or _PFBID.match(seg):
            continue
        return seg.lower()
    return None


def normalize_fb_url(url: str | None) -> str | None:
    """Canonical comparison key for a Facebook post URL.

    Drops scheme, host prefixes, query string, fragment and trailing slash.
    Lowercases the host and route words but preserves the post token's case —
    `pfbid` blobs are case-sensitive and collide when folded.
    """
    parsed = _host_and_path(url or "")
    if not parsed:
        return None
    host, segments = parsed
    if not segments:
        return None
    canon = [s if (_PFBID.match(s) or _NUMERIC_ID.match(s)) else s.lower()
             for s in segments]
    return f"{host}/" + "/".join(canon)
