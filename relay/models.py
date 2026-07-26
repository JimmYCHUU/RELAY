"""Core data models shared across the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

Provenance = Literal["matched", "estimated", "manual", "collected", "missing"]
MatchTier = Literal["exact", "prefix", "fuzzy", "review", "none"]

# Report value slots, in template column order.
SLOTS = ("fb1", "fb2", "fb3", "x", "ig")


@dataclass
class RowIssue:
    file: str
    row: int
    reason: str


@dataclass
class CampaignRow:
    no: Optional[int]
    date: Optional[datetime]
    caption: str
    fb_links: list[Optional[str]]          # [link1, link2, link3]
    x_link: Optional[str]
    ig_link: Optional[str]
    source_row: int = 0

    @property
    def is_shared(self) -> bool:
        l1 = self.fb_links[0] or ""
        return "/share/" in l1


@dataclass
class MatchedRow:
    title: str
    values: list[Optional[int]]            # Views_Match_1..N, in order
    source_row: int = 0

    @property
    def nonempty(self) -> list[int]:
        return [v for v in self.values if v is not None]


@dataclass
class MatchedFile:
    path: str
    rows: list[MatchedRow]                                 # captions only
    sections: dict[str, list[MatchedRow]] = field(default_factory=dict)
    issues: list[RowIssue] = field(default_factory=list)

    def for_brand(self, brand: str | None) -> list[MatchedRow]:
        """Rows for a brand section, else all caption rows."""
        if brand:
            hit = self.sections.get(brand.strip().lower())
            if hit:
                return hit
        return self.rows


@dataclass
class InsightsRow:
    """One post as Meta's own Business Suite content export reports it.

    These figures are exact integers straight from Meta — never routed through
    `collectors.base.parse_compact_number`, which invents trailing digits for
    compact "45.2K" display strings.
    """
    post_id: str
    permalink: str
    page_id: str = ""
    page_name: str = ""
    title: str = ""                     # the post's own caption, for the fuzzy fallback
    published: Optional[datetime] = None
    views: Optional[int] = None
    reach: Optional[int] = None
    reactions: Optional[int] = None
    post_type: str = ""
    is_share: bool = False
    source_file: str = ""
    source_row: int = 0

    def metric(self, name: str) -> Optional[int]:
        """The configured headline figure ('reach' or 'views')."""
        return self.reach if name == "reach" else self.views


@dataclass
class Match:
    matched: Optional[MatchedRow]
    tier: MatchTier
    confidence: float


@dataclass
class CellValue:
    value: Optional[int]
    provenance: Provenance
    confidence: float = 1.0
    note: str = ""

    @classmethod
    def missing(cls, note: str = "") -> "CellValue":
        return cls(None, "missing", 0.0, note)


@dataclass
class ReportRow:
    no: int
    date: Optional[datetime]
    caption: str
    links: dict[str, Optional[str]]        # slot -> url
    cells: dict[str, CellValue]            # slot -> value

    def link(self, slot: str) -> Optional[str]:
        return self.links.get(slot)


@dataclass
class RunResult:
    brand: str
    month: str
    rows: list[ReportRow]
    issues: list[RowIssue] = field(default_factory=list)
    match_tiers: dict[int, dict[str, str]] = field(default_factory=dict)
    # ingest.insights.InsightsIndex, attached by run_pipeline. Left untyped to
    # keep models.py free of an import cycle (insights.py imports InsightsRow
    # from here). Collectors reuse it to look up shares once resolved.
    insights: object | None = None

    def coverage(self) -> dict[str, float]:
        """Fraction of linked slots that have a value, per slot."""
        out: dict[str, float] = {}
        for slot in SLOTS:
            linked = [r for r in self.rows if r.links.get(slot)]
            if not linked:
                out[slot] = 1.0
                continue
            filled = [r for r in linked if r.cells[slot].value is not None]
            out[slot] = len(filled) / len(linked)
        return out
