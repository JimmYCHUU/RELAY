import openpyxl
import pytest

from relay.report.generator import build_report


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
    assert ws["A1"].value == "WHITE PLUS"
    assert ws["A1"].font.size == 38 and ws["A1"].font.bold
    assert ws["A1"].fill.fgColor.rgb.endswith("CCCCCC")
    assert ws["A2"].value == "No" and ws["E2"].value == "Views"
    assert ws["A2"].font.size == 14 and ws["A2"].font.bold


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
    c = ws["B3"]
    assert c.number_format == "d\\ mmmm"
    assert ws["C3"].font.name == "Arial" and ws["C3"].font.size == 14
    link_cell = ws["D3"]
    assert link_cell.font.color.rgb.endswith("0000FF")
    assert link_cell.hyperlink is not None
    assert ws["A3"].border.bottom.style == "thin"


def test_column_widths(generated):
    ws = generated
    expected = {"A": 16.7, "C": 31.3, "M": 19.6}
    for col, w in expected.items():
        assert abs(ws.column_dimensions[col].width - w) < 0.1


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
