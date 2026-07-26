"""Insights-export ingest, permalink joining, and the fill step that replaced
the reactions estimate as the source of Facebook figures.

The synthetic fixtures mirror the real export's quirks exactly: a UTF-8 BOM, a
`Title` column carrying multi-line Bengali captions, and a
"Reactions, comments and shares" column sitting right beside "Reactions".
"""
from __future__ import annotations

from datetime import datetime

import pytest

from conftest import INSIGHTS_EXPORT
from relay import config
from relay.ingest.insights import build_index, parse_insights, resolve_headers
from relay.matching.permalink import (is_share_link, normalize_fb_url,
                                      page_slug, post_token)
from relay.models import CellValue, ReportRow, RunResult
from relay.resolve.insights_fill import fill_from_insights, fit_k_table

PAGE = "https://www.facebook.com/somoysongbad360/posts/"
HEADER = ('"Post ID","Page ID","Page name",Title,"Publish time",Permalink,'
          '"Is share","Post type",Views,Reach,'
          '"Reactions, comments and shares",Reactions,Comments\n')


def _csv(tmp_path, rows: str, header: str = HEADER, name="export.csv"):
    """Write an export exactly as Meta does — UTF-8 *with* BOM."""
    path = tmp_path / name
    path.write_text(header + rows, encoding="utf-8-sig")
    return path


ROWS = (
    f'1001,900,"সময় সংবাদ","প্রথম পোস্ট","07/03/2026 10:00",{PAGE}pfbid0AAA,'
    '0,Photos,564,393,7,5,2\n'
    # a caption with embedded newlines and a comma — the real file is full of these
    f'1002,900,"সময় সংবাদ","দ্বিতীয় পোস্ট, লাইন এক\n\nলাইন দুই","07/04/2026 11:30",'
    f'{PAGE}pfbid0BBB,0,Photos,4000,2800,120,100,15\n'
    # a shared post: real Reach, almost no reactions — the case the multiplier broke on
    f'1003,900,"সময় সংবাদ","শেয়ার করা পোস্ট","07/05/2026 09:00",{PAGE}pfbid0CCC,'
    '1,Photos,4611,2892,9,5,3\n'
)


# --- permalink normalization ---

@pytest.mark.parametrize("url,expected", [
    (f"{PAGE}pfbid0AAA", "facebook.com/somoysongbad360/posts/pfbid0AAA"),
    (f"{PAGE}pfbid0AAA/", "facebook.com/somoysongbad360/posts/pfbid0AAA"),
    (f"{PAGE}pfbid0AAA?__cft__[0]=x&fbclid=y", "facebook.com/somoysongbad360/posts/pfbid0AAA"),
    ("https://m.facebook.com/somoysongbad360/posts/pfbid0AAA",
     "facebook.com/somoysongbad360/posts/pfbid0AAA"),
    ("https://www.facebook.com/somoysongbad360/videos/1614564286704364/",
     "facebook.com/somoysongbad360/videos/1614564286704364"),
    ("https://www.facebook.com/permalink.php?story_fbid=123456789&id=900",
     "facebook.com/900/posts/123456789"),
    ("https://x.com/somoytv/status/2047324234310193368", None),
    ("", None),
    (None, None),
])
def test_normalize_fb_url(url, expected):
    assert normalize_fb_url(url) == expected


def test_pfbid_case_is_preserved():
    """pfbid blobs are case-sensitive; folding them collides distinct posts."""
    a = normalize_fb_url(f"{PAGE}pfbid0AbC")
    b = normalize_fb_url(f"{PAGE}pfbid0aBc")
    assert a != b and "pfbid0AbC" in a


def test_post_token_and_page_slug():
    assert post_token(f"{PAGE}pfbid0AAA") == "pfbid0AAA"
    assert post_token("https://www.facebook.com/somoysongbad360/videos/1614564286704364/") \
        == "1614564286704364"
    assert page_slug(f"{PAGE}pfbid0AAA") == "somoysongbad360"
    assert post_token("https://www.facebook.com/share/p/18UYFuW8xo/") is None


def test_is_share_link():
    assert is_share_link("https://www.facebook.com/share/p/18UYFuW8xo/")
    assert not is_share_link(f"{PAGE}pfbid0AAA")
    assert not is_share_link(None)


# --- header resolution ---

def test_reactions_header_not_confused_with_the_combined_column():
    """'Reactions, comments and shares' sits beside 'Reactions' in the real
    export; a substring scan grabs the wrong one, so exact matches win first."""
    headers = ["Permalink", "Reactions, comments and shares", "Reactions", "Reach", "Views"]
    cols = resolve_headers(headers)
    assert cols["reactions"] == 2
    assert cols["reach"] == 3 and cols["views"] == 4


def test_headers_resolve_when_renamed():
    """Meta renames columns; substring matching keeps ingest working."""
    cols = resolve_headers(["Permalink URL", "Post impressions", "People reached"])
    assert cols["permalink"] == 0 and cols["views"] == 1 and cols["reach"] == 2


def test_qualified_views_never_outranks_views():
    cols = resolve_headers(["Permalink", "Qualified views", "Views"])
    assert cols["views"] == 2


# --- parsing ---

def test_parse_export_with_bom_and_embedded_newlines(tmp_path):
    export = parse_insights(_csv(tmp_path, ROWS))
    assert len(export.rows) == 3, "multi-line captions must not split into extra rows"
    first = export.rows[0]
    assert first.post_id == "1001" and first.views == 564 and first.reach == 393
    assert first.reactions == 5, "must read Reactions, not the combined column"
    assert first.published == datetime(2026, 7, 3, 10, 0)
    assert first.page_name == "সময় সংবাদ"
    assert "\n" in export.rows[1].title, "the caption's own newlines survive parsing"


def test_shared_posts_carry_real_reach(tmp_path):
    """The finding that removed the multiplier's whole reason to exist."""
    export = parse_insights(_csv(tmp_path, ROWS))
    shared = [r for r in export.rows if r.is_share]
    assert len(shared) == 1
    assert shared[0].reach == 2892 and shared[0].views == 4611


def test_values_stay_exact(tmp_path):
    """Export figures must never pass through parse_compact_number, which
    invents trailing digits for '45.2K'-style display strings."""
    rows = f'1,9,"P","t","07/03/2026 10:00",{PAGE}pfbid0X,0,Photos,45200,31000,1,1,0\n'
    export = parse_insights(_csv(tmp_path, rows))
    assert export.rows[0].views == 45200 and export.rows[0].reach == 31000


def test_missing_permalink_column_is_fatal(tmp_path):
    path = _csv(tmp_path, "1,2\n", header="Post ID,Views\n")
    with pytest.raises(ValueError, match="Permalink"):
        parse_insights(path)


def test_unreadable_export_becomes_an_issue_not_a_crash(tmp_path):
    """One bad export must never cost the user the whole report."""
    bad = tmp_path / "bad.csv"
    bad.write_text("Post ID,Views\n1,2\n", encoding="utf-8")
    index = build_index([bad, _csv(tmp_path, ROWS)])
    assert len(index) == 3 and index.issues
    assert "unreadable" in index.issues[0].reason


def test_index_lookup_by_url_and_token(tmp_path):
    index = build_index([_csv(tmp_path, ROWS)])
    assert index.lookup(f"{PAGE}pfbid0AAA/?fbclid=junk").post_id == "1001"
    # same post addressed through a different page slug still resolves
    assert index.lookup("https://www.facebook.com/100084045740327/posts/pfbid0BBB") \
        .post_id == "1002"
    assert index.lookup(f"{PAGE}pfbid0ZZZ") is None


# --- the fill step ---

def _run(links, cells=None, caption="", date=None):
    row = ReportRow(
        no=1, date=date, caption=caption,
        links={"fb1": links.get("fb1"), "fb2": links.get("fb2"),
               "fb3": links.get("fb3"), "x": None, "ig": None},
        cells=cells or {s: CellValue.missing() for s in ("fb1", "fb2", "fb3", "x", "ig")},
    )
    return RunResult(brand="B", month="July", rows=[row])


def test_fill_writes_exact_value_with_an_audit_trail(tmp_path):
    index = build_index([_csv(tmp_path, ROWS)])
    run = _run({"fb1": f"{PAGE}pfbid0AAA"})
    assert fill_from_insights(run, index, metric="reach") == 1
    cell = run.rows[0].cells["fb1"]
    assert cell.value == 393 and cell.provenance == "collected"
    assert "export.csv" in cell.note and "1001" in cell.note and "Reach" in cell.note


def test_metric_switch(tmp_path):
    index = build_index([_csv(tmp_path, ROWS)])
    run = _run({"fb1": f"{PAGE}pfbid0AAA"})
    fill_from_insights(run, index, metric="views")
    assert run.rows[0].cells["fb1"].value == 564


def test_fill_never_overwrites_the_supervisor_value(tmp_path):
    """The supervisor matched file stays primary — that is the user's rule."""
    index = build_index([_csv(tmp_path, ROWS)])
    cells = {s: CellValue.missing() for s in ("fb1", "fb2", "fb3", "x", "ig")}
    cells["fb1"] = CellValue(111111, "matched", 1.0)
    run = _run({"fb1": f"{PAGE}pfbid0AAA"}, cells)
    assert fill_from_insights(run, index) == 0
    assert run.rows[0].cells["fb1"].value == 111111


def test_share_links_wait_for_a_resolver(tmp_path):
    index = build_index([_csv(tmp_path, ROWS)])
    share = "https://www.facebook.com/share/p/18UYFuW8xo/"

    run = _run({"fb1": share})
    assert fill_from_insights(run, index) == 0, "no resolver -> left for the collector"

    run = _run({"fb1": share})
    filled = fill_from_insights(run, index, metric="reach",
                                resolve_share=lambda _u: f"{PAGE}pfbid0CCC")
    assert filled == 1
    assert run.rows[0].cells["fb1"].value == 2892
    assert run.rows[0].links["fb1"] == f"{PAGE}pfbid0CCC", "resolved link is kept"


def test_share_resolution_failure_is_not_fatal(tmp_path):
    index = build_index([_csv(tmp_path, ROWS)])

    def boom(_url):
        raise RuntimeError("dead link")

    run = _run({"fb1": "https://www.facebook.com/share/p/x/"})
    assert fill_from_insights(run, index, resolve_share=boom) == 0


def test_caption_fallback_is_scoped_to_page_and_date(tmp_path):
    index = build_index([_csv(tmp_path, ROWS)])
    caption = "দ্বিতীয় পোস্ট, লাইন এক\n\nলাইন দুই"

    # link is on the right page and the date is close -> matched by caption
    run = _run({"fb1": f"{PAGE}pfbid0MISSING"}, caption=caption,
               date=datetime(2026, 7, 4))
    assert fill_from_insights(run, index, metric="reach") == 1
    assert run.rows[0].cells["fb1"].value == 2800
    assert "matched by caption" in run.rows[0].cells["fb1"].note

    # same caption, but weeks away -> refused
    run = _run({"fb1": f"{PAGE}pfbid0MISSING"}, caption=caption,
               date=datetime(2026, 8, 20))
    assert fill_from_insights(run, index) == 0

    # same caption on a different page -> refused
    run = _run({"fb1": "https://www.facebook.com/somoynews.tv/posts/pfbid0MISSING"},
               caption=caption, date=datetime(2026, 7, 4))
    assert fill_from_insights(run, index) == 0


def test_short_captions_never_fuzzy_match(tmp_path):
    index = build_index([_csv(tmp_path, ROWS)])
    run = _run({"fb1": f"{PAGE}pfbid0MISSING"}, caption="ok", date=datetime(2026, 7, 4))
    assert fill_from_insights(run, index) == 0


# --- fitting k from real data ---

def test_fit_k_table_tracks_the_real_curve(tmp_path):
    rows = "".join(
        f'{i},9,"P","t","07/03/2026 10:00",{PAGE}pfbid0N{i},0,Photos,'
        f'{reactions * 400},{reactions * 300},1,{reactions},0\n'
        for i, reactions in enumerate([2] * 20 + [700] * 20)
    )
    table = fit_k_table(build_index([_csv(tmp_path, rows)]), metric="reach")
    assert table[(1, 4)] == pytest.approx(300, abs=1)
    assert table[(500, 10**9)] == pytest.approx(300, abs=1)
    # buckets without enough samples are omitted, so callers fall back
    assert (50, 99) not in table


def test_fit_k_table_ignores_zero_reaction_posts(tmp_path):
    rows = "".join(
        f'{i},9,"P","t","07/03/2026 10:00",{PAGE}pfbid0Z{i},0,Photos,500,400,0,0,0\n'
        for i in range(20))
    assert fit_k_table(build_index([_csv(tmp_path, rows)])) == {}


# --- against the real export, when it is present ---

@pytest.mark.skipif(not INSIGHTS_EXPORT.exists(), reason="real export not present")
def test_real_export_parses_completely():
    export = parse_insights(INSIGHTS_EXPORT)
    assert len(export.rows) == 1820 and not export.issues
    assert all(r.views is not None and r.reach is not None for r in export.rows)
    shares = [r for r in export.rows if r.is_share]
    assert shares and all(r.reach for r in shares), \
        "shared posts carry real Reach — the premise the estimate rested on is false"


@pytest.mark.skipif(not INSIGHTS_EXPORT.exists(), reason="real export not present")
def test_real_export_permalinks_are_unique_keys():
    index = build_index([INSIGHTS_EXPORT])
    assert len(index.by_url) == len(index) == 1820, "no permalink collisions"
    assert len(index.by_token) == 1820


@pytest.mark.skipif(not INSIGHTS_EXPORT.exists(), reason="real export not present")
def test_real_export_fits_k_far_above_the_flat_range():
    """The measurement that justified replacing the heuristic: the true ratio
    sits well outside 70-120 for ordinary posts, and falls as engagement rises."""
    table = fit_k_table(build_index([INSIGHTS_EXPORT]), metric="reach")
    assert table[(1, 4)] > config.K_MAX * 2
    assert table[(1, 4)] > table[(500, 10**9)]


# --- slot correction (the supervisor's Views_Match_N order is not Link 2/3 order) ---

P2 = "https://www.facebook.com/somoysongbad360/posts/"
P3 = "https://www.facebook.com/somoytvsports/posts/"

TWO_PAGES = (
    f'2001,900,"সময় সংবাদ","একই ক্যাপশন দুই পেজে প্রকাশিত হয়েছে আজ",'
    f'"07/03/2026 10:00",{P2}pfbid0S1,0,Photos,6778,4775,9,5,1\n'
    f'2002,901,"Somoy Sports","একই ক্যাপশন দুই পেজে প্রকাশিত হয়েছে আজ",'
    f'"07/03/2026 10:05",{P3}pfbid0S2,0,Photos,9562,6350,9,7,1\n'
)
CAPTION = "একই ক্যাপশন দুই পেজে প্রকাশিত হয়েছে আজ"


def _two_slot_run(v2, v3):
    """A row whose FB2/FB3 both carry a supervisor-matched value."""
    from datetime import datetime
    cells = {s: CellValue.missing() for s in ("fb1", "fb2", "fb3", "x", "ig")}
    cells["fb2"] = CellValue(v2, "matched", 1.0)
    cells["fb3"] = CellValue(v3, "matched", 1.0)
    run = _run({"fb2": f"{P2}pfbid0SHEET2", "fb3": f"{P3}pfbid0SHEET3"},
               cells, caption=CAPTION, date=datetime(2026, 7, 3))
    return run


def test_swapped_slots_are_corrected(tmp_path):
    """Measured on a real month: a sizeable share of filled FB cells carried a
    different page's number, because Views_Match_1 is not always the subpage."""
    from relay.resolve.insights_fill import reassign_subpage_slots
    index = build_index([_csv(tmp_path, TWO_PAGES)])

    run = _two_slot_run(9562, 6778)          # supervisor order is backwards
    assert reassign_subpage_slots(run, index, metric="views") == 2
    assert run.rows[0].cells["fb2"].value == 6778   # somoysongbad360
    assert run.rows[0].cells["fb3"].value == 9562   # somoytvsports
    assert "slot corrected from FB3" in run.rows[0].cells["fb2"].note


def test_correct_order_is_left_alone(tmp_path):
    from relay.resolve.insights_fill import reassign_subpage_slots
    index = build_index([_csv(tmp_path, TWO_PAGES)])
    run = _two_slot_run(6778, 9562)
    assert reassign_subpage_slots(run, index, metric="views") == 0
    assert run.rows[0].cells["fb2"].note == ""


def test_reassignment_never_invents_or_loses_a_number(tmp_path):
    """It permutes the supervisor's own values; the row total cannot move."""
    from relay.resolve.insights_fill import reassign_subpage_slots
    index = build_index([_csv(tmp_path, TWO_PAGES)])
    run = _two_slot_run(9562, 6778)
    before = sorted(c.value for c in run.rows[0].cells.values() if c.value)
    reassign_subpage_slots(run, index, metric="views")
    after = sorted(c.value for c in run.rows[0].cells.values() if c.value)
    assert before == after


def test_reassignment_needs_two_identifiable_posts(tmp_path):
    """With only one slot identifiable there is nothing to arbitrate."""
    from relay.resolve.insights_fill import reassign_subpage_slots
    one = TWO_PAGES.split("\n")[0] + "\n"
    index = build_index([_csv(tmp_path, one)])
    run = _two_slot_run(9562, 6778)
    assert reassign_subpage_slots(run, index, metric="views") == 0


def test_reassignment_only_touches_supervisor_values(tmp_path):
    """A collected or manually entered value is already authoritative."""
    from relay.resolve.insights_fill import reassign_subpage_slots
    index = build_index([_csv(tmp_path, TWO_PAGES)])
    run = _two_slot_run(9562, 6778)
    run.rows[0].cells["fb3"] = CellValue(6778, "manual", 1.0, "typed in")
    assert reassign_subpage_slots(run, index, metric="views") == 0
