"""Pipeline orchestrator — single entry point for CLI and web (SDD 2)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .ingest.campaign import parse_campaign
from .ingest.supervisor import parse_matched
from .matching.engine import match_rows
from .models import Match, RunResult
from .resolve.rules import build_row


def run_pipeline(
    campaign_path: str | Path,
    sheet: str,
    brand: str,
    mainpage_path: Optional[str | Path] = None,
    subpage_path: Optional[str | Path] = None,
    insta_path: Optional[str | Path] = None,
) -> RunResult:
    campaign, issues = parse_campaign(campaign_path, sheet)

    def matches_for(path: Optional[str | Path]) -> list[Match] | None:
        if not path:
            return None
        mf = parse_matched(path)
        issues.extend(mf.issues)
        return match_rows(campaign, mf.for_brand(brand))

    main_m = matches_for(mainpage_path)
    sub_m = matches_for(subpage_path)
    insta_m = matches_for(insta_path)

    rows = []
    tiers: dict[int, dict[str, str]] = {}
    for i, crow in enumerate(campaign):
        main = main_m[i] if main_m else None
        sub = sub_m[i] if sub_m else None
        insta = insta_m[i] if insta_m else None
        rows.append(build_row(crow, main, sub, insta))
        tiers[crow.no or i + 1] = {
            "mainpage": main.tier if main else "n/a",
            "subpage": sub.tier if sub else "n/a",
            "instagram": insta.tier if insta else "n/a",
        }

    return RunResult(brand=brand, month=sheet, rows=rows, issues=issues, match_tiers=tiers)
