"""Rows with links but no caption are kept, not skipped — the link is the
tracking key; caption-matching is skipped and collectors/manual entry fill
the views (and collectors recover the caption from the post itself)."""
from datetime import datetime

import openpyxl

from relay.ingest.campaign import parse_campaign
from relay.matching.engine import match_rows
from relay.models import MatchedRow

HEADER = ["No", "Date", "Content's name", "Content's Link [1]",
          "Content's Link 2", "Content's Link 3", "X, Link 4", "Instagram"]
FB = "https://www.facebook.com/somoynews.tv/posts/pfbid0demo"


def _sheet(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "April"
    ws.append(["campaign note"])
    ws.append(HEADER)
    ws.append([1, datetime(2026, 4, 2), "White Plus demo caption", FB,
               None, None, None, None])
    ws.append([2, datetime(2026, 4, 5), None, FB, None, None, None, None])
    path = tmp_path / "campaign.xlsx"
    wb.save(path)
    return path


def test_linked_row_without_caption_is_kept(tmp_path):
    rows, issues = parse_campaign(_sheet(tmp_path), "April")
    assert len(rows) == 2
    assert rows[1].caption == ""
    assert rows[1].fb_links[0] == FB
    kept = [i for i in issues if "row kept" in i.reason]
    assert kept and kept[0].row == 4
    assert not any("skipped" in i.reason for i in issues)


def test_footer_summary_rows_are_not_content(tmp_path):
    """Sum/Total/Average footer rows put numbers in the link columns — they
    must vanish silently, not survive as caption-less 'linked' rows."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "April"
    ws.append(["campaign note"])
    ws.append(HEADER)
    ws.append([1, datetime(2026, 4, 2), "real caption", FB, None, None, None, None])
    ws.append(["Sum", None, None, None, 4937626, None, 57000, None])
    ws.append(["Total views", None, None, None, 5614672, None, None, None])
    path = tmp_path / "campaign.xlsx"
    wb.save(path)

    rows, issues = parse_campaign(path, "April")
    assert len(rows) == 1
    assert not any("row kept" in i.reason for i in issues)


def test_captionless_row_never_caption_matches(tmp_path):
    rows, _ = parse_campaign(_sheet(tmp_path), "April")
    matched = [MatchedRow("White Plus demo caption", [123]),
               MatchedRow("", [999])]  # a blank supervisor line must not pair up
    result = match_rows(rows, matched)
    assert result[0].tier == "exact"
    assert result[1].tier == "none"
    assert result[1].matched is None
