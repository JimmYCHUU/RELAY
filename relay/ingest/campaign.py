"""Campaign workbook parser (SRS FR-1).

Layout (verified on White Plus Feb/Mar/Apr/May/FifaWC/Election tabs):
row 1: free-form note cells; row 2: header
`No | Date | Content's name | Content's Link [1] | Content's Link 2 |
 Content's Link 3 | X, Link 4 | Instagram`; data until trailing empty region.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import openpyxl

from ..models import CampaignRow, RowIssue

_EMPTY_RUN_STOP = 15  # consecutive empty rows = end of data (sheets have ~900 styled blanks)


def list_sheets(path: str | Path) -> list[str]:
    wb = openpyxl.load_workbook(path, read_only=True)
    names = wb.sheetnames
    wb.close()
    return names


def _find_header(ws) -> int | None:
    for row in ws.iter_rows(min_row=1, max_row=10):
        a = row[0].value
        joined = " ".join(str(c.value) for c in row[:8] if c.value)
        if isinstance(a, str) and a.strip().lower() == "no" and "content" in joined.lower():
            return row[0].row
    return None


def _cell_str(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def parse_campaign(path: str | Path, sheet: str) -> tuple[list[CampaignRow], list[RowIssue]]:
    wb = openpyxl.load_workbook(path, data_only=True)
    try:
        if sheet not in wb.sheetnames:
            raise ValueError(
                f"Sheet '{sheet}' not found in {Path(path).name}; available: {wb.sheetnames}"
            )
        ws = wb[sheet]
        header = _find_header(ws)
        if header is None:
            raise ValueError(f"Header row not found in sheet '{sheet}' of {Path(path).name}")

        rows: list[CampaignRow] = []
        issues: list[RowIssue] = []
        fname = Path(path).name
        empty_run = 0

        for row in ws.iter_rows(min_row=header + 1, max_col=8):
            r = row[0].row
            no, date, caption = row[0].value, row[1].value, _cell_str(row[2].value)
            links = [_cell_str(row[i].value) for i in (3, 4, 5)]
            x_link, ig_link = _cell_str(row[6].value), _cell_str(row[7].value)

            if not caption and not any(links) and not x_link and not ig_link:
                empty_run += 1
                if empty_run >= _EMPTY_RUN_STOP:
                    break
                continue
            empty_run = 0

            if not caption:
                issues.append(RowIssue(fname, r, "links present but caption empty — row skipped"))
                continue

            if isinstance(no, float):
                no = int(no)
            if not isinstance(no, int):
                if no is not None:
                    issues.append(RowIssue(fname, r, f"non-numeric No '{no}' ignored"))
                no = None
            if not isinstance(date, datetime):
                if date is not None:
                    issues.append(RowIssue(fname, r, f"unreadable Date '{date}'"))
                date = None

            rows.append(CampaignRow(no, date, caption, links, x_link, ig_link, source_row=r))

        for i, cr in enumerate(rows):
            if cr.date is None:
                issues.append(RowIssue(fname, cr.source_row, "missing Date"))
            if cr.no is None:
                cr.no = (rows[i - 1].no + 1) if i and rows[i - 1].no is not None else i + 1
        return rows, issues
    finally:
        wb.close()
