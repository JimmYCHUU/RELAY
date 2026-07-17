"""Collector orchestration: fill missing cells in a RunResult (opt-in)."""
from __future__ import annotations

import logging

from ..models import RunResult
from ..resolve.heuristic import estimate_views
from .base import BudgetExceeded, ChallengeDetected, Pacer
from .xpublic import collect_x_views

log = logging.getLogger("relay.collectors")


def collect_x(result: RunResult, pacer: Pacer | None = None, limit: int | None = None) -> int:
    """Fill X impression cells from public pages. Returns cells filled."""
    pacer = pacer or Pacer()
    filled = 0
    for row in result.rows:
        if limit is not None and pacer.visits >= limit:
            break
        link = row.links.get("x")
        if not link or row.cells["x"].value is not None:
            continue
        try:
            cell = collect_x_views(link, pacer)
        except BudgetExceeded:
            log.warning("X collection stopped: session budget reached")
            break
        if cell.value is not None:
            row.cells["x"] = cell
            filled += 1
    return filled


def collect_facebook(result: RunResult, k: float, pacer: Pacer | None = None,
                     headed: bool = False, limit: int | None = None) -> int:
    """Fill missing FB cells via Meta Business Suite session; estimate shared
    posts from reactions when direct views are unavailable."""
    from .browser import persistent_page
    from .mbs import collect_fb_post, resolve_share_link

    pacer = pacer or Pacer()
    filled = 0
    targets = [
        (row, slot)
        for row in result.rows
        for slot in ("fb1", "fb2", "fb3")
        if row.links.get(slot) and row.cells[slot].value is None
    ]
    if not targets:
        return 0
    if pacer.dry_run:
        for row, slot in targets:
            pacer.before_visit(row.links[slot])
        return 0

    with persistent_page("meta", headed=headed) as page:
        for row, slot in targets:
            if limit is not None and pacer.visits >= limit:
                break
            url = row.links[slot]
            try:
                if "/share/" in url:
                    url = resolve_share_link(page, url, pacer)
                cell, reactions = collect_fb_post(page, url, pacer)
                if cell.value is not None:
                    row.cells[slot] = cell
                    filled += 1
                elif reactions:
                    row.cells[slot] = estimate_views(reactions, k)
                    filled += 1
            except BudgetExceeded:
                log.warning("FB collection stopped: session budget reached")
                break
            except ChallengeDetected as exc:
                log.error("%s", exc)
                break
            except Exception as exc:
                log.warning("fb collect failed for %s: %s", url, exc)
    return filled
