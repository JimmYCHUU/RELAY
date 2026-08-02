"""Facebook permalink parsing — page slug, post token, canonical URL.

**`pfbid` tokens are not stable identifiers.** Measured on a real month: the
campaign sheet's copied links and Meta's own export use *different* `pfbid`
blobs for the same post — a whole month of campaign links against the export
rows for the same pages and dates gave a token intersection of exactly **zero**,
while the captions matched perfectly. Facebook mints `pfbid` per viewing
context, so it cannot be used to join the two sources.

What is still reliable here:

  * `page_slug()` — which page a post lives on. Stable, and the key that scopes
    caption matching in `resolve.insights_fill` so a post can only ever match
    rows from its own page.
  * `normalize_fb_url()` / `post_token()` — exact joins for the URL shapes that
    *do* carry a durable id (`/videos/<id>`, `/<page>/<numeric-id>`,
    `permalink.php?story_fbid=`), and for resume/link-identity checks.

The numeric `Post ID` export column is no help either: only a low single-digit
percentage of permalinks contain it.

Observed permalink shapes, in descending frequency on a real export:

    facebook.com/<page>/posts/<pfbid…>          the overwhelming majority
    facebook.com/<page>/<numeric-id>/           a small remainder
    facebook.com/<page>/videos/<numeric-id>/    videos only

Campaign sheets carry two further shapes the export never does, because they are
what Facebook's own "Copy link" buttons hand out:

    facebook.com/share/p/<short>/               mobile share sheet
    facebook.com/photo/?fbid=<id>&set=…         desktop photo lightbox

Neither names its page in the path. The lightbox's `set=pb.<page-id>` variant
names it in the query, and `page_slug()` recovers it there — as a numeric id,
which the export can translate to its vanity slug. The `set=a.<album-id>`
variant and every share link carry no page at all: `page_slug()` returns None
and `resolve.insights_fill` infers the page from the rest of the sheet.
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

# Instagram's shortcode, the opposite of a pfbid: the same post carries the same
# code in a copied link and in Meta's export, so `ig_shortcode` is an exact join
# and Instagram never needs the browser visit Facebook does.
_IG_SHORTCODE = re.compile(
    r"instagram\.com/(?:[^/]+/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", re.I)


def ig_shortcode(url: str | None) -> str | None:
    """The post's shortcode from an instagram.com URL, or None.

    Tolerates the tracking suffix the app's copy-link button appends
    (`?utm_source=ig_web_copy_link&…`), a trailing slash, and the
    `/<account>/reel/<code>` form as well as the bare `/p/<code>`.
    """
    hit = _IG_SHORTCODE.search((url or "").strip())
    return hit.group(1) if hit else None

# Path segments that are route furniture, never the post's identity.
_ROUTE_WORDS = {"posts", "videos", "video", "photos", "photo", "reel", "reels",
                "permalink.php", "story.php", "photo.php", "watch", "p", "pfbid"}

# The lightbox's `set` parameter: "pb.<page-id>.-2207520000" names the page,
# "a.<album-id>" names only an album and tells us nothing about the page.
_PHOTO_SET_PAGE = re.compile(r"^pb\.(\d{6,})\b")
_PHOTO_ROUTES = ("photo", "photo.php")


_X_HOSTS = ("x.com", "twitter.com")
_IG_HOSTS = ("instagram.com",)


def link_platform(url: str | None) -> str | None:
    """Which platform a link addresses — 'fb', 'x', 'ig' — or None if unknown.

    Campaign sheets are filled in by hand and the X and Instagram columns sit
    side by side, so the two get crossed. A link in the wrong column can never
    be matched: each platform's join uses a key the other's URLs do not carry,
    so an Instagram post filed under X is not a wrong figure but a permanently
    empty cell. `ingest.campaign` uses this to put each link back.
    """
    raw = (url or "").strip()
    if not raw:
        return None
    if "//" not in raw:
        raw = "https://" + raw.lstrip("/")
    host = urlsplit(raw).netloc.lower().split("@")[-1].split(":")[0]
    for prefix in _HOST_PREFIXES:
        if host.startswith(prefix):
            host = host[len(prefix):]
            break
    for hosts, name in ((_FB_HOSTS, "fb"), (_X_HOSTS, "x"), (_IG_HOSTS, "ig")):
        if any(host == h or host.endswith("." + h) for h in hosts):
            return name
    return None


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
    # /photo/?fbid=<id>&set=pb.<page-id> — the desktop lightbox, likewise
    elif segments and segments[-1] in _PHOTO_ROUTES:
        fbid = (parse_qs(parts.query).get("fbid") or [None])[0]
        if fbid:
            page = _PHOTO_SET_PAGE.match(
                (parse_qs(parts.query).get("set") or [""])[0])
            segments = ([page.group(1)] if page else []) + ["photos", fbid]
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

    The page is always the *first* path segment. A URL that opens with route
    furniture instead names no page — `/photo/?fbid=…&set=a.<album>` and a
    page-less `permalink.php?story_fbid=…` both do — and returns None rather
    than the post id that follows, which would scope the caption fallback to a
    page that does not exist.
    """
    parsed = _host_and_path(url or "")
    if not parsed:
        return None
    _, segments = parsed
    if not segments:
        return None
    head = segments[0]
    if head in _ROUTE_WORDS or _PFBID.match(head):
        return None
    return head.lower()


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
