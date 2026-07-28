"""Pipeline orchestrator — single entry point for CLI and web (SDD 2).

Everything a figure can come from is one of Meta's own exports. The campaign
sheet supplies the rows, their links and their dates; the Facebook and Instagram
content exports supply the numbers. Nothing is inferred from a multiplier, and
nothing arrives from a hand-made file any more — a cell RELAY cannot account for
stays empty until a collector visits the post or someone types a value in.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .ingest.campaign import parse_campaign
from .ingest.insights import build_index
from .models import RunResult
from .resolve.insights_fill import (fill_from_insights,
                                    fill_instagram_from_insights)
from .resolve.rules import build_row


def run_pipeline(
    campaign_path: str | Path,
    sheet: str,
    brand: str,
    insights_paths: Optional[list[str | Path]] = None,
    ig_insights_paths: Optional[list[str | Path]] = None,
) -> RunResult:
    campaign, issues = parse_campaign(campaign_path, sheet)
    rows = [build_row(crow) for crow in campaign]
    result = RunResult(brand=brand, month=sheet, rows=rows, issues=issues)

    # One index over both exports: they are the same shape with different words
    # for the same columns (see config.INSIGHTS_HEADERS), and each fill step keys
    # on the identifier its own platform actually carries.
    result.insights = build_index(list(insights_paths or []) + list(ig_insights_paths or []))
    issues.extend(result.insights.issues)
    if len(result.insights):
        fill_from_insights(result, result.insights)
        fill_instagram_from_insights(result, result.insights)

    return result
