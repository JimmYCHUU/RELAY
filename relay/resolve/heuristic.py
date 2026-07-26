"""Reactions-based view estimation — the last resort (SRS FR-13).

This runs only when neither the supervisor matched file nor Meta's own insights
export can account for a cell. That ordering matters, because the multiplier is
a poor estimator and now says so honestly: measured against a month of real
export data, `views = reactions x k` with k in [70,120] landed close for well
under a tenth of posts, and the true ratio falls steeply as engagement rises —
several hundred x on posts with a handful of reactions, tens of x on the
busiest ones.

So when the export is available, k is *fitted from the user's own data* per
reaction bucket (`insights_fill.fit_k_table`) instead of guessed. The flat
[K_MIN, K_MAX] range survives only as the fallback when there is nothing to fit
against.

k is randomized within its bucket so a batch never shares one tell-tale
multiplier, and every estimate is nudged onto an odd last digit (1/3/7/9 —
never 0 or 5) so it reads like an organic count rather than reactions x
constant.
"""
from __future__ import annotations

import random

from .. import config
from ..models import CellValue

# Spread applied around a fitted bucket median, so estimates in the same bucket
# don't all land on the identical multiplier.
_FIT_JITTER = 0.15


def _organic(value: int, rng: random.Random) -> int:
    """Round numbers betray estimates — end on an odd digit, never 0 or 5."""
    return max(1, value - value % 10 + rng.choice((1, 3, 7, 9)))


def _fitted_k(reactions: int, k_table: dict[tuple[int, int], float] | None,
              rng: random.Random) -> tuple[float, str] | None:
    """The multiplier for this reaction count, from real export data."""
    if not k_table:
        return None
    for (lo, hi), median in k_table.items():
        if lo <= reactions <= hi:
            k = round(median * rng.uniform(1 - _FIT_JITTER, 1 + _FIT_JITTER), 1)
            return k, f"fitted {lo}-{hi if hi < 10**9 else '+'}"
    return None


def estimate_views(
    reactions: int,
    k: float | None = None,
    rng: random.Random | None = None,
    k_table: dict[tuple[int, int], float] | None = None,
) -> CellValue:
    """Estimate a view count from a reaction count.

    Returns a `missing` cell for zero reactions: the multiplier has nothing to
    work with, and writing 0 into a sponsor report would be worse than leaving
    the gap visible. Posts with no reactions at all are a small but real slice
    of any month, and they still collect hundreds of views.
    """
    if reactions < 0:
        raise ValueError("reactions must be >= 0")
    rng = rng or random.Random()

    if reactions == 0:
        return CellValue.missing(
            "no reactions — cannot estimate; needs the insights export or manual entry")

    if k is None:
        fit = _fitted_k(reactions, k_table, rng)
        if fit:
            k, source = fit
        else:
            k = round(rng.uniform(config.K_MIN, config.K_MAX), 1)
            source = "unfitted"
    else:
        if not (config.K_MIN <= k <= config.K_MAX):
            raise ValueError(f"k must be within [{config.K_MIN}, {config.K_MAX}]")
        source = "pinned"

    return CellValue(
        value=_organic(round(reactions * k), rng),
        provenance="estimated",
        confidence=0.5,
        note=f"reactions={reactions}, k={k:g} ({source})",
    )


def apply_estimate(
    cell: CellValue,
    reactions: int,
    k: float | None = None,
    rng: random.Random | None = None,
    k_table: dict[tuple[int, int], float] | None = None,
) -> CellValue:
    """Estimate only into cells that have no real value (SRS FR-13/H-3)."""
    if cell.provenance in ("matched", "collected") and cell.value is not None:
        raise ValueError(f"refusing to overwrite a {cell.provenance} value with an estimate")
    return estimate_views(reactions, k, rng, k_table)
