"""Fill unresolved Facebook cells from Meta's own insights export (SRS FR-13a).

This is where nearly every figure in a report now comes from. The export is
consulted before any collector runs, and what it cannot account for is left for
a post visit rather than estimated — a multiplier was measured wrong for ~92% of
posts, and a blank cell is worth more to a sponsor than a plausible invention.

The value written is an exact integer from Meta, and its note names the source
file and post id so the client can trace any figure back to a row in the export
they were handed.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import timedelta
from itertools import permutations
from typing import Callable, Optional

from rapidfuzz import fuzz

from .. import config
from ..ingest.insights import InsightsIndex, display_name
from ..matching.normalize import normalize_caption, strip_boilerplate
from ..matching.permalink import is_share_link, page_slug
from ..models import CellValue, InsightsRow, RowIssue, RunResult

log = logging.getLogger("relay.resolve")

FB_SLOTS = ("fb1", "fb2", "fb3")
CAPTION_WINDOW_DAYS = config.CAPTION_WINDOW_DAYS

# Resolves a facebook.com/share/… link to its canonical permalink. Injected so
# this module never imports Playwright — see collectors.mbs.resolve_share_link.
ShareResolver = Optional[Callable[[str], Optional[str]]]


def _as_runs(result) -> list[RunResult]:
    return list(result) if isinstance(result, (list, tuple)) else [result]


def cell_from_insights(row: InsightsRow, metric: str | None = None,
                       how: str | None = None) -> CellValue | None:
    """An exact, auditable cell from one export row.

    The note has to answer "where did this number come from?" on its own, because
    hovering it is the only route a reader has. It names the line of the file it
    came from, `how` it was joined, and enough of the export row to check the
    figure against the live post.

    That last part is not decoration. A `pfbid` in the sheet never equals the one
    in the export (see `matching.permalink`), and 10.7% of a real month's export
    rows — including most shared posts — carry a blank Title, so for those a
    reader searching their own copy by link *or* by caption finds nothing and a
    correct figure looks invented. The reaction count is what they can actually
    compare against Facebook.
    """
    metric = metric or config.INSIGHTS_METRIC
    value = row.metric(metric)
    if value is None:
        return None
    label = "Reach" if metric == "reach" else "Views"
    where = f"insights export {display_name(row.source_file)}"
    if row.source_row:
        where += f" row {row.source_row}"
    parts = [where, f"post {row.post_id}", label]
    if how:
        parts.append(how)
    if not (row.title or "").strip():
        parts.append("shared post — the export carries no caption for it"
                     if row.is_share else "the export carries no caption for this post")
    if row.reactions is not None:
        parts.append(f"{row.reactions:,} reactions on the export's copy")
    # Reach and engagement ride along from the same export row, so the report's
    # three Facebook columns are all one post's own figures rather than three
    # separate joins that could disagree about which post they found.
    return CellValue(value, "collected", 1.0, " · ".join(parts),
                     reach=row.reach, engagement=row.engagement)


def _by_slug(index: InsightsIndex) -> dict[str, list[InsightsRow]]:
    """Export rows grouped by page, with both caption keys computed once.

    Built per fill rather than per cell: a month's export runs to thousands of
    rows and every campaign link would otherwise rescan all of them. Each entry
    is (raw key, boilerplate-stripped key, row).
    """
    groups: dict[str, list[tuple[str, str, InsightsRow]]] = {}
    for row in index.rows:
        slug = page_slug(row.permalink)
        if slug:
            raw = normalize_caption(row.title or "")
            groups.setdefault(slug, []).append(
                (raw, strip_boilerplate(row.title or ""), row))
    return groups


def _score(key: str, raw: str, stripped: str) -> float | None:
    """How well a campaign caption matches one export title, or None if it
    doesn't clear the bar.

    Two keys, two thresholds. The raw title has to clear FUZZY_HIGH. The
    stripped title — the same caption minus Somoy's "বিস্তারিত কমেন্টে…" tail and
    hashtag block, which 83% of export rows carry and no campaign sheet ever
    does — has to clear the much stricter INSIGHTS_STRIPPED_HIGH, because the
    shorter token set makes the comparison blind to meaning-reversing words.
    """
    best = fuzz.token_set_ratio(key, raw) / 100.0
    if best >= config.FUZZY_HIGH:
        return best
    if stripped and stripped != raw:
        alt = fuzz.token_set_ratio(key, stripped) / 100.0
        if alt >= config.INSIGHTS_STRIPPED_HIGH:
            return alt
    return None


# A caption that fits two export rows on one page equally well identifies
# neither. Returned instead of a match so the caller can say so and leave the
# cell for the post-id pass, which settles it exactly.
AMBIGUOUS = object()


def _candidates(rows, caption: str, date) -> list[tuple[float, InsightsRow]]:
    """Every export row whose caption and date can account for this post.

    Ordered best-first, then by publish time nearest the campaign date. That
    ordering only separates *unequal* scores — see `_match_by_caption` for why
    an exact tie is refused rather than ranked. The campaign sheet's Date has no
    time of day, so proximity to it is systematically biased toward the earliest
    post of the day, which on a re-posted story is the copy that was replaced.
    """
    key = normalize_caption(caption or "")
    if len(key) < config.PREFIX_MIN_LEN:
        return []
    out: list[tuple[float, float, InsightsRow]] = []
    for raw, stripped, row in rows:
        if date and row.published and \
                abs(row.published.date() - date.date()) > timedelta(days=CAPTION_WINDOW_DAYS):
            continue
        score = _score(key, raw, stripped)
        if score is None:
            continue
        gap = abs((row.published - date).total_seconds()) if (row.published and date) else float("inf")
        out.append((score, gap, row))
    out.sort(key=lambda t: (-t[0], t[1]))
    return [(s, r) for s, _, r in out]


def _slug_for(url: str | None, index: InsightsIndex) -> str | None:
    """The page a campaign link points at, as the export spells it.

    Some link shapes name the page by numeric id rather than vanity slug —
    `/photo/?fbid=…&set=pb.<page-id>` and `permalink.php?…&id=<page-id>`. The
    export carries both spellings side by side, so the id translates exactly and
    those links never have to be guessed at.
    """
    if is_share_link(url):
        return None
    slug = page_slug(url)
    return index.slug_for_page_id(slug) or slug if slug else None


def _match_by_caption(groups, caption: str, url: str, date,
                      slug: str | None = None) -> tuple[InsightsRow, float] | None:
    """Match a campaign row to its export row by caption, scoped to one page.

    This is the *primary* join for `/posts/pfbid…` links, because `pfbid` blobs
    differ between the campaign sheet and the export for the same post (see
    `matching.permalink`). Scoping is what keeps it safe: only rows on the same
    page and within a few days of the campaign date are eligible — a wrong
    number in a sponsor report is worse than a blank one.

    `slug` overrides the page read off the URL, for links that name their page
    by numeric id.

    Returns `AMBIGUOUS` when the top two candidates score identically. Somoy
    re-posts a story minutes after the first attempt, and both copies carry the
    same caption on the same page — measured on April, picking either way puts
    wrong numbers in the report (one ordering got a 678-view duplicate where the
    live post had 6,519). Nothing in the caption distinguishes them, so this
    refuses to guess and leaves the cell to the post-id pass.
    """
    slug = slug or page_slug(url)
    if not slug:
        return None
    hits = _candidates(groups.get(slug, ()), caption, date)
    if not hits:
        return None
    if len(hits) > 1 and hits[0][0] == hits[1][0]:
        return AMBIGUOUS
    return (hits[0][1], hits[0][0])


def _slot_pages(runs: list[RunResult], index: InsightsIndex) -> dict[str, Counter]:
    """Which pages each FB slot actually points at, learned from the sheet.

    Campaign sheets are consistent about this — Link 1 is the main page, Link 2
    and Link 3 are subpages — but which subpage varies row to row, so the
    distribution is read off the run rather than hard-coded.
    """
    pages: dict[str, Counter] = {slot: Counter() for slot in FB_SLOTS}
    for run in runs:
        for row in run.rows:
            for slot in FB_SLOTS:
                slug = _slug_for(row.links.get(slot), index)
                if slug:
                    pages[slot][slug] += 1
    return pages


def _infer_pages(unknown: list[str], hits: list[tuple[float, InsightsRow]],
                 pages: dict[str, Counter], taken: set[str]) -> dict[str, str]:
    """Guess which page each page-less link in one campaign row belongs to.

    A `/share/p/…` or `/photo/?fbid=…&set=a.…` link names no page, so the
    caption alone cannot say which of the several Somoy pages that carried the
    same story it points at. Three things narrow it down: the story's candidate
    export rows, the pages this slot points at elsewhere in the sheet, and the
    pages the row's *other* links already account for — one post per page per
    row. Slots are assigned together so those constraints interact.

    A slot is only filled when its winning page outweighs the nearest rival by
    `config.SLOT_PAGE_DOMINANCE`; a close call means several Somoy pages ran the
    story and the sheet gives no reason to prefer one, so it stays empty.

    Rivals are settled one slot at a time, because "one post per page per row"
    removes candidates as it goes. Ruchi's June sheet is the case that forced
    it: Link 2 points at somoytvsports 54 times and somoysongbad360 47, so no
    page can ever outweigh the other 3x there. But when Link 3 takes
    somoytvsports outright (50 against 13), somoysongbad360 is the only page
    left that the row's own links have not already claimed — and a slot with no
    rival left has nothing to be wrong about. Scoring every slot against the
    full page list at once declined a cell the row itself had already decided.
    """
    available: list[str] = []
    for _, row in hits:
        slug = page_slug(row.permalink)
        if slug and slug not in taken and slug not in available:
            available.append(slug)
    if not available:
        return {}

    best, best_weight = {}, 0
    for combo in permutations(available, min(len(unknown), len(available))):
        weights = [pages[slot].get(slug, 0) for slot, slug in zip(unknown, combo)]
        if not all(weights):
            continue                      # a slot that has never seen this page
        if sum(weights) > best_weight:
            best, best_weight = dict(zip(unknown, combo)), sum(weights)

    out: dict[str, str] = {}
    pending, claimed = dict(best), set()
    while pending:
        # Only a slot that clears the bar outright may claim its page, so a
        # shaky assignment never clears the field for the slot beside it.
        settled = [slot for slot, slug in pending.items()
                   if _dominant(pages[slot], slug, available, claimed)]
        if not settled:
            break
        for slot in settled:
            out[slot] = pending.pop(slot)
            claimed.add(out[slot])
    return out


def _dominant(seen: Counter, slug: str, available: list[str],
              claimed: set[str]) -> bool:
    """Whether this slot's winning page outweighs every page still in contention.

    A page another slot has already claimed is not in contention: the row cannot
    put two of its links on one page, so that page is no longer an alternative
    reading of this one.
    """
    top = max((seen.get(other, 0) for other in available
               if other != slug and other not in claimed), default=0)
    return top == 0 or seen[slug] >= config.SLOT_PAGE_DOMINANCE * top


def fill_from_insights(
    result: RunResult | list[RunResult],
    index: InsightsIndex,
    metric: str | None = None,
    resolve_share: ShareResolver = None,
    persist=None,
) -> int:
    """Fill every empty FB cell the export can account for. Returns cells filled.

    `resolve_share` is optional: without it, facebook.com/share/… links are
    left for the collector (which already resolves them). With it, shares are
    resolved here and looked up like any other post — the case that used to
    fall straight through to an estimate.
    """
    metric = metric or config.INSIGHTS_METRIC
    runs = _as_runs(result)
    if not len(index):
        return 0

    groups = _by_slug(index)
    slot_pages = _slot_pages(runs, index)
    filled = 0
    for run in runs:
        for row_idx, row in enumerate(run.rows):
            pageless: list[str] = []
            for slot in FB_SLOTS:
                url = row.links.get(slot)
                if not url or row.cells[slot].value is not None:
                    continue

                if is_share_link(url) and resolve_share is not None:
                    try:
                        resolved = resolve_share(url)
                    except Exception as exc:      # a dead share link is not fatal
                        log.warning("share resolution failed for %s: %s", url, exc)
                        resolved = None
                    if resolved:
                        url = resolved
                        row.links[slot] = resolved

                # Exact URL first — works for the shapes carrying a durable id
                # (/videos/<id>, permalink.php?story_fbid=). pfbid links will
                # miss here by design, and fall through to the caption join.
                hit = index.lookup(url)
                cell = cell_from_insights(
                    hit, metric, how="matched by the sheet's own link") if hit else None

                if cell is None:
                    slug = _slug_for(url, index)
                    if slug is None:
                        # No page in the URL, so no group to scope against —
                        # handled once per row, after the pages the other slots
                        # account for are known.
                        pageless.append(slot)
                        continue
                    guess = _match_by_caption(groups, row.caption, url, row.date, slug)
                    if guess is AMBIGUOUS:
                        row_issue(run, row, [slot],
                                  "this page ran the same story twice and the caption "
                                  "cannot say which post the link points at")
                        continue
                    if guess:
                        found, score = guess
                        cell = cell_from_insights(
                            found, metric, how=f"matched by caption ({score:.0%})")
                        if cell:
                            cell.confidence = round(score, 3)

                if cell is None:
                    continue

                row.cells[slot] = cell
                filled += 1
                if persist is not None:
                    try:
                        persist(run, row_idx, slot, cell)
                    except Exception as exc:
                        log.warning("checkpoint failed for row_idx %s %s: %s",
                                    row_idx, slot, exc)

            filled += _fill_pageless(run, row, row_idx, pageless, groups,
                                     slot_pages, index, metric, persist)

    log.info("insights export filled %d cells from %d posts", filled, len(index))
    return filled


def _fill_pageless(run: RunResult, row, row_idx: int, slots: list[str], groups,
                   slot_pages, index: InsightsIndex, metric: str, persist) -> int:
    """Fill the row's page-less links (share/photo) once their pages are inferred.

    Done per row rather than per cell because the inference needs the whole row:
    the pages the resolvable links already account for are exactly the pages
    these links cannot be on.
    """
    if not slots:
        return 0
    hits = _candidates([e for entries in groups.values() for e in entries],
                       row.caption, row.date)
    if not hits:
        row_issue(run, row, slots,
                  "link names no page and no export row matches this caption")
        return 0

    taken = {_slug_for(row.links.get(s), index) for s in FB_SLOTS} - {None}
    inferred = _infer_pages(slots, hits, slot_pages, taken)
    filled = 0
    for slot in slots:
        slug = inferred.get(slot)
        if not slug:
            row_issue(run, row, [slot],
                      "link names no page and the sheet gives no clear page for this slot")
            continue
        found, score = next((r, s) for s, r in hits if page_slug(r.permalink) == slug)
        kind = "share" if is_share_link(row.links[slot]) else "photo"
        cell = cell_from_insights(
            found, metric,
            how=(f"page inferred as {slug} — the link is a {kind} link that names "
                 f"none ({score:.0%} caption match) — verify"))
        if cell is None:
            continue
        # Never as trustworthy as a link that named its own page: the caption and
        # the slot's usual page agree, but nothing in the URL confirms it.
        cell.confidence = round(min(score, 0.9), 3)
        row.cells[slot] = cell
        filled += 1
        if persist is not None:
            try:
                persist(run, row_idx, slot, cell)
            except Exception as exc:
                log.warning("checkpoint failed for row_idx %s %s: %s", row_idx, slot, exc)
    return filled


def row_issue(run: RunResult, row, slots: list[str], reason: str) -> None:
    """Record why a cell stayed empty, so the dashboard can say so."""
    run.issues.append(RowIssue(
        f"{run.brand} {run.month}", row.no,
        f"{'/'.join(s.upper() for s in slots)}: {reason}"))


def fill_instagram_from_insights(result: RunResult | list[RunResult],
                                 index: InsightsIndex, metric: str | None = None,
                                 persist=None) -> int:
    """Fill Instagram cells from an Instagram content export. Returns cells filled.

    Nothing here resembles the Facebook path, and that is the point. An Instagram
    shortcode is stable — the code in a link someone copied is the code in Meta's
    export — so this is a plain exact join needing no browser visit, no caption
    comparison and no page inference. Facebook needs all three only because its
    `pfbid` blobs differ between the two sources.
    """
    metric = metric or config.INSIGHTS_METRIC
    runs = _as_runs(result)
    if not len(index):
        return 0
    filled = 0
    for run in runs:
        for row_idx, row in enumerate(run.rows):
            url = row.links.get("ig")
            if not url or row.cells["ig"].value is not None:
                continue
            hit = index.lookup_ig(url)
            if hit is None:
                continue
            cell = cell_from_insights(hit, metric,
                                      how="matched by the post's shortcode")
            if cell is None:
                continue
            row.cells["ig"] = cell
            filled += 1
            if persist is not None:
                try:
                    persist(run, row_idx, "ig", cell)
                except Exception as exc:
                    log.warning("checkpoint failed for row_idx %s ig: %s", row_idx, exc)
    if filled:
        log.info("instagram export filled %d cells", filled)
    return filled



def uncovered_pages(result: RunResult | list[RunResult],
                    index: InsightsIndex) -> dict[str, int]:
    """Pages the campaign links but no supplied export contains, and how many
    links land on each. Nothing can resolve those cells — not the caption, not a
    post id — so the only fix is to export that page, and the run should say so
    once rather than leaving a per-row mystery."""
    out: dict[str, int] = {}
    for run in _as_runs(result):
        for row in run.rows:
            for slot in FB_SLOTS:
                slug = _slug_for(row.links.get(slot), index)
                if slug and not index.covers(slug):
                    out[slug] = out.get(slug, 0) + 1
    return out


def note_unaccounted(result: RunResult | list[RunResult],
                     index: InsightsIndex | None = None) -> int:
    """Say why a linked cell is still empty, once the exports have had their turn.

    Until this runs a cell reads "awaiting the insights export", which is what
    `rules.build_row` sets *before* one has been consulted — and which reads,
    wrongly, as "you have not supplied it yet". The commonest reason a supplied
    export cannot account for a Facebook post is that Meta recorded no caption
    for it: 26.7% of one real month's main-page rows carry a blank Title, most
    of them shared or photo posts. No caption can find those and nothing is
    wrong with the sheet — only the post's own id will do it.
    """
    changed = 0
    for run in _as_runs(result):
        for row in run.rows:
            for slot in FB_SLOTS + ("ig",):
                cell = row.cells[slot]
                if not row.links.get(slot) or cell.value is not None:
                    continue
                if not cell.note.startswith("awaiting the "):
                    continue        # something more specific already explains it
                slug = _slug_for(row.links.get(slot), index) if index else None
                if slot == "ig":
                    cell.note = "the Instagram export has no row for this post"
                elif index is not None and slug and not index.covers(slug):
                    cell.note = (f"none of the supplied exports cover {slug} — "
                                 "export that page and this cell fills itself; "
                                 "no post id can rescue a page that is not there")
                else:
                    cell.note = (
                        "the exports could not account for this post — its caption "
                        "matches nothing on this page, which is normal for a shared "
                        "or photo post Meta recorded no caption for. Resolve Facebook "
                        "posts will identify it by its post id.")
                changed += 1
    return changed


# --- caption repair: rows whose sheet caption no longer describes the post ---
#
# The campaign sheet is hand-maintained. Someone writes a caption and pastes the
# links; later the caption is edited ON THE POST and nobody updates the sheet.
# Because one caption serves every FB slot in its row, a stale one breaks the
# whole row at once — measured on June, 72 cells across 40 rows.
#
# It cannot be repaired offline. For 32 of those 40 rows the sheet's caption does
# not reach even 0.70 against any post on one of the linked pages: the text was
# rewritten, not tweaked. Lowering the bar produces wrong numbers rather than
# missing ones (a "gold price cut" post scored 0.93 against a "gold price raised"
# caption). So one post per row is read through the browser, and the row's
# remaining slots are recovered from that anchor here.

# Which slot earns the visit. Subpages first: the mainpage is the page most
# likely to have had its headline rewritten, so anchoring elsewhere leaves the
# hardest cell to be recovered rather than depended on. Measured on June the
# difference is small (99.3% vs 99.1% sibling accuracy) but it is free.
REPAIR_SLOT_ORDER = ("fb2", "fb3", "fb1")



def _agrees(anchor: InsightsRow, other: InsightsRow) -> float | None:
    """How firmly two export rows describe the same story, or None below the bar.

    Both sides are Meta's own text, so this is a near-identity test rather than
    the lenient sheet-caption comparison in `_score`. Compared on the
    boilerplate-stripped titles, since the tail and hashtag block are page
    furniture that differs between a mainpage and a subpage post.
    """
    score = fuzz.token_set_ratio(strip_boilerplate(anchor.title or ""),
                                 strip_boilerplate(other.title or "")) / 100.0
    return score if score >= config.REPAIR_SIBLING_HIGH else None


def _story_siblings(rows, anchor: InsightsRow) -> list[tuple[float, InsightsRow]]:
    """Export rows that are the same story as `anchor`, best agreement first."""
    if anchor.published is None:
        return []
    window = timedelta(minutes=config.REPAIR_SIBLING_WINDOW_MIN)
    out = []
    for entry in rows:
        row = entry[2] if isinstance(entry, tuple) else entry
        if row is anchor or row.published is None:
            continue
        if abs(row.published - anchor.published) > window:
            continue
        score = _agrees(anchor, row)
        if score is not None:
            out.append((score, row))
    out.sort(key=lambda t: -t[0])
    return out


def refresh_caption(row, text: str) -> str:
    """Put the post's own caption on the row, preserving the sheet's.

    Returns the text that was replaced, or "" when nothing changed. Idempotent:
    a second repair never overwrites `original_caption` with the first repair's
    output, so the sheet's wording stays recoverable however often this runs.
    """
    new = strip_boilerplate(text or "")
    old = row.caption or ""
    if not new or normalize_caption(new) == normalize_caption(old):
        return ""
    if not row.original_caption:
        row.original_caption = old
    row.caption = new
    return old


def fill_row_from_anchor(run: RunResult, row, row_idx: int, anchor_slot: str,
                         anchor: InsightsRow, groups, slot_pages,
                         index: InsightsIndex, metric: str | None = None,
                         persist=None) -> int:
    """Fill the row's other empty FB slots from the post the browser identified.

    No further navigation. Somoy cross-posts one story to several pages within
    minutes, so each remaining slot's post is the row on that slot's own page
    whose export title agrees with the anchor's. A runner-up within
    `REPAIR_SIBLING_MARGIN` declines the slot instead of guessing — that is the
    same story running twice on one page, and the sheet gives no way to say
    which of the two the link points at.
    """
    metric = metric or config.INSIGHTS_METRIC
    filled = 0
    for slot in FB_SLOTS:
        if slot == anchor_slot or not row.links.get(slot):
            continue
        if row.cells[slot].value is not None:
            continue
        url = row.links[slot]
        slug = _slug_for(url, index)
        if slug:
            hits = _story_siblings(groups.get(slug, ()), anchor)
        else:
            # A share or album-photo link names no page. Same story agreement,
            # but the page comes from where this slot points elsewhere in the
            # sheet — `_infer_pages` and its dominance guard, fed a much better
            # candidate set than a stale caption could produce.
            everything = [e for entries in groups.values() for e in entries]
            hits = _story_siblings(everything, anchor)
            taken = {_slug_for(row.links.get(s), index) for s in FB_SLOTS} - {None}
            taken.add(page_slug(anchor.permalink))
            chosen = _infer_pages([slot], hits, slot_pages, taken).get(slot)
            hits = [(s, r) for s, r in hits if page_slug(r.permalink) == chosen] \
                if chosen else []
        if not hits:
            row_issue(run, row, [slot],
                      f"no post on this page matches the {anchor_slot.upper()} post "
                      "read from Facebook")
            continue
        if len(hits) > 1 and hits[0][0] - hits[1][0] < config.REPAIR_SIBLING_MARGIN:
            row_issue(run, row, [slot],
                      "two posts on this page carry the same story — the link "
                      "does not say which one it is")
            continue
        score, found = hits[0]
        apart = int(abs((found.published - anchor.published).total_seconds()) // 60)
        cell = cell_from_insights(
            found, metric,
            how=(f"same story as the {anchor_slot.upper()} post read from Facebook "
                 f"({score:.0%} title agreement, {apart}m apart)"))
        if cell is None:
            continue
        # Never 1.0: the story matches, but this slot's URL never confirmed it.
        cell.confidence = round(min(score, 0.95), 3)
        row.cells[slot] = cell
        filled += 1
        if persist is not None:
            try:
                persist(run, row_idx, slot, cell)
            except Exception as exc:
                log.warning("checkpoint failed for row_idx %s %s: %s", row_idx, slot, exc)
    return filled
