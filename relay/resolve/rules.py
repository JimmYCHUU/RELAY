"""Turn a campaign row into a report row of empty, explained cells.

Every FB/IG figure now comes from Meta's own export (`resolve.insights_fill`) or
from a collector visit, and X from its own collector. So this step no longer
decides any value — it lays out the slots and says, for each one, what RELAY is
still waiting on. Those notes are what a reader sees when a cell comes back
blank, so they name the step that would have filled it rather than a failure.
"""
from __future__ import annotations

from ..models import CampaignRow, CellValue, ReportRow


def build_row(row: CampaignRow) -> ReportRow:
    links = {
        "fb1": row.fb_links[0],
        "fb2": row.fb_links[1],
        "fb3": row.fb_links[2],
        "x": row.x_link,
        "ig": row.ig_link,
    }
    cells: dict[str, CellValue] = {s: CellValue.missing() for s in links}

    for slot in ("fb1", "fb2", "fb3"):
        if links[slot]:
            cells[slot] = CellValue.missing("awaiting the insights export")
    if links["ig"]:
        cells["ig"] = CellValue.missing("awaiting the Instagram export")
    if links["x"]:
        # X publishes no export; its figures only ever come from the public page.
        cells["x"] = CellValue.missing("awaiting X collector")

    return ReportRow(
        no=row.no or 0, date=row.date, caption=row.caption, links=links, cells=cells
    )
