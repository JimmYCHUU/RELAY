import openpyxl
import pytest

from relay.report.generator import (ACCENT_FALLBACK, build_report,
                                    detect_brand_accent, derive_palette)


@pytest.fixture()
def generated(april_result, tmp_path):
    out = tmp_path / "out.xlsx"
    build_report(april_result, out)
    wb = openpyxl.load_workbook(out)
    yield wb["April"]
    wb.close()


def test_banner_and_header(generated):
    ws = generated
    assert "A1:M1" in {str(r) for r in ws.merged_cells.ranges}
    assert ws["A1"].value.startswith("BRAND A")
    assert ws["A1"].font.size == 38 and ws["A1"].font.bold
    # no campaign sheet given -> the theme's fallback accent
    assert ws["A1"].fill.fgColor.rgb.endswith(derive_palette(ACCENT_FALLBACK)["acc"])
    assert ws["A2"].value == "No" and ws["E2"].value == "Views"
    assert ws["A2"].font.size == 12 and ws["A2"].font.bold


def test_footer_formulas(generated):
    ws = generated
    n = 25
    sum_row, total_row, avg_row = n + 3, n + 4, n + 5
    assert ws.cell(row=sum_row, column=1).value == "Sum"
    assert ws.cell(row=sum_row, column=5).value == f"=SUM(E3:E{n + 2})"
    assert ws.cell(row=sum_row, column=13).value == f"=SUM(M3:M{n + 2})"
    assert ws.cell(row=total_row, column=5).value == f"=SUM(E{sum_row}:M{sum_row})"
    assert ws.cell(row=avg_row, column=5).value == f"=E{total_row}/{n}"
    assert ws.cell(row=avg_row, column=5).number_format == "0"


def test_footer_merges(generated):
    ws = generated
    merges = {str(r) for r in ws.merged_cells.ranges}
    n = 25
    assert f"A{n + 3}:D{n + 3}" in merges
    assert f"A{n + 4}:D{n + 4}" in merges and f"E{n + 4}:M{n + 4}" in merges
    assert f"A{n + 5}:D{n + 5}" in merges and f"E{n + 5}:M{n + 5}" in merges


def test_data_row_styles(generated):
    ws = generated
    assert ws["B3"].number_format == "d\\ mmm"
    assert ws["C3"].font.name == "Arial" and ws["C3"].font.size == 11
    link_cell = ws["D3"]
    assert link_cell.font.color.rgb.endswith("1155CC")
    assert link_cell.hyperlink is not None
    assert ws["A3"].border.bottom.style == "thin"
    assert ws["E3"].number_format == "#,##0"


def test_modern_theme_polish(generated):
    ws = generated
    assert ws.freeze_panes == "A3"
    assert ws.sheet_view.showGridLines is False
    # alternating banding: row 4 is banded, row 3 is not
    assert ws["A4"].fill.fill_type == "solid"
    assert ws["A3"].fill.fill_type != "solid"
    # nothing beyond column M reaches the sponsor
    assert ws.max_column <= 13
    # rows are tall enough for wrapped captions
    assert ws.row_dimensions[3].height >= 70


def test_column_widths(generated):
    ws = generated
    expected = {"A": 16.7, "C": 31.3, "M": 19.6}
    for col, w in expected.items():
        assert abs(ws.column_dimensions[col].width - w) < 0.1


def _colored_campaign(path, fill_hex):
    wb = openpyxl.Workbook()
    ws = wb.active
    from openpyxl.styles import PatternFill
    for col in range(1, 8):
        ws.cell(row=1, column=col, value="x").fill = \
            PatternFill("solid", fgColor=fill_hex)
    ws.cell(row=2, column=1, value="y").fill = PatternFill("solid", fgColor="FFCCCCCC")
    wb.save(path)
    return path


def test_accent_detection(tmp_path):
    colored = _colored_campaign(tmp_path / "brand.xlsx", "FFC0392B")
    assert detect_brand_accent(colored) == "C0392B"
    # gray-only sheet -> nothing detected
    gray = _colored_campaign(tmp_path / "gray.xlsx", "FFCCCCCC")
    assert detect_brand_accent(gray) is None
    assert detect_brand_accent(tmp_path / "missing.xlsx") is None


def test_accent_detection_on_real_campaign():
    from tests.conftest import CAMPAIGN
    # Brand A campaign sheets are gray + link-blue only -> fallback applies
    assert detect_brand_accent(CAMPAIGN) is None


def test_report_uses_detected_brand_color(april_result, tmp_path):
    colored = _colored_campaign(tmp_path / "brand.xlsx", "FFC0392B")
    out = tmp_path / "branded.xlsx"
    build_report(april_result, out, campaign_path=colored)
    wb = openpyxl.load_workbook(out)
    ws = wb["April"]
    assert ws["A1"].fill.fgColor.rgb.endswith("C0392B")
    wb.close()


def test_missing_note_comment(april_result, tmp_path):
    """A linked slot whose extraction failed must say why in a cell comment —
    a silently blank cell is indistinguishable from a slot with no link."""
    from relay.models import CellValue

    result = april_result
    original = result.rows[0].cells["fb1"]
    try:
        result.rows[0].cells["fb1"] = CellValue.missing("auth-walled or removed post")
        out = tmp_path / "miss.xlsx"
        build_report(result, out)
        wb = openpyxl.load_workbook(out)
        c = wb["April"]["E3"].comment
        assert c is not None and "not collected" in c.text and "auth-walled" in c.text
        wb.close()
        # strip mode removes these too
        out2 = tmp_path / "miss2.xlsx"
        build_report(result, out2, estimate_comments=False)
        wb2 = openpyxl.load_workbook(out2)
        assert wb2["April"]["E3"].comment is None
        wb2.close()
    finally:
        result.rows[0].cells["fb1"] = original  # fixture is session-scoped


def test_estimate_comment(april_result, tmp_path):
    from relay.resolve.heuristic import estimate_views

    result = april_result
    original = result.rows[0].cells["fb1"]
    try:
        # inject an estimate into row 1 fb1 (the shared post)
        result.rows[0].cells["fb1"] = estimate_views(812)
        out = tmp_path / "est.xlsx"
        build_report(result, out)
        wb = openpyxl.load_workbook(out)
        ws = wb["April"]
        assert ws["E3"].comment is not None and "reactions=812" in ws["E3"].comment.text
        wb.close()
        # strip mode
        out2 = tmp_path / "est2.xlsx"
        build_report(result, out2, estimate_comments=False)
        wb2 = openpyxl.load_workbook(out2)
        assert wb2["April"]["E3"].comment is None
        wb2.close()
    finally:
        result.rows[0].cells["fb1"] = original  # fixture is session-scoped


def test_insights_source_comment_is_traceable(april_result, tmp_path):
    """An exact export figure must name its file and post id in the workbook —
    the export is the only part of the report the sponsor can verify against."""
    from relay.models import CellValue

    result = april_result
    original = result.rows[0].cells["fb1"]
    try:
        result.rows[0].cells["fb1"] = CellValue(
            2892, "collected", 1.0,
            "insights export Jul-01-2026.csv · post 1003 · Reach")
        out = tmp_path / "src.xlsx"
        build_report(result, out)
        wb = openpyxl.load_workbook(out)
        text = wb["April"]["E3"].comment.text
        assert "post 1003" in text and "Jul-01-2026.csv" in text and "Reach" in text
        wb.close()
        # the sponsor-facing copy strips every RELAY annotation
        out2 = tmp_path / "src2.xlsx"
        build_report(result, out2, estimate_comments=False)
        wb2 = openpyxl.load_workbook(out2)
        assert wb2["April"]["E3"].comment is None
        wb2.close()
    finally:
        result.rows[0].cells["fb1"] = original
