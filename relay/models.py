"""Core data models shared across the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

# "matched" is gone with the supervisor files, "estimated" with the multiplier:
# a figure is now Meta's own, read off a post, typed in, or absent.
Provenance = Literal["collected", "manual", "missing"]

# Report value slots, in template column order.
SLOTS = ("fb1", "fb2", "fb3", "x", "ig")

# What a cell says once its link has been struck off by hand. The post is gone
# from the platform — deleted by whoever ran the page — but the campaign sheet
# still lists it, so nothing can ever fill this cell and it should stop being
# counted as work outstanding.
LINK_REMOVED_NOTE = ("link removed by hand — the post is no longer on the "
                     "platform, so this slot is left blank in the report")


@dataclass
class RowIssue:
    file: str
    row: int
    reason: str
    # The cell this note is about, when it is about one. `slot` names it and
    # `row_idx` is the row's position in the run — together they are what lets
    # the dashboard drop a note once that cell has been filled. A note kept past
    # its own cell reads as a live problem and is simply no longer true: a cell
    # is tried by the export's caption join, then the sibling recovery, then a
    # post visit, and each pass that gives up has its own reason.
    slot: str = ""
    row_idx: Optional[int] = None
    # How to read `row`. An ingest note points at a line of the workbook; a
    # per-cell note points at the No the review table shows. The two are rarely
    # the same number, and one list showing both as "row N" invites the reader
    # to look in the wrong place.
    where: str = ""

    def __post_init__(self) -> None:
        # row 0 is the "no particular row" marker a whole-file note carries —
        # rendering it as "row 0" sends the reader looking for a line that does
        # not exist, so it stays unlocated.
        if not self.where and self.row:
            self.where = f"row {self.row}"


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
    # Meta's combined "Reactions, comments and shares" plus `clicks`, since that
    # column counts none of them (see config.INSIGHTS_HEADERS). Reconstructed
    # from the parts only when the export omits the combined column.
    engagement: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    # The export's all-clicks figure ("Total clicks"), carried in its own right
    # as well as folded into `engagement`.
    clicks: Optional[int] = None
    post_type: str = ""
    is_share: bool = False
    source_file: str = ""
    source_row: int = 0

    def metric(self, name: str) -> Optional[int]:
        """The configured headline figure ('reach' or 'views')."""
        return self.reach if name == "reach" else self.views


@dataclass
class CellValue:
    value: Optional[int]
    provenance: Provenance
    confidence: float = 1.0
    note: str = ""
    # Companion figures for the same post, carried alongside the headline value
    # so the report can print Views / Reach / Engagement / Clicks side by side.
    # Only ever set from a Meta export (`resolve.insights_fill`) or typed in by
    # hand — a collector reads a post's view count off the page and has none of
    # the three to offer. So these stay None for every cell that came from a
    # collector, and the report leaves them blank rather than inventing a figure.
    reach: Optional[int] = None
    engagement: Optional[int] = None
    clicks: Optional[int] = None

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
    # The campaign sheet's own text, kept when `resolve.insights_fill.
    # refresh_caption` replaced `caption` with the one the post actually
    # carries. Empty for every row the sheet still describes correctly.
    original_caption: str = ""
    # Which tab of the campaign workbook this row came from. Set only when
    # several tabs are merged into one report (`report.merge.merge_runs`), where
    # it becomes the report's "Source tab" column — a single-tab report has
    # nothing to disambiguate and carries no such column.
    source_sheet: str = ""

    def link(self, slot: str) -> Optional[str]:
        return self.links.get(slot)


@dataclass
class RunResult:
    brand: str
    month: str
    rows: list[ReportRow]
    issues: list[RowIssue] = field(default_factory=list)
    # The brand's colour, read off the campaign sheet's brand-name and header
    # rows (report.palette). None when that sheet was never branded, which
    # leaves the report on its default teal. Carried per run so each brand in a
    # multi-brand cycle keeps its own.
    accent: str | None = None
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
