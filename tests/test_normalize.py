import unicodedata

from relay.matching.normalize import is_brand_separator, normalize_caption


def test_nfc_equivalence():
    composed = "কৃষি"
    decomposed = unicodedata.normalize("NFD", composed)
    assert normalize_caption(composed) == normalize_caption(decomposed)


def test_zero_width_stripped():
    with_zwj = "র‍্যাঙ্কিংয়ে"
    without = with_zwj.replace("‍", "")
    assert normalize_caption(with_zwj) == normalize_caption(without)


def test_whitespace_collapsed():
    assert normalize_caption("\nআর্জেন্টিনা -   সুইজারল্যান্ড ") == "আর্জেন্টিনা - সুইজারল্যান্ড"


def test_wrapping_quotes_stripped():
    assert normalize_caption('"ত্রয়োদশ জাতীয় সংসদ নির্বাচন"') == "ত্রয়োদশ জাতীয় সংসদ নির্বাচন"


def test_trailing_ellipsis_stripped():
    assert normalize_caption("কিছু একটা...") == "কিছু একটা"
    assert normalize_caption("কিছু একটা…") == "কিছু একটা"


def test_idempotent():
    s = '  "নিউজিল্যান্ডের বিপক্ষে…" \n'
    assert normalize_caption(normalize_caption(s)) == normalize_caption(s)


def test_separator_detection():
    for token in ("bkash", "Bkash", "White Plus", "SINGER"):
        assert is_brand_separator(token, has_values=False)


def test_caption_not_separator():
    caps = [
        "সাফ অনূর্ধ্ব-২০ চ্যাম্পিয়নশিপের সেমিফাইনাল",
        "ঈদ মোবারক",  # short Bengali
    ]
    for c in caps:
        assert not is_brand_separator(c, has_values=False)


def test_separator_with_values_is_caption():
    assert not is_brand_separator("Bkash", has_values=True)
