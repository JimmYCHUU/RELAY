"""Sponsor report writer — "modern theme" (SRS FR-20..FR-22, SDD 5.6).

Layout (columns, footer formulas, merges) still mirrors the hand-made
the client's own hand-made report as ground truth; the visual layer is the
modern style the analyst approved from `style-samples/style-3-modern-theme.xlsx`.

The report's chrome wears the sponsor's own colour, read off the campaign
sheet's brand-name and header rows (see `palette.py`): the banner, the header
row, the rule beneath it, and the Sum / Total / Average rows. The data rows
stay neutral — the zebra stripe, captions and links are what a reader is
actually reading, and tinting those buys nothing.

Only those two header rows are consulted. An earlier attempt took the sheet's
strongest colour from anywhere in the tab, which on the June sheets picked up a
highlighted cell's yellow (FFFF00) and produced an olive masthead. A sheet with
no brand colour at all — SMC Plus's June tracker fills those rows plain grey —
falls back to the approved teal, unchanged.

Nothing in the delivered file explains how RELAY works: no cell comments, no
provenance, no notes. The dashboard is where a figure is audited; this workbook
is what goes to the sponsor.
"""
from __future__ import annotations

from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from ..models import RunResult
from .palette import DEFAULT, derive

# style-3's exact palette, still the fallback for an unbranded sheet. The tint
# and band are the sample's own hand-picked values, not a formula's output —
# mixing the accent toward white lands a few points off on both.
ACCENT = "0C8F7C"
TINT = "E7F5F2"
BAND = "F5F8F7"
INK = "FF1F2937"
LINK_BLUE = "FF1155CC"

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
DATE_FMT = "d\\ mmm"
NUM_FMT = "#,##0"


# ── writer ────────────────────────────────────────────────────────────────────
def _write_cell(ws, row, col, value, font, fmt=None, fill=None, border=None,
                align=None):
    c = ws.cell(row=row, column=col, value=value)
    c.font = font
    c.alignment = align or Alignment(horizontal="center", vertical="center",
                                     wrap_text=True)
    if border is not None:
        c.border = border
    if fmt:
        c.number_format = fmt
    if fill is not None:
        c.fill = fill
    return c


def build_report(
    result: RunResult,
    out_path: str | Path,
    sheet_name: str | None = None,
) -> Path:
    # The sponsor's colour dresses the chrome; the data rows below stay neutral.
    pal = derive(result.accent) if result.accent else DEFAULT

    fill_acc = PatternFill("solid", fgColor="FF" + pal.accent)
    fill_tint = PatternFill("solid", fgColor="FF" + pal.tint)
    fill_band = PatternFill("solid", fgColor="FF" + BAND)   # data zebra: neutral
    lgray = Side(style="thin", color="FFD5DDDA")
    border = Border(left=lgray, right=lgray, top=lgray, bottom=lgray)
    header_border = Border(left=lgray, right=lgray, top=lgray,
                           bottom=Side(style="medium", color="FF" + pal.rule))
    no_border = Border()
    # Banner and footer ink flip to dark on a light brand colour — white 38pt on
    # TK Super Board's gold or SMC Plus's green is unreadable.
    f_banner = Font(name="Arial", size=38, bold=True, color="FF" + pal.on_accent)
    f_header = Font(name="Arial", size=12, bold=True, color=INK)
    f_data = Font(name="Arial", size=12, bold=True, color="FF111111")
    f_caption = Font(name="Arial", size=11, color=INK)
    f_link = Font(name="Arial", size=9, color=LINK_BLUE, underline="single")
    f_sum = Font(name="Arial", size=12, bold=True, color="FF" + pal.accent_text)
    f_foot = Font(name="Arial", size=16, bold=True, color="FF" + pal.on_accent)
    left = Alignment(horizontal="left", vertical="center", wrap_text=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name or result.month
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "A3"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    for col, width in COL_WIDTHS.items():
        ws.column_dimensions[col].width = width

    # banner: BRAND — Month Year
    year = next((r.date.year for r in result.rows if r.date), None)
    title = f"{result.brand.upper()} — {result.month}" + (f" {year}" if year else "")
    ws.merge_cells("A1:M1")
    for col in range(1, 14):
        _write_cell(ws, 1, col, title if col == 1 else None, f_banner,
                    fill=fill_acc, border=no_border)
    ws.row_dimensions[1].height = 52

    # header
    for col, text in enumerate(HEADERS, start=1):
        _write_cell(ws, 2, col, text, f_header, fill=fill_tint,
                    border=header_border)
    ws.row_dimensions[2].height = 34

    # data
    first_data = 3
    for i, r in enumerate(result.rows):
        excel_row = first_data + i
        lines = max(1, -(-len(r.caption or "") // 38))
        ws.row_dimensions[excel_row].height = min(130, max(70, lines * 13 + 10))
        band = fill_band if i % 2 else None
        # Renumber sequentially: the source No is hand-filled and may repeat or
        # be blank; the delivered report must carry a clean, unique No.
        _write_cell(ws, excel_row, 1, i + 1, f_data, fill=band, border=border)
        _write_cell(ws, excel_row, 2, r.date, f_data,
                    fmt=DATE_FMT if r.date else None, fill=band, border=border)
        _write_cell(ws, excel_row, 3, r.caption, f_caption, fill=band,
                    border=border, align=left)
        for slot, (lc, vc) in SLOT_COLS.items():
            link = r.link(slot)
            cell = r.cells[slot]
            link_cell = _write_cell(ws, excel_row, lc, link,
                                    f_link if link else f_data,
                                    fill=band, border=border)
            if link:
                link_cell.hyperlink = link
            _write_cell(ws, excel_row, vc, cell.value, f_data,
                        fmt=NUM_FMT, fill=band, border=border)

    n = len(result.rows)
    last_data = first_data + n - 1
    sum_row, total_row, avg_row = last_data + 1, last_data + 2, last_data + 3

    # footer: Sum
    ws.merge_cells(start_row=sum_row, start_column=1, end_row=sum_row, end_column=4)
    for col in range(1, 14):
        _write_cell(ws, sum_row, col, "Sum" if col == 1 else None, f_sum,
                    fill=fill_tint, border=border)
    for col in VALUE_COLS:
        cl = get_column_letter(col)
        _write_cell(ws, sum_row, col, f"=SUM({cl}{first_data}:{cl}{last_data})",
                    f_sum, fmt=NUM_FMT, fill=fill_tint, border=border)

    # footer: Total views
    ws.merge_cells(start_row=total_row, start_column=1, end_row=total_row, end_column=4)
    ws.merge_cells(start_row=total_row, start_column=5, end_row=total_row, end_column=13)
    for col in range(1, 14):
        _write_cell(ws, total_row, col, "Total views" if col == 1 else None,
                    f_foot, fill=fill_acc, border=no_border)
    _write_cell(ws, total_row, 5, f"=SUM(E{sum_row}:M{sum_row})", f_foot,
                fmt=NUM_FMT, fill=fill_acc, border=no_border)

    # footer: Average
    ws.merge_cells(start_row=avg_row, start_column=1, end_row=avg_row, end_column=4)
    ws.merge_cells(start_row=avg_row, start_column=5, end_row=avg_row, end_column=13)
    for col in range(1, 14):
        _write_cell(ws, avg_row, col,
                    "Average views per content" if col == 1 else None,
                    f_foot, fill=fill_acc, border=no_border)
    _write_cell(ws, avg_row, 5, f"=E{total_row}/{n}", f_foot, fmt="0",
                fill=fill_acc, border=no_border)
    for rr in (sum_row, total_row, avg_row):
        ws.row_dimensions[rr].height = 28

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    wb.close()
    return out_path
