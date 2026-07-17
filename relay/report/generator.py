"""Template-exact sponsor report writer (SRS FR-20..FR-22, SDD 5.6).

Every style constant below was measured programmatically from the hand-made
`White Plus FB Photocard (April).xlsx` ground-truth workbook.
"""
from __future__ import annotations

from pathlib import Path

import openpyxl
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from ..models import ReportRow, RunResult

GRAY = PatternFill("solid", fgColor="CCCCCC")
THIN = Side(style="thin")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)

F_BANNER = Font(name="Arial", size=38, bold=True)
F_HEADER = Font(name="Arial", size=14, bold=True)
F_DATA = Font(name="Arial", size=14, bold=True)
F_LINK = Font(name="Arial", size=14, bold=False, color="0000FF", underline="single")
F_FOOT = Font(name="Arial", size=18, bold=True)

COL_WIDTHS = {
    "A": 16.7, "B": 21.7, "C": 31.3, "D": 32.1, "E": 21.0, "F": 27.0, "G": 27.6,
    "H": 19.6, "I": 25.4, "J": 27.7, "K": 24.6, "L": 25.0, "M": 19.6,
}
HEADERS = [
    "No", "Date", "Content's name", "Content's Link 1", "Views",
    "Content's Link 2", "Views", "Content's Link 3", "Views",
    "X, Link 4", "Impressions", "Instagram", "Views",
]
# (link column, value column) per slot, template order
SLOT_COLS = {"fb1": (4, 5), "fb2": (6, 7), "fb3": (8, 9), "x": (10, 11), "ig": (12, 13)}
VALUE_COLS = (5, 7, 9, 11, 13)
DATE_FMT = "d\\ mmmm"


def _write_cell(ws, row, col, value, font, fmt=None):
    c = ws.cell(row=row, column=col, value=value)
    c.font = font
    c.alignment = CENTER
    c.border = BORDER
    if fmt:
        c.number_format = fmt
    return c


def build_report(
    result: RunResult,
    out_path: str | Path,
    sheet_name: str | None = None,
    estimate_comments: bool = True,
) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name or result.month

    for col, width in COL_WIDTHS.items():
        ws.column_dimensions[col].width = width

    # banner
    ws.merge_cells("A1:M1")
    for col in range(1, 14):
        _write_cell(ws, 1, col, result.brand.upper() if col == 1 else None, F_BANNER)
        ws.cell(row=1, column=col).fill = GRAY

    # header
    for col, text in enumerate(HEADERS, start=1):
        c = _write_cell(ws, 2, col, text, F_HEADER)
        c.fill = GRAY

    # data
    first_data = 3
    for i, r in enumerate(result.rows):
        excel_row = first_data + i
        _write_cell(ws, excel_row, 1, r.no, F_DATA)
        _write_cell(ws, excel_row, 2, r.date, F_DATA, fmt=DATE_FMT if r.date else None)
        _write_cell(ws, excel_row, 3, r.caption, F_DATA)
        for slot, (lc, vc) in SLOT_COLS.items():
            link = r.link(slot)
            cell = r.cells[slot]
            link_cell = _write_cell(ws, excel_row, lc, link, F_LINK if link else F_DATA)
            if link:
                link_cell.hyperlink = link
            vcell = _write_cell(ws, excel_row, vc, cell.value, F_DATA)
            if estimate_comments and cell.provenance == "estimated":
                vcell.comment = Comment(f"RELAY estimate: {cell.note}", "RELAY")

    n = len(result.rows)
    last_data = first_data + n - 1
    sum_row, total_row, avg_row = last_data + 1, last_data + 2, last_data + 3

    # footer: Sum
    ws.merge_cells(start_row=sum_row, start_column=1, end_row=sum_row, end_column=4)
    for col in range(1, 14):
        _write_cell(ws, sum_row, col, "Sum" if col == 1 else None, F_HEADER)
    for col in VALUE_COLS:
        cl = get_column_letter(col)
        _write_cell(ws, sum_row, col, f"=SUM({cl}{first_data}:{cl}{last_data})", F_HEADER)

    # footer: Total views
    ws.merge_cells(start_row=total_row, start_column=1, end_row=total_row, end_column=4)
    ws.merge_cells(start_row=total_row, start_column=5, end_row=total_row, end_column=13)
    for col in range(1, 14):
        _write_cell(ws, total_row, col, "Total views" if col == 1 else None, F_FOOT)
        ws.cell(row=total_row, column=col).fill = GRAY
    _write_cell(ws, total_row, 5, f"=SUM(E{sum_row}:M{sum_row})", F_FOOT)

    # footer: Average
    ws.merge_cells(start_row=avg_row, start_column=1, end_row=avg_row, end_column=4)
    ws.merge_cells(start_row=avg_row, start_column=5, end_row=avg_row, end_column=13)
    for col in range(1, 14):
        _write_cell(ws, avg_row, col, "Average views per content" if col == 1 else None, F_FOOT)
        ws.cell(row=avg_row, column=col).fill = GRAY
    _write_cell(ws, avg_row, 5, f"=E{total_row}/{n}", F_FOOT, fmt="0")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    wb.close()
    return out_path
