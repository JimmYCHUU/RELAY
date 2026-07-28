"""Collector orchestration: fill missing cells in a RunResult (opt-in)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from .. import config
from ..models import CellValue, RunResult
from .base import BudgetExceeded, ChallengeDetected, Pacer

log = logging.getLogger("relay.collectors")


@dataclass
class Progress:
    """Mutable job status the dashboard polls while a collector runs."""
    total: int = 0
    done: int = 0
    filled: int = 0
    current: str = ""
    state: str = "running"           # running | finished | stopped | error
    message: str = ""
    stop_requested: bool = False     # set by the dashboard's Stop button
    events: list[str] = field(default_factory=list)

    def log(self, line: str) -> None:
        self.events.append(line)
        del self.events[:-40]


ProgressCb = Optional[Progress]

# Checkpoint hook: (run, row_idx, slot, cell), called after every filled cell
# so a crash/power-off mid-collection loses nothing already collected.
PersistCb = Optional[Callable[[RunResult, int, str, CellValue], None]]

# Checkpoint hook for a repaired caption: (run, row_idx, anchor_slot, original,
# repaired). Each one costs a paced browser visit, so it is worth the same
# crash-safety as a collected cell.
PersistCaptionCb = Optional[Callable[[RunResult, int, str, str, str], None]]

# Worth spelling out on the cell rather than only in the progress log: a reader
# checking this figure against their own copy of the export will search by the
# sheet's link and find nothing, because the two name the same post with
# different `pfbid` blobs. Only Meta's numeric id is shared between them.
_BY_POST_ID = ("identified by post id read from the post page — the sheet's link "
               "and the export use different pfbid blobs")


def _checkpoint(persist: PersistCb, run: RunResult, row_idx: int, slot: str,
                cell: CellValue, p: Progress) -> None:
    if persist is None:
        return
    try:
        persist(run, row_idx, slot, cell)
    except Exception as exc:  # a checkpoint hiccup must never abort collection
        log.warning("checkpoint failed for row_idx %s %s: %s", row_idx, slot, exc)
        p.log(f"checkpoint failed for {slot} (row_idx {row_idx}): {type(exc).__name__}")


def _as_runs(result) -> list[RunResult]:
    """Collectors accept one run or a whole cycle's worth — one shared Pacer
    budget either way (safer than per-brand resets)."""
    return list(result) if isinstance(result, (list, tuple)) else [result]


def collect_x(result: RunResult | list[RunResult], pacer: Pacer | None = None,
              progress: ProgressCb = None, limit: int | None = None,
              persist: PersistCb = None) -> int:
    """Fill X impression cells from public status pages — logged-out browser,
    no credentials ever (C-3). Returns cells filled."""
    from .browser import anonymous_page
    from .xpublic import collect_x_views, extract_tweet_text

    runs = _as_runs(result)
    tag = (lambda run: f"{run.brand} · ") if len(runs) > 1 else (lambda run: "")
    pacer = pacer or Pacer(min_delay=config.X_PACE_MIN_S, max_delay=config.X_PACE_MAX_S)
    p = progress or Progress()
    targets = [(run, idx, r) for run in runs for idx, r in enumerate(run.rows)
               if r.links.get("x") and r.cells["x"].value is None]
    if limit is not None:
        targets = targets[:limit]
    p.total = len(targets)
    if not targets:
        p.state, p.message = "finished", "no X cells to fill"
        return 0

    if pacer.dry_run:
        for _run, _idx, row in targets:
            pacer.before_visit(row.links["x"])
            p.done += 1
        p.state, p.message = "finished", f"dry-run: would visit {p.total} pages"
        return 0

    filled = 0
    try:
        with anonymous_page() as page:
            for run, idx, row in targets:
                if p.stop_requested:
                    break
                url = row.links["x"]
                p.current = url
                cell = collect_x_views(page, url, pacer)
                if not row.caption:
                    cap = extract_tweet_text(page)
                    if cap:
                        row.caption = cap
                        p.log(f"{tag(run)}row {row.no}: caption recovered from the post")
                p.done += 1
                if cell.value is not None:
                    row.cells["x"] = cell
                    filled += 1
                    p.filled = filled
                    p.log(f"{tag(run)}row {row.no}: {cell.value:,} views")
                    _checkpoint(persist, run, idx, "x", cell, p)
                else:
                    p.log(f"{tag(run)}row {row.no}: {cell.note}")
    except BudgetExceeded as exc:
        p.state, p.message = "stopped", str(exc)
        return filled
    except Exception as exc:
        log.exception("x collection aborted")
        p.state, p.message = "error", f"{type(exc).__name__}: {exc}"
        return filled
    if p.stop_requested:
        p.state, p.message = "stopped", f"stopped — filled {filled} of {p.done} visited"
    else:
        p.state = "finished"
        p.message = f"filled {filled} of {p.total} X cells"
    return filled


def resolve_facebook(result: RunResult | list[RunResult], pacer: Pacer | None = None,
                     headed: bool = False, progress: ProgressCb = None,
                     limit: int | None = None, persist: PersistCb = None,
                     persist_caption: PersistCaptionCb = None) -> int:
    """Account for every Facebook cell the export could not reach on its own.

    One pass, one mechanism: identify the post, then take Meta's own figure for
    it. A post is identified by the numeric id read off its page — the only key
    the live post and the export share, since a `pfbid` differs between a copied
    link and the export, and a rewritten or placeholder caption matches nothing.

    Nothing here estimates. A cell this pass cannot account for stays empty, and
    the reason is recorded; a multiplier applied to reactions was measured wrong
    for ~92% of posts, and a blank cell is worth more to a sponsor than a
    plausible invention.

    Visits are spent sparingly rather than one per cell. Share links resolve to a
    permalink the export already knows. The first post identified in a row also
    identifies that row's other posts for free, because Somoy cross-posts one
    story to several pages within minutes — so a three-link row usually costs one
    visit, and only what remains unaccounted for is visited in turn.

    Refreshing a stale sheet caption falls out of the same work: once the post is
    identified, the export's title is what it actually says now.
    """
    from ..resolve.insights_fill import (FB_SLOTS, REPAIR_SLOT_ORDER, _by_slug,
                                         _slot_pages, _slug_for,
                                         cell_from_insights, fill_row_from_anchor,
                                         refresh_caption, row_issue)
    from ..matching.permalink import is_share_link
    from .browser import persistent_session
    from .mbs import collect_fb_post, extract_caption, resolve_share_link

    runs = _as_runs(result)
    tag = (lambda run: f"{run.brand} · ") if len(runs) > 1 else (lambda run: "")
    pacer = pacer or Pacer()
    p = progress or Progress()

    index = next((r.insights for r in runs if getattr(r, "insights", None)), None)
    if index is None or not len(index):
        p.state = "finished"
        p.message = "no insights export loaded — nothing to identify posts against"
        return 0

    # Grouped by row, because the sibling shortcut is a per-row saving.
    targets = []
    for run in runs:
        for row_idx, row in enumerate(run.rows):
            slots = [s for s in FB_SLOTS
                     if row.links.get(s) and row.cells[s].value is None]
            if slots:
                targets.append((run, row_idx, row, slots))
    if limit is not None:
        targets = targets[:limit]
    p.total = len(targets)
    if not targets:
        p.state, p.message = "finished", "every Facebook cell is already accounted for"
        return 0

    if pacer.dry_run:
        for _run, _idx, row, slots in targets:
            pacer.before_visit(row.links[slots[0]])
            p.done += 1
        p.state, p.message = "finished", f"dry-run: would visit up to {p.total} posts"
        return 0

    groups, slot_pages = _by_slug(index), _slot_pages(runs, index)
    filled = captions = 0
    try:
        with persistent_session("meta", headed=headed) as sess:
            for run, row_idx, row, slots in targets:
                if p.stop_requested:
                    break
                anchor = None
                # Subpages first: the main page is the one whose headline is most
                # often rewritten, so anchoring elsewhere leaves the hardest cell
                # to be recovered rather than depended on.
                ordered = [s for s in REPAIR_SLOT_ORDER if s in slots]
                for slot in ordered:
                    if p.stop_requested:
                        break
                    if row.cells[slot].value is not None:
                        continue        # a sibling pass already accounted for it
                    url = row.links[slot]
                    p.current = url
                    try:
                        page = sess.page()
                        if is_share_link(url):
                            url = resolve_share_link(page, url, pacer)
                            row.links[slot] = url
                            hit = index.lookup(url)
                            cell = cell_from_insights(
                                hit, how="matched by permalink after resolving the "
                                         "share link") if hit else None
                            if cell is not None:
                                row.cells[slot] = cell
                                filled += 1
                                p.filled = filled
                                p.log(f"{tag(run)}row {row.no} {slot}: {cell.value:,} "
                                      "(export, via the resolved share link)")
                                _checkpoint(persist, run, row_idx, slot, cell, p)
                                continue

                        _cell, _reactions, post_id = collect_fb_post(page, url, pacer)
                        hit = index.lookup_post_id(post_id)
                        if hit is None:
                            # og:description on a deleted or restricted post is
                            # Facebook's boilerplate or the page bio, and the tab
                            # title carries the page name — good enough to show a
                            # human only when the sheet said nothing at all.
                            if not row.caption:
                                cap = extract_caption(page)
                                if cap and refresh_caption(row, cap):
                                    captions += 1
                                    p.log(f"{tag(run)}row {row.no}: caption read "
                                          "from the post")
                            slug = _slug_for(url, index)
                            row_issue(run, row, [slot],
                                      f"none of the supplied exports cover {slug} — "
                                      "no post id can resolve a page that is not there"
                                      if slug and not index.covers(slug) else
                                      "the post was reached but its id is in none of "
                                      "the supplied exports, so this cell stays empty")
                            continue

                        cell = cell_from_insights(hit, how=_BY_POST_ID)
                        if cell is not None:
                            row.cells[slot] = cell
                            filled += 1
                            p.filled = filled
                            p.log(f"{tag(run)}row {row.no} {slot}: {cell.value:,} "
                                  "(export, matched by post id)")
                            _checkpoint(persist, run, row_idx, slot, cell, p)

                        if anchor is None:
                            anchor = hit
                            was = refresh_caption(row, hit.title)
                            if was:
                                captions += 1
                                p.log(f"{tag(run)}row {row.no}: caption refreshed "
                                      "from the post")
                                if persist_caption is not None:
                                    try:
                                        persist_caption(run, row_idx, slot, was,
                                                        row.caption)
                                    except Exception as exc:
                                        log.warning("caption checkpoint failed for "
                                                    "row_idx %s: %s", row_idx, exc)
                            got = fill_row_from_anchor(run, row, row_idx, slot, hit,
                                                       groups, slot_pages, index,
                                                       persist=persist)
                            if got:
                                filled += got
                                p.filled = filled
                                p.log(f"{tag(run)}row {row.no}: {got} more cell(s) "
                                      "from the same story on the other pages")
                    except (BudgetExceeded, ChallengeDetected):
                        raise
                    except Exception as exc:
                        p.log(f"{tag(run)}row {row.no} {slot}: failed "
                              f"({type(exc).__name__})")
                p.done += 1
    except (BudgetExceeded, ChallengeDetected) as exc:
        p.state, p.message = "stopped", str(exc)
        return filled
    except Exception as exc:
        log.exception("facebook resolution aborted")
        p.state, p.message = "error", f"{type(exc).__name__}: {exc}"
        return filled
    tail = (f"filled {filled} Facebook cells and refreshed {captions} captions "
            f"over {p.done} rows")
    if p.stop_requested:
        p.state, p.message = "stopped", f"stopped — {tail}"
    else:
        p.state, p.message = "finished", tail
    return filled


def collect_instagram(result: RunResult | list[RunResult], pacer: Pacer | None = None,
                      headed: bool = False, progress: ProgressCb = None,
                      limit: int | None = None, persist: PersistCb = None) -> int:
    """Fill missing Instagram cells from post pages via the user's Meta
    session (same persistent profile as Facebook).

    Only for what the Instagram export could not account for — which is little,
    since an Instagram shortcode joins the export exactly. Reels carry a real
    view count; a photo post that shows none leaves the cell empty rather than
    inferring one from its likes."""
    from .browser import persistent_session
    from .instagram import collect_ig_post, extract_ig_caption

    runs = _as_runs(result)
    tag = (lambda run: f"{run.brand} · ") if len(runs) > 1 else (lambda run: "")
    pacer = pacer or Pacer()
    p = progress or Progress()
    targets = [(run, idx, row) for run in runs for idx, row in enumerate(run.rows)
               if row.links.get("ig") and row.cells["ig"].value is None]
    if limit is not None:
        targets = targets[:limit]
    p.total = len(targets)
    if not targets:
        p.state, p.message = "finished", "no missing Instagram cells"
        return 0

    if pacer.dry_run:
        for _run, _idx, row in targets:
            pacer.before_visit(row.links["ig"])
            p.done += 1
        p.state, p.message = "finished", f"dry-run: would visit {p.total} posts"
        return 0

    filled = 0
    try:
        with persistent_session("meta", headed=headed) as sess:
            for run, idx, row in targets:
                if p.stop_requested:
                    break
                page = sess.page()
                url = row.links["ig"]
                p.current = url
                try:
                    cell, likes = collect_ig_post(page, url, pacer)
                    if not row.caption:
                        cap = extract_ig_caption(page)
                        if cap:
                            row.caption = cap
                            p.log(f"{tag(run)}row {row.no}: caption recovered from the post")
                    if cell.value is not None:
                        row.cells["ig"] = cell
                        filled += 1
                        p.log(f"{tag(run)}row {row.no}: {cell.value:,} views")
                        _checkpoint(persist, run, idx, "ig", cell, p)
                    else:
                        p.log(f"{tag(run)}row {row.no}: {cell.note}")
                except (BudgetExceeded, ChallengeDetected):
                    raise
                except Exception as exc:
                    p.log(f"{tag(run)}row {row.no}: failed ({type(exc).__name__})")
                finally:
                    p.done += 1
                p.filled = filled
    except (BudgetExceeded, ChallengeDetected) as exc:
        p.state, p.message = "stopped", str(exc)
        return filled
    except Exception as exc:
        log.exception("instagram collection aborted")
        p.state, p.message = "error", f"{type(exc).__name__}: {exc}"
        return filled
    if p.stop_requested:
        p.state, p.message = "stopped", f"stopped — filled {filled} of {p.done} visited"
    else:
        p.state = "finished"
        p.message = f"filled {filled} of {p.total} Instagram cells"
    return filled


def meta_profile_exists() -> bool:
    from pathlib import Path
    prof = Path(config.PROFILE_DIR) / "meta"
    return (prof / ".relay-login-complete").exists()
