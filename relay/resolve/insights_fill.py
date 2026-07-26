"""Fill unresolved Facebook cells from Meta's own insights export (SRS FR-13a).

Sits between matching and the browser collectors, so the resolution order is:

    supervisor matched file  ->  insights export  ->  reactions x k

The supervisor file stays primary and is never overwritten. The export is
consulted only for cells it left empty — which is where the reactions estimate
used to fire, and where it was measured to be wrong for ~92% of posts.

The value written is an exact integer from Meta, and its note names the source
file and post id so the client can trace any figure back to a row in the export
they were handed.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from itertools import permutations
from typing import Callable, Optional

from rapidfuzz import fuzz

from .. import config
from ..ingest.insights import InsightsIndex
from ..matching.normalize import normalize_caption
from ..matching.permalink import is_share_link, page_slug
from ..models import CellValue, InsightsRow, RunResult

log = logging.getLogger("relay.resolve")

FB_SLOTS = ("fb1", "fb2", "fb3")
CAPTION_WINDOW_DAYS = 3

# Resolves a facebook.com/share/… link to its canonical permalink. Injected so
# this module never imports Playwright — see collectors.mbs.resolve_share_link.
ShareResolver = Optional[Callable[[str], Optional[str]]]


def _as_runs(result) -> list[RunResult]:
    return list(result) if isinstance(result, (list, tuple)) else [result]


def cell_from_insights(row: InsightsRow, metric: str | None = None) -> CellValue | None:
    """An exact, auditable cell from one export row — the note names the source
    file and post id so any figure can be traced back to the client's copy."""
    metric = metric or config.INSIGHTS_METRIC
    value = row.metric(metric)
    if value is None:
        return None
    label = "Reach" if metric == "reach" else "Views"
    note = f"insights export {row.source_file} · post {row.post_id} · {label}"
    return CellValue(value, "collected", 1.0, note)


def _by_slug(index: InsightsIndex) -> dict[str, list[InsightsRow]]:
    """Export rows grouped by page, with captions pre-normalized once.

    Built per fill rather than per cell: a month's export runs to thousands of
    rows and every campaign link would otherwise rescan all of them.
    """
    groups: dict[str, list[InsightsRow]] = {}
    for row in index.rows:
        slug = page_slug(row.permalink)
        if slug:
            groups.setdefault(slug, []).append(row)
    return groups


def _match_by_caption(groups: dict[str, list[InsightsRow]], caption: str,
                      url: str, date) -> tuple[InsightsRow, float] | None:
    """Match a campaign row to its export row by caption, scoped to one page.

    This is the *primary* join for `/posts/pfbid…` links, because `pfbid` blobs
    differ between the campaign sheet and the export for the same post (see
    `matching.permalink`). Scoping is what keeps it safe: only rows on the same
    page and within a few days of the campaign date are eligible, and the bar is
    FUZZY_HIGH — a wrong number in a sponsor report is worse than a blank one.
    """
    key = normalize_caption(caption or "")
    if len(key) < config.PREFIX_MIN_LEN:
        return None
    slug = page_slug(url)
    if not slug:
        return None
    best: tuple[InsightsRow, float] | None = None
    for row in groups.get(slug, ()):
        if date and row.published and \
                abs(row.published.date() - date.date()) > timedelta(days=CAPTION_WINDOW_DAYS):
            continue
        score = fuzz.token_set_ratio(key, normalize_caption(row.title or "")) / 100.0
        if score >= config.FUZZY_HIGH and (best is None or score > best[1]):
            best = (row, score)
    return best


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
    filled = 0
    for run in runs:
        for row_idx, row in enumerate(run.rows):
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
                cell = cell_from_insights(hit, metric) if hit else None

                if cell is None and not is_share_link(url):
                    guess = _match_by_caption(groups, row.caption, url, row.date)
                    if guess:
                        found, score = guess
                        cell = cell_from_insights(found, metric)
                        if cell:
                            cell.confidence = round(score, 3)
                            cell.note += f" · matched by caption ({score:.0%})"

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

    log.info("insights export filled %d cells from %d posts", filled, len(index))
    return filled


SUB_SLOTS = ("fb2", "fb3")


def _export_target(groups, index: InsightsIndex, url: str, caption: str,
                   date, metric: str) -> int | None:
    """The export's own figure for whatever post `url` points at."""
    hit = index.lookup(url)
    if hit is None and not is_share_link(url):
        guess = _match_by_caption(groups, caption, url, date)
        hit = guess[0] if guess else None
    return hit.metric(metric) if hit else None


def reassign_subpage_slots(result: RunResult | list[RunResult], index: InsightsIndex,
                           metric: str | None = None) -> int:
    """Put each supervisor value on the slot whose page actually earned it.

    `rules.py` assumes the supervisor's `Views_Match_1` is Somoy Shongbad and
    `Views_Match_2..N` the category pages (FR-10). It isn't: their file lists
    values in whatever order its scraper found them, so a sizeable share of the
    time VM1 belongs to the category page instead. Checked against the export on
    a real month, a substantial minority of verifiable FB cells carried a
    different page's number — the row total stayed right while the columns were
    swapped.

    This does not change any number. It permutes the values the supervisor
    supplied across that row's own FB slots, choosing the arrangement that best
    matches each linked page's figure in the export. A value can only move to
    another slot in the same row, and only when the export can identify at
    least two of those slots' posts.

    Returns the number of cells whose slot changed.
    """
    metric = metric or config.INSIGHTS_METRIC
    runs = _as_runs(result)
    if not len(index):
        return 0

    groups = _by_slug(index)
    moved = 0
    for run in runs:
        for row in run.rows:
            slots = [s for s in SUB_SLOTS
                     if row.links.get(s) and row.cells[s].provenance == "matched"
                     and row.cells[s].value is not None]
            if len(slots) < 2:
                continue

            targets = {s: _export_target(groups, index, row.links[s], row.caption,
                                         row.date, metric) for s in slots}
            known = [s for s in slots if targets[s]]
            if len(known) < 2:
                continue    # nothing to arbitrate between

            values = [row.cells[s].value for s in slots]

            def cost(order):
                return sum(abs(order[slots.index(s)] - targets[s]) / targets[s]
                           for s in known)

            best = min(permutations(values), key=cost)
            if list(best) == values or cost(best) >= cost(values):
                continue

            originals = {s: row.cells[s] for s in slots}
            for slot, value in zip(slots, best):
                if originals[slot].value == value:
                    continue
                came_from = next(s for s in slots if originals[s].value == value)
                cell = originals[came_from]
                note = (cell.note + "; " if cell.note else "") + \
                    f"slot corrected from {came_from.upper()} — the insights export " \
                    f"attributes this figure to {page_slug(row.links[slot])}"
                row.cells[slot] = CellValue(value, cell.provenance, cell.confidence, note)
                moved += 1

    if moved:
        log.info("insights export corrected the slot of %d supervisor values", moved)
    return moved


def fit_k_table(index: InsightsIndex, metric: str | None = None) -> dict[tuple[int, int], float]:
    """Fit the reactions->views multiplier from the user's own export data.

    A single k cannot describe this relationship: measured on a real export the
    ratio falls steeply as engagement rises — several hundred x on posts with a
    handful of reactions, down to tens of x on the busiest — so a flat 70-120
    landed close for only a small fraction of posts. Bucketing by reaction count
    and taking each bucket's median tracks that curve.

    Buckets with too few samples are omitted; callers fall back to K_DEFAULT.
    """
    metric = metric or config.INSIGHTS_METRIC
    samples: dict[tuple[int, int], list[float]] = {b: [] for b in config.K_BUCKETS}
    for row in index.rows:
        value, reactions = row.metric(metric), row.reactions
        if not value or not reactions or reactions <= 0:
            continue
        for lo, hi in config.K_BUCKETS:
            if lo <= reactions <= hi:
                samples[(lo, hi)].append(value / reactions)
                break

    table: dict[tuple[int, int], float] = {}
    for bucket, ratios in samples.items():
        if len(ratios) < config.K_BUCKET_MIN_SAMPLES:
            continue
        ratios.sort()
        mid = len(ratios) // 2
        median = ratios[mid] if len(ratios) % 2 else (ratios[mid - 1] + ratios[mid]) / 2
        table[bucket] = round(median, 1)
    return table
