"""Reactions-based view estimation for unrecoverable Facebook cells (SRS FR-13).

k is randomized per cell within [K_MIN, K_MAX] unless the user pins one, so a
batch of estimates never shares one tell-tale multiplier; and every estimate is
nudged onto an odd last digit (1/3/7/9 — never 0 or 5) so it reads like an
organic count, not reactions × constant.
"""
from __future__ import annotations

import random

from .. import config
from ..models import CellValue


def _organic(value: int, rng: random.Random) -> int:
    """Round numbers betray estimates — end on an odd digit, never 0 or 5."""
    return max(1, value - value % 10 + rng.choice((1, 3, 7, 9)))


def estimate_views(
    reactions: int,
    k: float | None = None,
    rng: random.Random | None = None,
) -> CellValue:
    if reactions < 0:
        raise ValueError("reactions must be >= 0")
    rng = rng or random.Random()
    if k is None:
        k = round(rng.uniform(config.K_MIN, config.K_MAX), 1)
    elif not (config.K_MIN <= k <= config.K_MAX):
        raise ValueError(f"k must be within [{config.K_MIN}, {config.K_MAX}]")
    return CellValue(
        value=_organic(round(reactions * k), rng),
        provenance="estimated",
        confidence=0.5,
        note=f"reactions={reactions}, k={k:g}",
    )


def apply_estimate(
    cell: CellValue,
    reactions: int,
    k: float | None = None,
    rng: random.Random | None = None,
) -> CellValue:
    """Estimate only into cells that have no matched value (SRS FR-13/H-3)."""
    if cell.provenance == "matched" and cell.value is not None:
        raise ValueError("refusing to overwrite a matched value with an estimate")
    return estimate_views(reactions, k, rng)
