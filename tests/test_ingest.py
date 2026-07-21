import pytest

from relay.ingest.campaign import list_sheets, parse_campaign
from relay.ingest.supervisor import parse_matched
from tests.conftest import ALL_MAIN_APRIL, ALL_MAIN_PENDING, ALL_SUB_PENDING, CAMPAIGN, WP_INSTA, WP_MAIN, WP_SUB


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
    rows, issues = parse_campaign(CAMPAIGN, "White Plus Election")
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


def test_mainpage_layout():
    mf = parse_matched(WP_MAIN)
    assert len(mf.rows) == 25
    assert mf.rows[0].values == []            # empty match (shared post)
    assert mf.rows[1].values[0] == 161332


def test_subpage_layout():
    mf = parse_matched(WP_SUB)
    row3 = mf.rows[2]
    assert row3.values == [38139, 4891, 8705]


def test_insta_layout():
    mf = parse_matched(WP_INSTA)
    assert mf.rows[0].values[0] == 1764
    assert mf.rows[2].values[0] == 193173


def test_multibrand_sections_april():
    mf = parse_matched(ALL_MAIN_APRIL)
    assert "bkash" in mf.sections
    assert len(mf.sections["bkash"]) > 0
    # case-insensitive access through for_brand
    assert mf.for_brand("BKASH") == mf.sections["bkash"]


def test_multibrand_sections_pending():
    for path in (ALL_MAIN_PENDING, ALL_SUB_PENDING):
        mf = parse_matched(path)
        assert mf.sections, f"no sections detected in {path.name}"
        # separator rows must not appear among caption rows
        for rows in mf.sections.values():
            for r in rows:
                assert len(r.title) > 0


def test_wide_files_parse():
    mf = parse_matched(ALL_SUB_PENDING)
    widths = [len(r.values) for r in mf.rows]
    assert max(widths) >= 12


def test_cocola_layout(tmp_path):
    """Cocola-style sheet: category-count row under the header, per-row category
    column after Instagram, duplicate captions, and a blank Date cell."""
    from datetime import datetime

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "June"
    ws.append(["Cocola", None, None, None, None, None, None, None, 104, "*Total 104 Social Cards"])
    ws.append(["No", "Date", "Content's name", "Content's Link", "Content's Link 2",
               "Content's Link 3", "X, Link 4", "Instagram"])
    # company-side bookkeeping row — how many creatives per category; not data
    ws.append([None, None, "Jusika", 35, "Marshmallow ", 35, "Cup Noodles", 34])
    d = datetime(2026, 6, 12)
    ws.append([1, d, "Match Schedule 12 June", "https://www.facebook.com/a", None, None,
               "https://x.com/somoytv/status/1", "https://www.instagram.com/p/1", "Jusika"])
    ws.append([2, None, "Match Schedule 12 June", "https://www.facebook.com/b", None, None,
               "https://x.com/somoytv/status/2", "https://www.instagram.com/p/2", "Cup Noodles"])
    path = tmp_path / "cocola.xlsx"
    wb.save(path)

    rows, issues = parse_campaign(path, "June")
    assert len(rows) == 2
    assert any("category-count row ignored" in i.reason for i in issues)
    # duplicate captions are legitimate (same creative, different category)
    assert rows[0].caption == rows[1].caption == "Match Schedule 12 June"
    # blank Date inherits the neighbouring row's date
    assert rows[1].date == d
    assert any("empty Date filled" in i.reason for i in issues)
