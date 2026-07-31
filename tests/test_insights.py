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
from relay.resolve.insights_fill import cell_from_insights, fill_from_insights

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


def test_photo_lightbox_links_are_parsed():
    """The desktop lightbox names its page only in `set=pb.<page-id>`."""
    pb = ("https://www.facebook.com/photo/?fbid=1547624310731465"
          "&set=pb.100064517327464.-2207520000")
    assert page_slug(pb) == "100064517327464"
    assert post_token(pb) == "1547624310731465"
    # an album says nothing about which page owns it
    album = "https://www.facebook.com/photo/?fbid=1560894569404439&set=a.626062159554356"
    assert page_slug(album) is None
    assert post_token(album) == "1560894569404439"


def test_page_slug_never_mistakes_a_post_id_for_a_page():
    """The page is always the first path segment. A URL that opens with route
    furniture names no page, and must not hand back the post id that follows —
    that would scope the caption fallback to a page that does not exist."""
    assert page_slug("https://www.facebook.com/permalink.php?story_fbid=123456789") is None
    assert page_slug("https://www.facebook.com/photo/?fbid=1560894569404439") is None


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


# --- campaign links that name no page ---
#
# Facebook's own "Copy link" buttons hand out two shapes the export never uses:
# the mobile share sheet's `/share/p/<short>/` and the desktop lightbox's
# `/photo/?fbid=…&set=…`. Neither carries the page in its path, so the caption
# fallback has nothing to scope against and these cells used to come back empty
# even when the export plainly held the post — the June bKash sheet opens with
# four such rows.

MAIN = "https://www.facebook.com/somoynews.tv/posts/"
SPORT = "https://www.facebook.com/somoytvsports/posts/"
STORY = "২০২৬ ফুটবল বিশ্বকাপ সামনে রেখে যুক্তরাষ্ট্রে পৌঁছেছে ব্রাজিল জাতীয় ফুটবল দল"
JUNE3 = datetime(2026, 6, 3)

# the same story as both pages ran it, exactly as the real export carries it
TWO_PAGE_STORY = (
    f'2001,100064517327464,"somoynews.tv","{STORY}","06/03/2026 10:00",'
    f'{MAIN}pfbid0EXPORTA,0,Photos,99818,70000,50,40,5\n'
    f'2002,61550125032197,"Somoy Sports","{STORY}","06/03/2026 10:05",'
    f'{SPORT}pfbid0EXPORTB,0,Photos,6542,5000,20,15,2\n'
)


def _sheet(rows):
    """A RunResult of several campaign rows — page inference reads the slot's
    page distribution off the whole sheet, so one row is never enough."""
    out = []
    for i, (links, caption, date) in enumerate(rows, start=1):
        out.append(ReportRow(
            no=i, date=date, caption=caption,
            links={"fb1": links.get("fb1"), "fb2": links.get("fb2"),
                   "fb3": links.get("fb3"), "x": None, "ig": None},
            cells={s: CellValue.missing() for s in ("fb1", "fb2", "fb3", "x", "ig")},
        ))
    return RunResult(brand="B", month="June", rows=out)


def _sheet_with(first_row_links, filler_fb2=SPORT):
    """`first_row_links` under three ordinary rows that establish the habit:
    Link 1 is the main page, Link 2 a subpage."""
    rows = [(first_row_links, STORY, JUNE3)]
    for i in range(3):
        rows.append(({"fb1": f"{MAIN}pfbid0F{i}", "fb2": f"{filler_fb2}pfbid0G{i}"},
                     "অন্য একটি খবর যার সঙ্গে এই গল্পের কোনো সম্পর্ক নেই", JUNE3))
    return _sheet(rows)


def test_share_link_page_is_inferred_from_the_slots_other_links(tmp_path):
    """The June bKash rows 1-4 case: both links are share links, the caption is
    in the export twice — once per page — and the slot each link sits in says
    which is which."""
    index = build_index([_csv(tmp_path, TWO_PAGE_STORY)])
    run = _sheet_with({"fb1": "https://www.facebook.com/share/p/14i5461RWUo/",
                       "fb2": "https://www.facebook.com/share/p/1Khk1YURtN/"})

    assert fill_from_insights(run, index, metric="views") == 2
    row = run.rows[0]
    assert row.cells["fb1"].value == 99818, "Link 1 is the main page"
    assert row.cells["fb2"].value == 6542, "Link 2 is the subpage"
    assert "page inferred as somoynews.tv" in row.cells["fb1"].note
    assert row.cells["fb1"].confidence <= 0.9, "never as good as a link that named its page"


def test_photo_lightbox_link_resolves_its_page_by_id(tmp_path):
    """`set=pb.<page-id>` names the page numerically; the export carries both
    that id and the vanity slug, so this one needs no guessing at all."""
    index = build_index([_csv(tmp_path, TWO_PAGE_STORY)])
    photo = ("https://www.facebook.com/photo/?fbid=1547624310731465"
             "&set=pb.100064517327464.-2207520000")
    run = _sheet_with({"fb1": photo})

    assert fill_from_insights(run, index, metric="views") == 1
    cell = run.rows[0].cells["fb1"]
    assert cell.value == 99818
    assert "matched by caption" in cell.note and "inferred" not in cell.note


def test_album_photo_link_falls_back_to_inference(tmp_path):
    """`set=a.<album-id>` names only an album, which the export knows nothing
    about — so this shape does go through the slot's page distribution."""
    index = build_index([_csv(tmp_path, TWO_PAGE_STORY)])
    run = _sheet_with({"fb1": "https://www.facebook.com/photo/?fbid=15476243&set=a.626062159554356"})

    assert fill_from_insights(run, index, metric="views") == 1
    assert run.rows[0].cells["fb1"].value == 99818
    assert "page inferred" in run.rows[0].cells["fb1"].note


def test_inference_declines_when_the_sheet_gives_no_clear_page(tmp_path):
    """Both pages ran the story and this slot points at both about equally
    often, so there is no reason to prefer one. A blank beats a coin flip."""
    index = build_index([_csv(tmp_path, TWO_PAGE_STORY)])
    rows = [({"fb2": "https://www.facebook.com/share/p/14i5461RWUo/"}, STORY, JUNE3)]
    for i in range(3):
        rows.append(({"fb2": f"{MAIN}pfbid0H{i}"}, "ভিন্ন খবর এক নম্বর যা মেলে না", JUNE3))
        rows.append(({"fb2": f"{SPORT}pfbid0I{i}"}, "ভিন্ন খবর দুই নম্বর যা মেলে না", JUNE3))
    run = _sheet(rows)

    assert fill_from_insights(run, index, metric="views") == 0
    assert run.rows[0].cells["fb2"].value is None
    assert any("no clear page" in i.reason for i in run.issues)


def test_a_pageless_link_records_why_it_stayed_empty(tmp_path):
    index = build_index([_csv(tmp_path, TWO_PAGE_STORY)])
    run = _sheet_with({"fb1": "https://www.facebook.com/share/p/14i5461RWUo/"})
    run.rows[0].caption = "সম্পূর্ণ ভিন্ন একটি খবর যা রপ্তানিতে নেই"

    assert fill_from_insights(run, index, metric="views") == 0
    assert any("no export row matches this caption" in i.reason for i in run.issues)


def test_inference_never_puts_two_slots_on_one_page(tmp_path):
    """One post per page per row: a page already accounted for by a link that
    named itself is not available to a page-less one."""
    index = build_index([_csv(tmp_path, TWO_PAGE_STORY)])
    run = _sheet_with({"fb1": f"{MAIN}pfbid0SHEETSIDE",
                       "fb2": "https://www.facebook.com/share/p/1Khk1YURtN/"})

    assert fill_from_insights(run, index, metric="views") == 2
    assert run.rows[0].cells["fb1"].value == 99818
    assert run.rows[0].cells["fb2"].value == 6542, "main page was already taken"


SONGBAD = "https://www.facebook.com/somoysongbad360/posts/"
THREE_PAGE_STORY = TWO_PAGE_STORY + (
    f'2003,100084045740327,"সময় সংবাদ","{STORY}","06/03/2026 10:07",'
    f'{SONGBAD}pfbid0EXPORTC,0,Photos,6245,4267,60,50,6\n'
)


def test_a_confident_slot_frees_the_page_its_neighbour_could_not_choose(tmp_path):
    """Ruchi June row 69. Link 2 is split near-evenly between two subpages, so
    on its own it can never clear the dominance bar — but Link 3 takes one of
    them outright, and one post per page per row leaves Link 2 only one page it
    could possibly be on. Nothing is left to be wrong about, so it fills."""
    index = build_index([_csv(tmp_path, THREE_PAGE_STORY)])
    album = "https://www.facebook.com/photo?fbid=%s&set=a.130548286423362"
    rows = [({"fb1": f"{MAIN}pfbid0SHEETSIDE",
              "fb2": album % "1043508205127361",
              "fb3": album % "122365967318004167"}, STORY, JUNE3)]
    # Link 2: 4 sports against 3 songbad — neither is 3x the other.
    # Link 3: 6 sports against 1 songbad — sports wins outright.
    habit = [("fb2", SPORT)] * 4 + [("fb2", SONGBAD)] * 3 \
        + [("fb3", SPORT)] * 6 + [("fb3", SONGBAD)] * 1
    for i, (slot, page) in enumerate(habit):
        rows.append(({"fb1": f"{MAIN}pfbid0J{i}", slot: f"{page}pfbid0K{i}"},
                     f"ভিন্ন একটি খবর যা রপ্তানিতে নেই {i}", JUNE3))
    run = _sheet(rows)

    assert fill_from_insights(run, index, metric="views") == 3
    row = run.rows[0]
    assert row.cells["fb3"].value == 6542, "Link 3 wins its page outright"
    assert row.cells["fb2"].value == 6245, "so Link 2's only remaining page is its own"
    assert "page inferred as somoysongbad360" in row.cells["fb2"].note


def test_a_shaky_slot_never_frees_a_page_for_its_neighbour(tmp_path):
    """The converse guard: when neither page-less slot clears the bar, no slot
    may claim a page on the strength of the other's guess. Both stay empty."""
    index = build_index([_csv(tmp_path, THREE_PAGE_STORY)])
    album = "https://www.facebook.com/photo?fbid=%s&set=a.130548286423362"
    rows = [({"fb1": f"{MAIN}pfbid0SHEETSIDE",
              "fb2": album % "15476243", "fb3": album % "15476244"}, STORY, JUNE3)]
    habit = [("fb2", SPORT)] * 4 + [("fb2", SONGBAD)] * 3 \
        + [("fb3", SPORT)] * 3 + [("fb3", SONGBAD)] * 2
    for i, (slot, page) in enumerate(habit):
        rows.append(({"fb1": f"{MAIN}pfbid0L{i}", slot: f"{page}pfbid0M{i}"},
                     f"ভিন্ন একটি খবর যা রপ্তানিতে নেই {i}", JUNE3))
    run = _sheet(rows)

    assert fill_from_insights(run, index, metric="views") == 1, "Link 1 only"
    assert run.rows[0].cells["fb2"].value is None
    assert run.rows[0].cells["fb3"].value is None


# --- the export's own boilerplate tail ---

BUDGET = "দাম কমতে পারে যেসব পণ্যের এবারের বাজেট প্রস্তাবে"
GOLD = ("দেশের বাজারে স্বর্ণের দাম আরেক দফা বাড়ানোর সিদ্ধান্ত নিয়েছে "
        "বাংলাদেশ জুয়েলার্স অ্যাসোসিয়েশন")

BOILERPLATE_ROWS = (
    f'3001,900,"সময় সংবাদ","{BUDGET}...\n\nবিস্তারিত কমেন্টে…\n\n#somoytv #NewsUpdate",'
    f'"06/03/2026 10:00",{PAGE}pfbid0BUDGET,0,Photos,182392,120000,90,70,9\n'
    # the same day's gold story, but it says prices were CUT where the campaign
    # sheet says RAISED — one word apart, and a different post
    f'3002,900,"সময় সংবাদ","দেশের বাজারে আরেক দফা স্বর্ণের দাম কমানোর সিদ্ধান্ত '
    f'নিয়েছে বাংলাদেশ জুয়েলার্স অ্যাসোসিয়েশন। এবার ভরিতে...\n\nবিস্তারিত কমেন্টে…\n\n#gold",'
    f'"06/03/2026 11:00",{PAGE}pfbid0GOLD,0,Photos,637905,400000,300,250,30\n'
)


def test_the_exports_call_to_action_tail_no_longer_blocks_a_match(tmp_path):
    """83% of a real month's export titles end in "বিস্তারিত কমেন্টে…" plus a
    hashtag block that no campaign sheet carries. Those extra tokens dragged
    token_set_ratio to 0.88 — under the bar — on captions that were otherwise
    word-for-word identical."""
    index = build_index([_csv(tmp_path, BOILERPLATE_ROWS)])
    run = _sheet([({"fb1": f"{PAGE}pfbid0MISSING"}, BUDGET, JUNE3)])

    assert fill_from_insights(run, index, metric="views") == 1
    assert run.rows[0].cells["fb1"].value == 182392


def test_stripping_the_tail_never_rescues_a_reversed_headline(tmp_path):
    """Stripping shortens the token set, and a short set stops noticing the one
    word that flips the meaning — বাড়ানোর (raised) against কমানোর (cut) scores
    0.93. Hence the far stricter bar for the stripped key: this must stay empty."""
    index = build_index([_csv(tmp_path, BOILERPLATE_ROWS)])
    run = _sheet([({"fb1": f"{PAGE}pfbid0MISSING"}, GOLD, JUNE3)])

    assert fill_from_insights(run, index, metric="views") == 0


def test_a_page_running_one_story_twice_is_refused_not_ranked(tmp_path):
    """Somoy re-posts a story minutes after the first attempt and both copies
    carry the same caption on the same page. Nothing in the caption separates
    them, and measured on a real April both orderings put wrong numbers in the
    report — one picked a 678-view duplicate where the live post had 6,519. So
    the caption join refuses the slot and the post-id pass settles it."""
    caption = "একই শিরোনামে দুইবার প্রকাশিত একটি খবরের প্রতিবেদন"
    rows = (
        f'4001,900,"সময় সংবাদ","{caption}","06/03/2026 10:00",{PAGE}pfbid0OLD,'
        '0,Photos,1111,900,10,8,1\n'
        f'4002,900,"সময় সংবাদ","{caption}","06/04/2026 10:00",{PAGE}pfbid0NEW,'
        '0,Photos,2222,1800,10,8,1\n'
    )
    index = build_index([_csv(tmp_path, rows)])
    run = _sheet([({"fb1": f"{PAGE}pfbid0MISSING"}, caption, datetime(2026, 6, 4))])

    assert fill_from_insights(run, index, metric="views") == 0
    assert run.rows[0].cells["fb1"].value is None
    assert any("same story twice" in i.reason for i in run.issues)


# --- one post, several exports ---
#
# Meta's export ranges overlap freely and the user downloads them as they go, so
# a real set covered Jun 8-14, Jun 11-17, Jun 15-21 and Jun 10-Jul 30 at once.
# 12,223 of 40,024 posts arrived more than once, each wearing a *different*
# pfbid permalink — and the caption join, seeing two rows, called every one of
# them a page that had run the story twice.

# The same post read on two days: the later download has accrued a few views,
# and Meta has re-minted the pfbid in the permalink.
DUP_EARLY = (f'2001,900,"সময় সংবাদ","{STORY}","06/03/2026 10:00",'
             f'{PAGE}pfbid0EARLYREAD,0,Photos,298967,195650,50,40,5\n')
DUP_LATER = (f'2001,900,"সময় সংবাদ","{STORY}","06/03/2026 10:00",'
             f'{PAGE}pfbid0LATERREAD,0,Photos,298978,195653,50,40,5\n')


def test_a_post_in_two_overlapping_exports_stays_one_post(tmp_path):
    index = build_index([_csv(tmp_path, DUP_EARLY, name="jun08-14.csv"),
                         _csv(tmp_path, DUP_LATER, name="jun11-17.csv")])

    assert len(index) == 1
    assert index.rows[0].views == 298978, "every figure is lifetime — the larger is the later"
    assert index.rows[0].reach == 195653, "reach comes from that same reading"


def test_the_superseded_reading_stops_resolving(tmp_path):
    """The stale row's permalink differs from its replacement's, so dropping it
    means deleting its key rather than overwriting one."""
    index = build_index([_csv(tmp_path, DUP_EARLY, name="a.csv"),
                         _csv(tmp_path, DUP_LATER, name="b.csv")])

    assert index.lookup(f"{PAGE}pfbid0EARLYREAD") is None
    assert index.lookup(f"{PAGE}pfbid0LATERREAD").views == 298978
    assert index.lookup_post_id("2001").views == 298978


def test_a_reading_without_views_never_displaces_one_that_has_them(tmp_path):
    blank = (f'2001,900,"সময় সংবাদ","{STORY}","06/03/2026 10:00",'
             f'{PAGE}pfbid0NOFIGURES,0,Photos,,,50,40,5\n')
    index = build_index([_csv(tmp_path, DUP_LATER, name="a.csv"),
                         _csv(tmp_path, blank, name="b.csv")])

    assert len(index) == 1
    assert index.rows[0].views == 298978


def test_a_duplicated_post_is_not_a_page_running_one_story_twice(tmp_path):
    """The cost of the duplicate: the caption join scored the post against its
    own twin, tied, and refused the cell that the export could account for."""
    index = build_index([_csv(tmp_path, DUP_EARLY, name="jun08-14.csv"),
                         _csv(tmp_path, DUP_LATER, name="jun11-17.csv")])
    run = _sheet([({"fb1": f"{PAGE}pfbid0SHEETSIDE"}, STORY, JUNE3)])

    assert fill_from_insights(run, index, metric="views") == 1
    assert run.rows[0].cells["fb1"].value == 298978
    assert not any("same story twice" in i.reason for i in run.issues)


# --- a figure has to explain itself ---
#
# A user auditing the June report could not account for a 40,144 on a shared
# post: the export's pfbid differs from the sheet's link, and that export row
# carries a blank Title, so searching their own copy by link *or* by caption
# found nothing. The figure was right — it had been joined on Meta's numeric post
# id after the collector read it off the post page — but the note said only
# "insights export <file> · post <id> · Views", which named no method and cited a
# filename carrying RELAY's internal upload prefix.

def test_note_names_the_line_of_the_file_and_how_it_was_joined(tmp_path):
    index = build_index([_csv(tmp_path, ROWS)])
    cell = cell_from_insights(index.lookup(f"{PAGE}pfbid0AAA"), "views",
                              how="matched by the sheet's own link")
    assert "export.csv row 2" in cell.note, "the exact CSV line, not just the file"
    assert "post 1001" in cell.note
    assert "matched by the sheet's own link" in cell.note
    assert "5 reactions on the export's copy" in cell.note


def test_a_blank_title_row_says_why_a_caption_search_would_fail(tmp_path):
    """10.7% of a real month's export rows carry no Title, most of them shares.
    For those, a reader searching their copy by caption finds nothing — so the
    note has to say the export never had one."""
    rows = (f'2001,900,"সময় সংবাদ","","07/03/2026 10:00",{PAGE}pfbid0SHARED,'
            '1,Photos,40144,28161,90,85,3\n')
    index = build_index([_csv(tmp_path, rows)])
    cell = cell_from_insights(index.rows[0], "views", how="identified by post id")
    assert "shared post — the export carries no caption for it" in cell.note
    assert "85 reactions on the export's copy" in cell.note


def test_the_note_cites_the_filename_the_client_was_handed(tmp_path):
    """Dashboard uploads are stored under a random prefix. A note citing
    '48bcbfb9_combine.csv' points at a name that exists nowhere but RELAY."""
    from relay.ingest.insights import display_name

    index = build_index([_csv(tmp_path, ROWS, name="48bcbfb9_combine.csv")])
    cell = cell_from_insights(index.rows[0], "views")
    assert "insights export combine.csv row" in cell.note
    assert "48bcbfb9" not in cell.note
    # an unprefixed name is left alone, and so is something merely prefix-shaped
    assert display_name("combine.csv") == "combine.csv"
    assert display_name("Jun-01-2026_Jun-07-2026_1697572464799951.csv") == \
        "Jun-01-2026_Jun-07-2026_1697572464799951.csv"


def test_every_export_fill_states_its_method(tmp_path):
    """The four join paths must be distinguishable from the cell alone — that is
    the whole point. Reading them out of the progress log is not enough: the log
    is trimmed to the last 40 lines and never persisted."""
    index = build_index([_csv(tmp_path, ROWS)])
    caption = "দ্বিতীয় পোস্ট, লাইন এক\n\nলাইন দুই"

    run = _run({"fb1": f"{PAGE}pfbid0AAA"})
    fill_from_insights(run, index, metric="views")
    assert "matched by the sheet's own link" in run.rows[0].cells["fb1"].note

    run = _run({"fb1": f"{PAGE}pfbid0MISSING"}, caption=caption,
               date=datetime(2026, 7, 4))
    fill_from_insights(run, index, metric="views")
    assert "matched by caption" in run.rows[0].cells["fb1"].note


# --- Instagram ---
#
# The mirror image of Facebook. A `pfbid` differs between a copied link and the
# export, which is why Facebook needs a browser visit to read a post id. An
# Instagram shortcode is the same string in both, so the join is exact and
# offline — and the export's own columns say "Likes" and "Account name" where
# Facebook's say "Reactions" and "Page name".

IG_HEADER = ('"Post ID","Account ID","Account username","Account name",Description,'
             '"Duration (sec)","Publish time",Permalink,"Post type","Data comment",'
             'Date,Views,Reach,Likes,Shares,Follows,Comments,Saves\n')
IG_ROWS = (
    '18098311940237254,17841405640718718,somoynews_tv,"SOMOY TV","প্রথম পোস্ট",0,'
    '"06/29/2026 15:21",https://www.instagram.com/p/DaL7buhEzbR/,"IG image",,'
    'Lifetime,87275,47106,3478,504,2,59,44\n'
    '18098311940237255,17841405640718718,somoynews_tv,"SOMOY TV","দ্বিতীয় পোস্ট",0,'
    '"06/30/2026 11:00",https://www.instagram.com/reel/DaXyz12AbCd/,"IG reel",,'
    'Lifetime,4570,3000,62,10,0,3,2\n'
)


def test_instagram_export_columns_resolve(tmp_path):
    """Its headers differ from Facebook's for the same fields; one alias table
    has to cover both without "Likes" ever displacing "Likes and reactions"."""
    export = parse_insights(_csv(tmp_path, IG_ROWS, header=IG_HEADER, name="ig.csv"))
    row = export.rows[0]
    assert row.views == 87275 and row.reach == 47106
    assert row.reactions == 3478, "Likes is the Instagram spelling of reactions"
    assert row.page_name == "SOMOY TV" and row.title == "প্রথম পোস্ট"
    assert row.post_id == "18098311940237254"


@pytest.mark.parametrize("url,code", [
    ("https://www.instagram.com/p/DaL7buhEzbR/", "DaL7buhEzbR"),
    # the app's copy-link button appends tracking the export never carries
    ("https://www.instagram.com/p/DZKgM89kyqP/?utm_source=ig_web_copy_link&i=1",
     "DZKgM89kyqP"),
    ("https://www.instagram.com/reel/DaXyz12AbCd/", "DaXyz12AbCd"),
    ("https://www.instagram.com/somoynews_tv/reel/DaXyz12AbCd/", "DaXyz12AbCd"),
    ("https://www.facebook.com/somoynews.tv/posts/pfbid0AAA", None),
    (None, None),
])
def test_ig_shortcode(url, code):
    from relay.matching.permalink import ig_shortcode
    assert ig_shortcode(url) == code


def test_instagram_cells_fill_from_the_export_without_a_browser(tmp_path):
    from relay.resolve.insights_fill import fill_instagram_from_insights

    index = build_index([_csv(tmp_path, IG_ROWS, header=IG_HEADER, name="ig.csv")])
    run = _sheet([({}, "যেকোনো একটি ক্যাপশন যা কোথাও মেলে না", datetime(2026, 6, 29))])
    run.rows[0].links["ig"] = \
        "https://www.instagram.com/p/DaL7buhEzbR/?utm_source=ig_web_copy_link"

    assert fill_instagram_from_insights(run, index, metric="views") == 1
    cell = run.rows[0].cells["ig"]
    assert cell.value == 87275 and cell.provenance == "collected"
    assert "matched by the post's shortcode" in cell.note
    assert "ig.csv row 2" in cell.note


def test_an_instagram_link_absent_from_the_export_stays_empty(tmp_path):
    from relay.resolve.insights_fill import fill_instagram_from_insights

    index = build_index([_csv(tmp_path, IG_ROWS, header=IG_HEADER, name="ig.csv")])
    run = _sheet([({}, "ক্যাপশন", datetime(2026, 6, 29))])
    run.rows[0].links["ig"] = "https://www.instagram.com/p/NOTINEXPORT/"

    assert fill_instagram_from_insights(run, index) == 0
    assert run.rows[0].cells["ig"].value is None


def test_one_index_serves_both_exports(tmp_path):
    """Facebook and Instagram files are loaded into a single index; each join
    keys on the identifier its own platform actually carries."""
    index = build_index([_csv(tmp_path, ROWS),
                         _csv(tmp_path, IG_ROWS, header=IG_HEADER, name="ig.csv")])
    assert len(index) == 5
    assert index.lookup(f"{PAGE}pfbid0AAA").post_id == "1001"
    assert index.lookup_ig("https://www.instagram.com/p/DaL7buhEzbR/").views == 87275
    # neither join answers for the other platform's URLs
    assert index.lookup_ig(f"{PAGE}pfbid0AAA") is None
    assert index.lookup("https://www.instagram.com/p/DaL7buhEzbR/") is None


def test_an_unaccounted_cell_says_it_needs_a_post_visit(tmp_path):
    """"awaiting the insights export" is what a cell says before one has been
    consulted. Left there after a fill it reads as "you have not supplied the
    file", when the real reason is usually that Meta recorded no caption for the
    post — 26.7% of a real month's main-page rows carry a blank Title."""
    from relay.resolve.insights_fill import note_unaccounted

    index = build_index([_csv(tmp_path, ROWS)])
    run = _sheet([({"fb1": f"{PAGE}pfbid0NOTHERE"}, "একটি ক্যাপশন যা কোথাও মেলে না",
                   datetime(2026, 7, 4))])
    run.rows[0].links["ig"] = "https://www.instagram.com/p/NOTINEXPORT/"
    # the placeholders rules.build_row leaves before any export is consulted
    run.rows[0].cells["fb1"] = CellValue.missing("awaiting the insights export")
    run.rows[0].cells["ig"] = CellValue.missing("awaiting the Instagram export")

    assert note_unaccounted(run) == 2
    assert "identify it by its post id" in run.rows[0].cells["fb1"].note
    assert "no row for this post" in run.rows[0].cells["ig"].note
    # idempotent, and a cell that already explains itself is left alone
    run.rows[0].cells["fb1"].note = "something more specific"
    assert note_unaccounted(run) == 0
    assert run.rows[0].cells["fb1"].note == "something more specific"


def test_a_page_no_export_covers_is_named_outright(tmp_path):
    """The June sheet links somoytechnews and drishshopot, and neither page is
    in the export at all. No caption and no post id can resolve those — the only
    fix is to export the page, so the run says which page and how many links."""
    from relay.resolve.insights_fill import note_unaccounted, uncovered_pages

    index = build_index([_csv(tmp_path, ROWS)])          # somoysongbad360 only
    run = _sheet([({"fb1": f"{PAGE}pfbid0A",
                    "fb2": "https://www.facebook.com/somoytechnews/posts/pfbid0B"},
                   "একটি ক্যাপশন যা কোথাও মেলে না", datetime(2026, 7, 4))])
    assert index.covers("somoysongbad360") and not index.covers("somoytechnews")
    assert uncovered_pages(run, index) == {"somoytechnews": 1}

    for slot in ("fb1", "fb2"):
        run.rows[0].cells[slot] = CellValue.missing("awaiting the insights export")
    note_unaccounted(run, index)
    # the covered page gets the "run the post-id pass" advice…
    assert "identify it by its post id" in run.rows[0].cells["fb1"].note
    # …the uncovered one is told the truth: nothing will ever fill it
    assert "none of the supplied exports cover somoytechnews" in run.rows[0].cells["fb2"].note


# --- reach and engagement, the report's other two Facebook figures ---
#
# The report prints Views, Reach and Engagement per Facebook link. All three have
# to come off the *same* export row, and Engagement has to be Meta's own combined
# "Reactions, comments and shares" rather than a number RELAY adds up — a sponsor
# checks it against Business Suite, where that column is what they see.

def test_engagement_reads_metas_combined_column_not_the_parts(tmp_path):
    """ROWS' first post has RCS 7 beside Reactions 5 and Comments 2. The
    combined column is the figure of record; 5 + 2 only happens to agree here,
    and would not once Shares is non-zero."""
    index = build_index([_csv(tmp_path, ROWS)])
    row = index.lookup(f"{PAGE}pfbid0AAA")
    assert (row.views, row.reach) == (564, 393)
    assert row.engagement == 7
    assert (row.reactions, row.comments) == (5, 2)


def test_engagement_is_reconstructed_only_when_the_column_is_absent(tmp_path):
    header = ('"Post ID","Page ID","Page name",Title,"Publish time",Permalink,'
              '"Is share","Post type",Views,Reach,Reactions,Comments,Shares\n')
    rows = (f'3001,900,"p","cap","07/03/2026 10:00",{PAGE}pfbid0NOCOMBINED,'
            '0,Photos,500,300,40,7,3\n'
            # one part missing: a partial sum would be a smaller number wearing
            # the same label, so no engagement is claimed at all
            f'3002,900,"p","cap2","07/03/2026 10:00",{PAGE}pfbid0PARTIAL,'
            '0,Photos,500,300,40,,\n')
    index = build_index([_csv(tmp_path, rows, header=header)])
    assert index.lookup(f"{PAGE}pfbid0NOCOMBINED").engagement == 50
    assert index.lookup(f"{PAGE}pfbid0PARTIAL").engagement is None


def test_a_filled_cell_carries_reach_and_engagement_from_its_own_row(tmp_path):
    index = build_index([_csv(tmp_path, ROWS)])
    cell = cell_from_insights(index.lookup(f"{PAGE}pfbid0BBB"), "views")
    assert (cell.value, cell.reach, cell.engagement) == (4000, 2800, 120)


def test_a_cell_no_export_filled_offers_no_reach_or_engagement():
    """A collector reads a view count off the post page and a manual entry is a
    single typed number — neither has reach or engagement, and the report must
    leave those blank rather than print a zero the post never reported."""
    blank = CellValue.missing("awaiting the insights export")
    assert blank.reach is None and blank.engagement is None
    typed = CellValue(1234, "manual", 1.0, "manual entry")
    assert typed.reach is None and typed.engagement is None


def test_reactions_column_is_still_not_mistaken_for_the_combined_one():
    """The guard that made resolve_headers claim exact matches first now has a
    third neighbour to keep apart."""
    cols = resolve_headers(["Views", "Reach", "Reactions, comments and shares",
                            "Reactions", "Comments", "Shares", "Permalink"])
    assert cols["engagement"] == 2
    assert cols["reactions"] == 3
    assert cols["comments"] == 4 and cols["shares"] == 5
