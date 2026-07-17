"""Column-mapping rules, as confirmed by the analyst (SRS FR-9..FR-12).

FB1 (Somoy News TV main)   = mainpage Views_Match_1
FB2 (Somoy Shongbad)       = subpage  Views_Match_1
FB3 (category subpage)     = max(subpage Views_Match_2..N) — extras are scraper
                             snapshot garbage; discards are logged in the note.
IG                         = insta    Views_Match_1
X                          = collectors only; never fabricated here.

Subpage values fill only FB slots that exist in the campaign row, in order:
a row with Link 1 + Link 3 (no Link 2) puts subpage VM1 on the Link 3 slot.
"""
from __future__ import annotations

from ..models import CampaignRow, CellValue, Match, ReportRow


def _matched_cell(value: int | None, match: Match, note: str = "") -> CellValue:
    if value is None:
        return CellValue.missing(note or f"match tier={match.tier}, no value")
    return CellValue(value, "matched", match.confidence, note)


def build_row(
    row: CampaignRow,
    main: Match | None,
    sub: Match | None,
    insta: Match | None,
) -> ReportRow:
    links = {
        "fb1": row.fb_links[0],
        "fb2": row.fb_links[1],
        "fb3": row.fb_links[2],
        "x": row.x_link,
        "ig": row.ig_link,
    }
    cells: dict[str, CellValue] = {s: CellValue.missing() for s in links}

    # FB1 — mainpage
    if links["fb1"]:
        if main and main.matched:
            vals = main.matched.nonempty
            note = ""
            if len(set(vals)) > 1:
                note = f"multiple mainpage values {vals}, used first"
            cells["fb1"] = _matched_cell(
                main.matched.values[0] if main.matched.values else None, main, note
            )
            if row.is_shared and cells["fb1"].value is None:
                cells["fb1"].note = "shared post (share/p) — needs heuristic/collector"
        elif row.is_shared:
            cells["fb1"] = CellValue.missing("shared post (share/p) — needs heuristic/collector")
        else:
            cells["fb1"] = CellValue.missing("no mainpage match")

    # FB2/FB3 — subpage values onto existing slots, in order
    sub_slots = [s for s in ("fb2", "fb3") if links[s]]
    if sub_slots:
        if sub and sub.matched and sub.matched.values:
            vals = sub.matched.values
            first = vals[0]
            rest = [v for v in vals[1:] if v is not None]
            if len(sub_slots) == 1:
                # single subpage-family link: candidates are VM1 + rest, take VM1
                # (the one post that exists), extras logged
                note = f"extra values discarded: {rest}" if rest else ""
                cells[sub_slots[0]] = _matched_cell(first, sub, note)
            else:
                cells[sub_slots[0]] = _matched_cell(first, sub)  # Somoy Shongbad

                if rest:
                    top = max(rest)
                    dropped = sorted(v for v in rest if v != top)
                    note = f"snapshot extras discarded: {dropped}" if dropped else ""
                    cells[sub_slots[1]] = _matched_cell(top, sub, note)
                else:
                    cells[sub_slots[1]] = CellValue.missing("subpage file had a single value")
        else:
            for s in sub_slots:
                cells[s] = CellValue.missing("no subpage match")
        # A share/p link cannot be reliably caption-matched; when a value landed
        # on one, keep it (the supervisor file does sometimes match shares) but
        # mark it for review — the analyst has been known to reassign these
        # (April row 7: subpage value moved to FB1, shared FB3 estimated).
        for s in sub_slots:
            cell = cells[s]
            if cell.value is not None and "/share/" in (links[s] or ""):
                cell.confidence = min(cell.confidence, 0.7)
                cell.note = (cell.note + "; " if cell.note else "") + \
                    "shared-post slot — verify assignment"

    # IG
    if links["ig"]:
        if insta and insta.matched and insta.matched.values:
            cells["ig"] = _matched_cell(insta.matched.values[0], insta)
        else:
            cells["ig"] = CellValue.missing("no instagram match")

    # X — collector-only (SRS: current values are fabricated; we never fabricate)
    if links["x"]:
        cells["x"] = CellValue.missing("awaiting X collector")

    return ReportRow(
        no=row.no or 0, date=row.date, caption=row.caption, links=links, cells=cells
    )
