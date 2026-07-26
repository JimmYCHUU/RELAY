"""Sponsor report writer — "modern theme" (SRS FR-20..FR-22, SDD 5.6).

Layout (columns, footer formulas, merges) still mirrors the hand-made
`White Plus FB Photocard (April).xlsx` ground truth; the visual layer is the
modern style the analyst approved from `style-samples/style-3-modern-theme.xlsx`.
The accent color follows the brand: it is detected from the campaign sheet's
fills, with the theme's teal as the fallback for colorless sheets.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import openpyxl
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from ..models import RunResult

ACCENT_FALLBACK = "0C8F7C"          # the approved sample's teal
INK = "FF1F2937"
LINK_BLUE = "FF1155CC"
# colors that appear in campaign sheets but are not brand identity
_NON_BRAND = {"0000FF", "1155CC", "FF0000"}

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


# ── brand accent ──────────────────────────────────────────────────────────────
def _rgb(hexs: str) -> tuple[int, ...]:
    return tuple(int(hexs[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb) -> str:
    return "".join(f"{max(0, min(255, round(v))):02X}" for v in rgb)


def _luminance(rgb) -> float:
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _mix(rgb, other, t):
    return tuple(a + (b - a) * t for a, b in zip(rgb, other))


def detect_brand_accent(campaign_path: str | Path, max_rows: int = 200) -> str | None:
    """Dominant saturated fill color across the campaign workbook's sheets —
    brand sheets usually carry the brand's tone. Grays/whites and the standard
    link-blue / warning-red fonts' hexes are ignored; None when nothing
    qualifies (e.g. White Plus sheets, which are pure gray)."""
    try:
        wb = openpyxl.load_workbook(campaign_path, read_only=False)
    except Exception:
        return None
    counts: Counter[str] = Counter()
    try:
        for ws in wb.worksheets:
            for row in ws.iter_rows(min_row=1, max_row=max_rows):
                for c in row:
                    f = c.fill
                    if not f or f.fill_type != "solid" or f.fgColor.type != "rgb":
                        continue
                    rgb = (f.fgColor.rgb or "")[-6:].upper()
                    if len(rgb) != 6 or rgb in _NON_BRAND:
                        continue
                    channels = _rgb(rgb)
                    if max(channels) - min(channels) < 30:   # gray/white/black
                        continue
                    counts[rgb] += 1
    finally:
        wb.close()
    return counts.most_common(1)[0][0] if counts else None


def derive_palette(accent_hex: str) -> dict[str, str]:
    """Accent -> masthead/tint/banding hexes; the accent is darkened until
    large white text reads on it (WCAG large-text 3:1)."""
    acc = _rgb(accent_hex)
    while _contrast(acc, (255, 255, 255)) < 3.0:
        acc = _mix(acc, (0, 0, 0), 0.12)
    return {
        "acc": _hex(acc),
        "tint": _hex(_mix(acc, (255, 255, 255), 0.90)),
        "band": _hex(_mix(acc, (255, 255, 255), 0.96)),
    }


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
    estimate_comments: bool = True,
    campaign_path: str | Path | None = None,
    accent: str | None = None,
) -> Path:
    accent = accent or (campaign_path and detect_brand_accent(campaign_path)) \
        or ACCENT_FALLBACK
    pal = derive_palette(accent)
    fill_acc = PatternFill("solid", fgColor="FF" + pal["acc"])
    fill_tint = PatternFill("solid", fgColor="FF" + pal["tint"])
    fill_band = PatternFill("solid", fgColor="FF" + pal["band"])
    lgray = Side(style="thin", color="FFD5DDDA")
    border = Border(left=lgray, right=lgray, top=lgray, bottom=lgray)
    header_border = Border(left=lgray, right=lgray, top=lgray,
                           bottom=Side(style="medium", color="FF" + pal["acc"]))
    no_border = Border()
    f_banner = Font(name="Arial", size=38, bold=True, color="FFFFFFFF")
    f_header = Font(name="Arial", size=12, bold=True, color=INK)
    f_data = Font(name="Arial", size=12, bold=True, color="FF111111")
    f_caption = Font(name="Arial", size=11, color=INK)
    f_link = Font(name="Arial", size=9, color=LINK_BLUE, underline="single")
    f_sum = Font(name="Arial", size=12, bold=True, color="FF" + pal["acc"])
    f_foot = Font(name="Arial", size=16, bold=True, color="FFFFFFFF")
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

    # banner: BRAND — Month Year on the brand accent
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
            vcell = _write_cell(ws, excel_row, vc, cell.value, f_data,
                                fmt=NUM_FMT, fill=band, border=border)
            if estimate_comments and cell.provenance == "estimated":
                vcell.comment = Comment(f"RELAY estimate: {cell.note}", "RELAY")
            elif estimate_comments and cell.provenance == "collected" \
                    and cell.note.startswith("insights export"):
                # An exact figure from Meta's own export. The note names the
                # file and post id so the sponsor can trace the number back to
                # a row in the export they were handed — the only part of the
                # report they can independently verify.
                vcell.comment = Comment(f"RELAY source: {cell.note}", "RELAY")
            elif estimate_comments and link and cell.value is None and cell.note:
                # a linked slot with no value is a failed extraction, not an
                # empty slot — say why, so blank cells aren't ambiguous
                vcell.comment = Comment(f"RELAY: not collected — {cell.note}", "RELAY")

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
