"""Reactions-based view estimation for unrecoverable Facebook cells (SRS FR-13)."""
from __future__ import annotations

from .. import config
from ..models import CellValue


def estimate_views(reactions: int, k: float = config.K_DEFAULT) -> CellValue:
    if reactions < 0:
        raise ValueError("reactions must be >= 0")
    if not (config.K_MIN <= k <= config.K_MAX):
        raise ValueError(f"k must be within [{config.K_MIN}, {config.K_MAX}]")
    return CellValue(
        value=round(reactions * k),
        provenance="estimated",
        confidence=0.5,
        note=f"reactions={reactions}, k={k:g}",
    )


def apply_estimate(cell: CellValue, reactions: int, k: float = config.K_DEFAULT) -> CellValue:
    """Estimate only into cells that have no matched value (SRS FR-13/H-3)."""
    if cell.provenance == "matched" and cell.value is not None:
        raise ValueError("refusing to overwrite a matched value with an estimate")
    return estimate_views(reactions, k)
