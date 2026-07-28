import pytest

from relay.ingest.campaign import list_sheets, parse_campaign
from tests.conftest import CAMPAIGN, local_value


def test_april_campaign_rows(april_campaign):
    rows, issues = april_campaign
    assert len(rows) == 25
    r1 = rows[0]
    assert "/share/" in r1.fb_links[0]
    assert r1.fb_links[1] and r1.fb_links[2] is None
    assert r1.is_shared


def test_missing_no_and_date_tolerated(april_campaign):
    rows, issues = april_campaign
    # rows without explicit No get sequential fill
    assert [r.no for r in rows] == list(range(1, 26))
    # April row No 2 has no Date in the source sheet — auto-filled from a
    # neighbouring row (posts are chronological) and flagged
    assert all(r.date is not None for r in rows)
    assert rows[1].date == rows[0].date
    assert any("empty Date filled" in i.reason for i in issues)


def test_feb_14col_variant():
    rows, issues = parse_campaign(CAMPAIGN, "Feb")
    assert len(rows) >= 10
    assert rows[0].caption.startswith("সরকারি চাকরিতে")


def test_election_missing_dates_filled():
    rows, issues = parse_campaign(CAMPAIGN, local_value("ELECTION_SHEET", "Election"))
    assert all(r.date is not None for r in rows)
    assert any("empty Date filled" in i.reason for i in issues)
    assert all(r.no is not None for r in rows)


def test_unknown_sheet_error():
    with pytest.raises(ValueError, match="available"):
        parse_campaign(CAMPAIGN, "Nope")


def test_no_phantom_rows(april_campaign):
    rows, _ = april_campaign
    assert all(r.caption for r in rows)


def test_list_sheets():
    assert "April" in list_sheets(CAMPAIGN)








def test_category_count_layout(tmp_path):
    """Brand C-style sheet: category-count row under the header, per-row category
    column after Instagram, duplicate captions, and a blank Date cell."""
    from datetime import datetime

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "June"
    ws.append(["Brand C", None, None, None, None, None, None, None, 104, "*Total 104 Social Cards"])
    ws.append(["No", "Date", "Content's name", "Content's Link", "Content's Link 2",
               "Content's Link 3", "X, Link 4", "Instagram"])
    # company-side bookkeeping row — how many creatives per category; not data
    ws.append([None, None, "Category A", 35, "Category B ", 35, "Category C", 34])
    d = datetime(2026, 6, 12)
    ws.append([1, d, "Match Schedule 12 June", "https://www.facebook.com/a", None, None,
               "https://x.com/somoytv/status/1", "https://www.instagram.com/p/1", "Category A"])
    ws.append([2, None, "Match Schedule 12 June", "https://www.facebook.com/b", None, None,
               "https://x.com/somoytv/status/2", "https://www.instagram.com/p/2", "Category C"])
    path = tmp_path / "categories.xlsx"
    wb.save(path)

    rows, issues = parse_campaign(path, "June")
    assert len(rows) == 2
    assert any("category-count row ignored" in i.reason for i in issues)
    # duplicate captions are legitimate (same creative, different category)
    assert rows[0].caption == rows[1].caption == "Match Schedule 12 June"
    # blank Date inherits the neighbouring row's date
    assert rows[1].date == d
    assert any("empty Date filled" in i.reason for i in issues)
