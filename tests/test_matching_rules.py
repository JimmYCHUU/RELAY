import pytest

from relay.matching.engine import match_rows
from relay.models import CampaignRow, CellValue, Match, MatchedRow
from relay.resolve.heuristic import apply_estimate, estimate_views
from relay.resolve.rules import build_row


def crow(caption="ক্যাপশন", links=(None, None, None), x=None, ig=None, no=1):
    return CampaignRow(no, None, caption, list(links), x, ig)


def mrow(title, values):
    return MatchedRow(title=title, values=values)


def m(row, tier="exact", conf=1.0):
    return Match(row, tier, conf)


# --- engine ---

def test_exact_match_consumes_one_to_one():
    camp = [crow("একই ক্যাপশন", no=1), crow("একই ক্যাপশন", no=2)]
    matched = [mrow("একই ক্যাপশন", [10]), mrow("একই ক্যাপশন", [20])]
    res = match_rows(camp, matched)
    assert [r.matched.values[0] for r in res] == [10, 20]


def test_prefix_match_truncation():
    long_cap = "নিউজিল্যান্ডের বিপক্ষে তৃতীয় ওয়ানডেতে বাংলাদেশের সম্ভাবনা নিয়ে আলোচনা"
    camp = [crow(long_cap)]
    matched = [mrow(long_cap[:40], [5])]
    res = match_rows(camp, matched)
    assert res[0].tier == "prefix"


def test_fuzzy_and_none():
    camp = [crow("সম্পূর্ণ ভিন্ন একটি বাক্য যা কোথাও নেই")]
    matched = [mrow("অন্য কিছু সম্পূর্ণ আলাদা লেখা এখানে", [1])]
    res = match_rows(camp, matched)
    assert res[0].tier in ("none", "review")


# --- rules ---

def test_fb1_mainpage_vm1():
    row = crow(links=("http://fb/1", None, None))
    rr = build_row(row, m(mrow("t", [161332])), None, None)
    assert rr.cells["fb1"].value == 161332
    assert rr.cells["fb1"].provenance == "matched"


def test_fb2_vm1_fb3_highest():
    row = crow(links=("http://fb/1", "http://fb/2", "http://fb/3"))
    rr = build_row(row, None, m(mrow("t", [38139, 4891, 8705])), None)
    assert rr.cells["fb2"].value == 38139
    assert rr.cells["fb3"].value == 8705          # highest of the rest
    assert "4891" in rr.cells["fb3"].note          # discard logged


def test_single_sub_slot_gets_vm1():
    # campaign has Link1 + Link3 only: subpage VM1 lands on the fb3 slot
    row = crow(links=("http://fb/1", None, "http://fb/3"))
    rr = build_row(row, None, m(mrow("t", [306634])), None)
    assert rr.cells["fb3"].value == 306634
    assert rr.cells["fb2"].value is None


def test_no_match_stays_missing():
    row = crow(links=("http://fb/1", "http://fb/2", None), ig="http://ig")
    rr = build_row(row, None, None, None)
    for slot in ("fb1", "fb2", "ig"):
        assert rr.cells[slot].value is None
        assert rr.cells[slot].provenance == "missing"


def test_shared_post_flagged():
    row = crow(links=("https://www.facebook.com/share/p/x", None, None))
    rr = build_row(row, Match(None, "none", 0.0), None, None)
    assert "shared post" in rr.cells["fb1"].note


def test_x_never_fabricated():
    row = crow(x="https://x.com/somoytv/status/1")
    rr = build_row(row, None, None, None)
    assert rr.cells["x"].value is None


# --- heuristic ---

def test_estimate_randomized_k():
    # no pinned k -> a fresh multiplier in [70, 150] every call
    values = [estimate_views(812).value for _ in range(40)]
    assert all(812 * 70 <= v <= 812 * 150 + 9 for v in values)
    assert len(set(values)) > 1, "k must vary between estimates"
    cv = estimate_views(812)
    assert cv.provenance == "estimated"
    assert "reactions=812" in cv.note and "k=" in cv.note


def test_estimate_never_ends_in_0_or_5():
    for reactions in (1, 7, 812, 4093):
        for _ in range(20):
            v = estimate_views(reactions).value
            assert v % 10 in (1, 3, 7, 9), f"got {v}"
    # pinned k gets the same last-digit treatment
    assert estimate_views(100, k=100).value % 10 in (1, 3, 7, 9)


def test_estimate_seeded_rng_reproducible():
    import random
    a = estimate_views(812, rng=random.Random(42))
    b = estimate_views(812, rng=random.Random(42))
    assert a.value == b.value and a.note == b.note


def test_k_bounds():
    with pytest.raises(ValueError):
        estimate_views(10, k=50)
    with pytest.raises(ValueError):
        estimate_views(10, k=151)
    estimate_views(10, k=150)  # new upper bound is valid


def test_estimate_refuses_matched_cell():
    cell = CellValue(100, "matched", 1.0)
    with pytest.raises(ValueError):
        apply_estimate(cell, reactions=10)
    # but fills a missing cell fine
    filled = apply_estimate(CellValue.missing(), reactions=10)
    assert 10 * 70 <= filled.value <= 10 * 150 + 9
    assert filled.value % 10 in (1, 3, 7, 9)
