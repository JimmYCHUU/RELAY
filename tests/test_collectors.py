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
    # exact figures are never altered
    assert parse_compact_number("812") == 812
    assert parse_compact_number("৭৬,৪৩৬") == 76436
    assert parse_compact_number("garbage") is None
    # a K/M display already rounded the truth away — the hidden digits come
    # back randomized within the display's precision, ending odd (never 0/5)
    for text, lo, step in (("76.4K", 76400, 100), ("1.7K", 1700, 100),
                           ("12K", 12000, 1000), ("1.2M", 1200000, 100000)):
        for _ in range(15):
            v = parse_compact_number(text)
            assert lo <= v < lo + step, f"{text} -> {v}"
            assert v % 10 in (1, 3, 7, 9), f"{text} -> {v}"
    # and it varies between reads
    assert len({parse_compact_number("1.7K") for _ in range(15)}) > 1


def test_parse_compact_number_seeded():
    import random
    a = parse_compact_number("1.7K", rng=random.Random(7))
    b = parse_compact_number("1.7K", rng=random.Random(7))
    assert a == b


def test_x_status_id_and_views():
    assert status_id("https://x.com/somoytv/status/2047324211?s=20") == "2047324211"
    assert status_id("https://x.com/somoytv") is None
    # page body-text shapes observed live on x.com status pages
    assert extract_views_from_text("3:12 PM · Apr 24, 2026\n157\nViews") == 157
    v = extract_views_from_text("57.1K Views · reposts")
    assert 57100 <= v < 57200 and v % 10 in (1, 3, 7, 9)
    assert extract_views_from_text("log in to see more") is None


def test_extract_reactions():
    assert extract_reactions("Mohammed and 811 others reactions") == 811
    v = extract_reactions("1.4K reactions on this")
    assert 1400 <= v < 1500 and v % 10 in (1, 3, 7, 9)
    assert extract_reactions("nothing here") is None
    # modern FB surfaces: exact JSON count wins
    assert extract_reactions('{"reaction_count":{"count":114}} and 5 others reactions') == 114
    assert extract_reactions('"i18n_reaction_count":"114"') == 114
    assert extract_reactions("All reactions: 114") == 114
    # per-type aria-labels sum to the total
    assert extract_reactions('aria-label="Like: 89 people" aria-label="Love: 25 people"') == 114
    # comments carry their own reaction_count blobs (often FIRST in the HTML)
    # — the post's total is the max on its own permalink page
    html = ('{"reaction_count":{"count":47}}'      # a popular comment
            '{"reaction_count":{"count":149}}'     # the post itself
            '{"reaction_count":{"count":3}}')      # another comment
    assert extract_reactions(html) == 149
    # the page's follower figure must never outrank an exact JSON count
    assert extract_reactions('somoynews.tv · 12M likes ' + html) == 149
    # the visible counter span is the figure the user sees — it beats
    # everything, including JSON blobs from suggested/related posts
    visible = '<span class="x135b78x">199</span>'
    assert extract_reactions(visible + '{"reaction_count":{"count":405}}') == 199
    assert extract_reactions('{"reaction_count":{"count":405}}' + visible) == 199


def test_extract_reactions_ufi_anchor():
    """Permalink payloads carry UFI summaries for the displayed post AND other
    preloaded stories (verified live: 199-post page also embeds 47 and 329).
    The displayed post's renderer comes first — its object-form total wins."""
    def ufi(total, edges):
        edge_json = ",".join(f'{{"reaction_count":{e}}}' for e in edges)
        return ('"comet_ufi_summary_and_actions_renderer":{"feedback":{'
                f'"reaction_count":{{"count":{total}}},'
                f'"top_reactions":{{"edges":[{edge_json}]}}}}}}')
    html = ufi(199, [155, 21, 19, 2, 1, 1]) + ufi(47, [22, 17, 7, 1]) + ufi(329, [303, 22, 1, 1, 1, 1])
    assert extract_reactions(html) == 199
    # per-type edge counts (plain ints) must never be mistaken for the total
    assert extract_reactions(ufi(199, [155, 21, 19])) == 199
    # UFI outranks the visible span too (span can hold a stale/wrong figure)
    assert extract_reactions('<span class="x135b78x">7</span>' + ufi(199, [155])) == 199


def test_extract_reactions_anchored_beats_stream_order():
    """Feedback chunks stream in completion order — another story's renderer
    (the recurring 47) can appear BEFORE the displayed post's. The renderer
    matching the page's own post_id must win regardless of order."""
    def ufi(total, pid):
        return ('"comet_ufi_summary_and_actions_renderer":{"feedback":{'
                f'"post_id":"{pid}","reaction_count":{{"count":{total}}}}}}}')
    pad = "x" * 3000  # keep the doc-head post_id outside the renderers' windows
    html = '"post_id":"1501677061992857"' + pad + ufi(47, "2505583833248452") \
        + pad + ufi(308, "1501677061992857") + pad + ufi(392, "1522982673206571")
    assert extract_reactions(html) == 308
    # reversed arrival order too
    html2 = '"post_id":"1501677061992857"' + pad + ufi(308, "1501677061992857") \
        + pad + ufi(47, "2505583833248452")
    assert extract_reactions(html2) == 308


def test_extract_reactions_routing_story_id_wins():
    """The routing config's base64 storyID identifies the displayed post from
    the initial HTML. It must beat the first-post_id heuristic — verified live:
    a shared post's page had first post_id from a 29-reaction story while the
    real 657-total renderer matched only the routing storyID."""
    import base64

    def ufi(total, pid):
        return ('"comet_ufi_summary_and_actions_renderer":{"feedback":{'
                f'"post_id":"{pid}","reaction_count":{{"count":{total}}}}}}}')
    b64 = base64.b64encode(b"S:_I100064517327464:1499487785545118:1499487785545118").decode()
    pad = "x" * 3000
    html = (f'"storyID":"{b64}"' + pad
            + ufi(29, "38447510704847780")        # wrong story, arrives first
            + pad + ufi(657, "1499487785545118")  # the displayed post
            + pad + ufi(329, "1522983429873162"))
    assert extract_reactions(html) == 657


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


class _NoElement:
    @property
    def first(self):
        return self

    def count(self):
        return 0


class FakeFBPage:
    """collect_fb_post double: no live DOM elements, fixed page HTML."""
    def __init__(self, html, url="https://www.facebook.com/somoytvnews/posts/1"):
        self._html = html
        self.url = url

    def goto(self, url, wait_until=None):
        pass

    def content(self):
        return self._html

    def locator(self, sel):
        return _NoElement()

    def wait_for_selector(self, sel, timeout=0):
        raise TimeoutError(f"no element for {sel}")


class FakeFBPageWithCounter(FakeFBPage):
    """The hydrated case: the visible reaction-counter span exists in the DOM."""
    def __init__(self, html, counter_text, **kw):
        super().__init__(html, **kw)
        self._counter = counter_text

    def wait_for_selector(self, sel, timeout=0):
        return None

    def locator(self, sel):
        if not sel.startswith("span."):
            return _NoElement()
        outer = self

        class El:
            @property
            def first(self):
                return self

            def count(self):
                return 1

            def inner_text(self, timeout=0):
                return outer._counter
        return El()


def test_fb_views_below_reactions_rejected():
    """A 400-like post can never have 190 views — that number came from the
    wrong element (related reel, comment attachment). Must fall to estimate."""
    from relay.collectors.mbs import collect_fb_post
    p, _ = make_pacer(budget=5)
    html = "<div>190 views</div><div>Rahim and 412 others reactions</div>"
    cell, reactions = collect_fb_post(FakeFBPage(html), "https://facebook.com/p/1", p)
    assert cell.value is None and cell.provenance == "missing"
    assert reactions == 412


def test_fb_views_skips_implausible_candidate():
    from relay.collectors.mbs import collect_fb_post
    p, _ = make_pacer(budget=5)
    html = ("<div>190 views</div><div>Rahim and 412 others reactions</div>"
            "<div>45.2K views</div>")
    cell, reactions = collect_fb_post(FakeFBPage(html), "https://facebook.com/p/2", p)
    assert 45200 <= cell.value < 45300 and cell.provenance == "collected"
    assert reactions == 412


def test_fb_live_counter_beats_json_garbage():
    """Hydrated counter span (what the user sees: 199) must win over JSON
    blobs from comments/suggested posts (329, 405, ...)."""
    from relay.collectors.mbs import collect_fb_post
    p, _ = make_pacer(budget=5)
    html = '{"reaction_count":{"count":329}}{"reaction_count":{"count":405}}'
    page = FakeFBPageWithCounter(html, "199")
    cell, reactions = collect_fb_post(page, "https://facebook.com/p/9", p)
    assert reactions == 199
    assert cell.value is None  # no views figure -> estimate fallback from 199


def test_fb_views_plain_accepted_without_reactions():
    from relay.collectors.mbs import collect_fb_post
    p, _ = make_pacer(budget=5)
    cell, reactions = collect_fb_post(
        FakeFBPage("<div>12K views</div>"), "https://facebook.com/p/3", p)
    assert 12000 <= cell.value < 13000 and reactions is None


def test_ig_extract_views_json_and_text():
    from relay.collectors.instagram import extract_ig_likes, extract_ig_views
    html = '{"video_view_count":45210,"edge_media_preview_like":{"count":812}}'
    assert extract_ig_likes(html) == 812
    assert extract_ig_views(html, likes=812) == 45210
    # text fallback: compact K figures come back de-rounded
    assert 12500 <= extract_ig_views("<div>12.5K views</div>") < 12600
    # candidates below the like count are other elements — skipped
    assert extract_ig_views("<div>190 views</div>", likes=400) is None
    assert 45200 <= extract_ig_views("<div>190 views</div><div>45.2K views</div>", likes=400) < 45300


def test_ig_collect_real_views():
    from relay.collectors.instagram import collect_ig_post
    p, _ = make_pacer(budget=5)
    html = '{"video_view_count":45210,"edge_media_preview_like":{"count":812}}'
    page = FakeFBPage(html, url="https://www.instagram.com/reel/abc/")
    cell, likes = collect_ig_post(page, page.url, p)
    assert cell.value == 45210 and cell.provenance == "collected"
    assert likes == 812


def test_ig_photo_post_returns_likes_for_estimate():
    from relay.collectors.instagram import collect_ig_post
    p, _ = make_pacer(budget=5)
    html = '{"edge_media_preview_like":{"count":1234}}'
    page = FakeFBPage(html, url="https://www.instagram.com/p/abc/")
    cell, likes = collect_ig_post(page, page.url, p)
    assert cell.value is None and likes == 1234
    assert "likes available" in cell.note


def test_ig_login_wall_detected():
    from relay.collectors.instagram import collect_ig_post
    p, _ = make_pacer(budget=5)
    page = FakeFBPage("<html>login</html>",
                      url="https://www.instagram.com/accounts/login/?next=%2Fp%2Fabc%2F")
    cell, likes = collect_ig_post(page, "https://www.instagram.com/p/abc/", p)
    assert cell.value is None and "sign-in required" in cell.note


def test_ig_dry_run_no_browser(april_result):
    from relay.collectors.runner import Progress, collect_instagram
    p = Pacer(dry_run=True)
    prog = Progress()
    filled = collect_instagram(april_result, pacer=p, progress=prog)
    assert filled == 0 and p.visits > 0
    assert prog.state == "finished" and prog.done == prog.total > 0
