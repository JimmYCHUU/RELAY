import pytest

from relay.collectors.base import BudgetExceeded, ChallengeDetected, Pacer, parse_compact_number
from relay.collectors.mbs import extract_reactions
from relay.collectors.xpublic import extract_views_from_text, status_id


def make_pacer(**kw):
    p = Pacer(**kw)
    delays = []
    p._sleep = delays.append          # capture instead of sleeping
    return p, delays


def test_pacer_delays_within_bounds():
    p, delays = make_pacer(min_delay=8, max_delay=15, budget=10)
    for i in range(10):
        p.before_visit(f"https://example.com/{i}")
    assert len(delays) == 10
    assert all(8 <= d <= 15 for d in delays)


def test_pacer_budget_enforced():
    p, _ = make_pacer(budget=2)
    p.before_visit("u1")
    p.before_visit("u2")
    with pytest.raises(BudgetExceeded, match="preserved"):
        p.before_visit("u3")


def test_pacer_dry_run_no_sleep():
    p, delays = make_pacer(dry_run=True, budget=5)
    p.before_visit("u1")
    assert delays == [] and p.visits == 1 and p.log_lines


def test_challenge_detection_aborts():
    p, _ = make_pacer()
    with pytest.raises(ChallengeDetected):
        p.check_challenge("https://facebook.com/checkpoint/", "<html>")
    with pytest.raises(ChallengeDetected):
        p.check_challenge("https://x.com/ok", "please solve this CAPTCHA to continue")
    p.check_challenge("https://x.com/ok", "a normal page")  # no raise


def test_parse_compact_number():
    assert parse_compact_number("76.4K") == 76400
    assert parse_compact_number("1.2M") == 1200000
    assert parse_compact_number("812") == 812
    assert parse_compact_number("৭৬,৪৩৬") == 76436
    assert parse_compact_number("garbage") is None


def test_x_status_id_and_views():
    assert status_id("https://x.com/somoytv/status/2047324211?s=20") == "2047324211"
    assert status_id("https://x.com/somoytv") is None
    # page body-text shapes observed live on x.com status pages
    assert extract_views_from_text("3:12 PM · Apr 24, 2026\n157\nViews") == 157
    assert extract_views_from_text("57.1K Views · reposts") == 57100
    assert extract_views_from_text("log in to see more") is None


def test_extract_reactions():
    assert extract_reactions("Mohammed and 811 others reactions") == 811
    assert extract_reactions("1.4K reactions on this") == 1400
    assert extract_reactions("nothing here") is None


def test_dry_run_collect_no_browser(april_result):
    """Dry run must never launch Playwright (browser import sits after the guard)."""
    from relay.collectors.runner import Progress, collect_facebook, collect_x
    p = Pacer(dry_run=True)
    prog = Progress()
    filled = collect_facebook(april_result, k=95, pacer=p, progress=prog)
    assert filled == 0 and p.visits > 0
    assert prog.state == "finished" and prog.done == prog.total > 0
    p2 = Pacer(dry_run=True)
    prog2 = Progress()
    collect_x(april_result, pacer=p2, progress=prog2)
    assert prog2.state == "finished"
    assert all(r.cells["x"].value is None for r in april_result.rows)
