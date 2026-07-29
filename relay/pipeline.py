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
from .models import RowIssue, RunResult
from .report.palette import accent_from_campaign
from .resolve.insights_fill import (fill_from_insights,
                                    fill_instagram_from_insights,
                                    note_unaccounted, uncovered_pages)
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
    result = RunResult(brand=brand, month=sheet, rows=rows, issues=issues,
                       accent=accent_from_campaign(campaign_path, sheet))

    # One index over both exports: they are the same shape with different words
    # for the same columns (see config.INSIGHTS_HEADERS), and each fill step keys
    # on the identifier its own platform actually carries.
    result.insights = build_index(list(insights_paths or []) + list(ig_insights_paths or []))
    issues.extend(result.insights.issues)
    if len(result.insights):
        fill_from_insights(result, result.insights)
        fill_instagram_from_insights(result, result.insights)
        # Whatever is still empty is now waiting on a post visit, not on a file
        # the user has yet to supply — say so on the cell.
        note_unaccounted(result, result.insights)
        # And say it once at the run level for a page nothing can rescue: no
        # post id resolves against a page that was never exported.
        for slug, n in sorted(uncovered_pages(result, result.insights).items(),
                              key=lambda kv: -kv[1]):
            issues.append(RowIssue(
                "insights exports", 0,
                f"{n} link{'s' if n > 1 else ''} "
                f"{'point' if n > 1 else 'points'} at {slug}, which none of the "
                "supplied exports cover — export that page to fill them"))

    return result
