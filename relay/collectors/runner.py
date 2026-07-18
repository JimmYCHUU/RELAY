"""Collector orchestration: fill missing cells in a RunResult (opt-in)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from .. import config
from ..models import RunResult
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


def collect_x(result: RunResult, pacer: Pacer | None = None,
              progress: ProgressCb = None, limit: int | None = None) -> int:
    """Fill X impression cells from public status pages — logged-out browser,
    no credentials ever (C-3). Returns cells filled."""
    from .browser import anonymous_page
    from .xpublic import collect_x_views

    pacer = pacer or Pacer(min_delay=config.X_PACE_MIN_S, max_delay=config.X_PACE_MAX_S)
    p = progress or Progress()
    targets = [r for r in result.rows
               if r.links.get("x") and r.cells["x"].value is None]
    if limit is not None:
        targets = targets[:limit]
    p.total = len(targets)
    if not targets:
        p.state, p.message = "finished", "no X cells to fill"
        return 0

    if pacer.dry_run:
        for row in targets:
            pacer.before_visit(row.links["x"])
            p.done += 1
        p.state, p.message = "finished", f"dry-run: would visit {p.total} pages"
        return 0

    filled = 0
    try:
        with anonymous_page() as page:
            for row in targets:
                if p.stop_requested:
                    break
                url = row.links["x"]
                p.current = url
                cell = collect_x_views(page, url, pacer)
                p.done += 1
                if cell.value is not None:
                    row.cells["x"] = cell
                    filled += 1
                    p.filled = filled
                    p.log(f"row {row.no}: {cell.value:,} views")
                else:
                    p.log(f"row {row.no}: {cell.note}")
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


def collect_facebook(result: RunResult, k: float, pacer: Pacer | None = None,
                     headed: bool = False, progress: ProgressCb = None,
                     limit: int | None = None) -> int:
    """Fill missing FB cells via the user's Meta Business Suite session;
    shared posts fall back to reactions × k estimation automatically."""
    from .browser import persistent_page
    from .mbs import collect_fb_post, resolve_share_link

    pacer = pacer or Pacer()
    p = progress or Progress()
    targets = [
        (row, slot)
        for row in result.rows
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
        for row, slot in targets:
            pacer.before_visit(row.links[slot])
            p.done += 1
        p.state, p.message = "finished", f"dry-run: would visit {p.total} posts"
        return 0

    filled = 0
    try:
        with persistent_page("meta", headed=headed) as page:
            for row, slot in targets:
                if p.stop_requested:
                    break
                url = row.links[slot]
                p.current = url
                try:
                    if "/share/" in url:
                        url = resolve_share_link(page, url, pacer)
                    cell, reactions = collect_fb_post(page, url, pacer)
                    if cell.value is not None:
                        row.cells[slot] = cell
                        filled += 1
                        p.log(f"row {row.no} {slot}: {cell.value:,} views")
                    elif reactions:
                        row.cells[slot] = estimate_views(reactions, k)
                        filled += 1
                        p.log(f"row {row.no} {slot}: estimated "
                              f"{row.cells[slot].value:,} (reactions {reactions:,} × {k:g})")
                    else:
                        p.log(f"row {row.no} {slot}: {cell.note}")
                except (BudgetExceeded, ChallengeDetected):
                    raise
                except Exception as exc:
                    p.log(f"row {row.no} {slot}: failed ({type(exc).__name__})")
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


def meta_profile_exists() -> bool:
    from pathlib import Path
    prof = Path(config.PROFILE_DIR) / "meta"
    return (prof / ".relay-login-complete").exists()
