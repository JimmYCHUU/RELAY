"""Collector orchestration: fill missing cells in a RunResult (opt-in)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from .. import config
from ..models import CellValue, RunResult
from ..resolve.heuristic import estimate_views
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


def collect_facebook(result: RunResult | list[RunResult], k: float | None = None,
                     pacer: Pacer | None = None,
                     headed: bool = False, progress: ProgressCb = None,
                     limit: int | None = None, persist: PersistCb = None) -> int:
    """Fill missing FB cells via the user's Meta Business Suite session;
    shared posts fall back to reactions × k estimation automatically."""
    from .browser import persistent_session
    from .mbs import collect_fb_post, extract_caption, resolve_share_link

    from ..resolve.insights_fill import cell_from_insights, fit_k_table

    runs = _as_runs(result)
    tag = (lambda run: f"{run.brand} · ") if len(runs) > 1 else (lambda run: "")
    pacer = pacer or Pacer()
    p = progress or Progress()

    # Meta's export is the source of truth; the multiplier only ever fills what
    # it cannot account for, and its k is fitted from that same export rather
    # than guessed (a flat 70-120 was measured right for few posts).
    index = next((r.insights for r in runs if getattr(r, "insights", None)), None)
    k_table = fit_k_table(index) if index is not None and len(index) else None
    if k_table:
        p.log(f"multiplier fitted from {len(index):,} posts in the insights export")

    targets = [
        (run, idx, row, slot)
        for run in runs
        for idx, row in enumerate(run.rows)
        for slot in ("fb1", "fb2", "fb3")
        if row.links.get(slot) and row.cells[slot].value is None
    ]
    if limit is not None:
        targets = targets[:limit]
    p.total = len(targets)
    if not targets:
        p.state, p.message = "finished", "no missing Facebook cells"
        return 0

    if pacer.dry_run:
        for _run, _idx, row, slot in targets:
            pacer.before_visit(row.links[slot])
            p.done += 1
        p.state, p.message = "finished", f"dry-run: would visit {p.total} posts"
        return 0

    filled = 0
    try:
        with persistent_session("meta", headed=headed) as sess:
            for run, idx, row, slot in targets:
                if p.stop_requested:
                    break
                page = sess.page()
                url = row.links[slot]
                p.current = url
                try:
                    if "/share/" in url:
                        url = resolve_share_link(page, url, pacer)
                        row.links[slot] = url
                        # A share/p link usually points at a post on one of the
                        # user's own pages, so the export almost always has it —
                        # this is the case that used to fall straight through to
                        # an estimate for want of a resolved URL.
                        hit = index.lookup(url) if index is not None else None
                        if hit is not None:
                            cell = cell_from_insights(hit)
                            if cell is not None:
                                row.cells[slot] = cell
                                filled += 1
                                p.filled = filled
                                p.log(f"{tag(run)}row {row.no} {slot}: {cell.value:,} "
                                      f"(insights export, resolved share)")
                                _checkpoint(persist, run, idx, slot, cell, p)
                                continue    # `finally` below still counts the visit
                    cell, reactions, post_id = collect_fb_post(page, url, pacer)
                    if not row.caption:
                        cap = extract_caption(page)
                        if cap:
                            row.caption = cap
                            p.log(f"{tag(run)}row {row.no}: caption recovered from the post")

                    # Meta's numeric post id is the one key shared with the
                    # export. It rescues exactly the rows nothing else can:
                    # mainpage posts, whose headline is rewritten so the
                    # photocard caption never matches, and whose pfbid differs
                    # between the sheet's link and the export.
                    if cell.value is None and index is not None:
                        hit = index.lookup_post_id(post_id)
                        exact = cell_from_insights(hit) if hit else None
                        if exact is not None:
                            row.cells[slot] = exact
                            filled += 1
                            p.filled = filled
                            p.log(f"{tag(run)}row {row.no} {slot}: {exact.value:,} "
                                  f"(insights export, matched by post id)")
                            _checkpoint(persist, run, idx, slot, exact, p)
                            continue

                    if cell.value is not None:
                        row.cells[slot] = cell
                        filled += 1
                        p.log(f"{tag(run)}row {row.no} {slot}: {cell.value:,} views")
                        _checkpoint(persist, run, idx, slot, cell, p)
                    elif reactions:
                        # k fitted per reaction bucket when the export is loaded,
                        # otherwise a fresh random multiplier for every cell
                        est = estimate_views(reactions, k, k_table=k_table)
                        if est.value is None:
                            p.log(f"{tag(run)}row {row.no} {slot}: {est.note}")
                        else:
                            row.cells[slot] = est
                            filled += 1
                            p.log(f"{tag(run)}row {row.no} {slot}: estimated "
                                  f"{est.value:,} ({est.note})")
                            _checkpoint(persist, run, idx, slot, est, p)
                    else:
                        p.log(f"{tag(run)}row {row.no} {slot}: {cell.note}")
                except (BudgetExceeded, ChallengeDetected):
                    raise
                except Exception as exc:
                    p.log(f"{tag(run)}row {row.no} {slot}: failed ({type(exc).__name__})")
                finally:
                    p.done += 1
                p.filled = filled
    except BudgetExceeded as exc:
        p.state, p.message = "stopped", str(exc)
        return filled
    except ChallengeDetected as exc:
        p.state, p.message = "stopped", str(exc)
        return filled
    except Exception as exc:
        log.exception("fb collection aborted")
        p.state, p.message = "error", f"{type(exc).__name__}: {exc}"
        return filled
    if p.stop_requested:
        p.state, p.message = "stopped", f"stopped — filled {filled} of {p.done} visited"
    else:
        p.state = "finished"
        p.message = f"filled {filled} of {p.total} Facebook cells"
    return filled


def collect_instagram(result: RunResult | list[RunResult], k: float | None = None,
                      pacer: Pacer | None = None,
                      headed: bool = False, progress: ProgressCb = None,
                      limit: int | None = None, persist: PersistCb = None) -> int:
    """Fill missing Instagram cells from post pages via the user's Meta
    session (same persistent profile as Facebook). Reels carry a real view
    count; photo posts fall back to likes × k estimation, marked ≈."""
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
                    elif likes:
                        # k=None -> a fresh random multiplier for every cell
                        row.cells["ig"] = estimate_views(likes, k)
                        filled += 1
                        p.log(f"{tag(run)}row {row.no}: estimated "
                              f"{row.cells['ig'].value:,} ({row.cells['ig'].note})")
                        _checkpoint(persist, run, idx, "ig", row.cells["ig"], p)
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
