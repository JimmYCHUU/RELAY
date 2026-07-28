"""Caption normalization and brand-separator detection (SDD 5.1, 5.2)."""
from __future__ import annotations

import re
import unicodedata

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍﻿"))
_WS = re.compile(r"\s+")
_WRAP_QUOTES = "\"'“”«»‘’"
# Bengali sentence punctuation। Latin punctuation. Captions have these; brand tokens don't.
_SENTENCE_PUNCT = set("।,.!?:;—–")

# 83% of a real month's export titles end in the same call-to-action plus a
# hashtag block, which the campaign sheet's caption never carries. Everything
# from the marker to the end of the title is Somoy's own post furniture.
_BOILERPLATE_TAIL = re.compile(
    r"(বিস্তারিত\s*কমেন্টে|বিস্তারিত\s*জানতে|details\s+in\s+comments?).*$",
    re.IGNORECASE | re.DOTALL)
_HASHTAG = re.compile(r"#\S+")


def normalize_caption(text: str) -> str:
    """Canonical comparison key for a caption."""
    s = unicodedata.normalize("NFC", text)
    s = s.translate(_ZERO_WIDTH)
    s = _WS.sub(" ", s).strip()
    s = s.strip(_WRAP_QUOTES).strip()
    while s.endswith(("…", "...")):
        s = s[:-1] if s.endswith("…") else s[:-3]
        s = s.rstrip()
    return s


def strip_boilerplate(text: str) -> str:
    """A caption with Somoy's own post furniture removed.

    Used only as a *secondary* comparison key, at a much stricter threshold than
    the raw one (`config.INSIGHTS_STRIPPED_HIGH`). Removing the tail shortens
    the token set, and `token_set_ratio` on a short set stops noticing the one
    word that reverses a headline — a real June row read "স্বর্ণের দাম আরেক দফা
    বাড়ানোর" (raised) and scored 0.93 against an export row that said "কমানোর"
    (cut), a different post two days later. Near-identity is the only safe bar.
    """
    return normalize_caption(_HASHTAG.sub("", _BOILERPLATE_TAIL.sub("", text)))


def _ascii_fraction(s: str) -> float:
    core = [c for c in s if not c.isspace()]
    if not core:
        return 0.0
    return sum(c.isascii() for c in core) / len(core)


def is_brand_separator(title: str, has_values: bool) -> bool:
    """A bare brand token row that splits a multi-brand matched file.

    Brand tokens ("acme", "Brand A") are short, Latin-script, carry no
    sentence punctuation, and never have match values. Bengali captions fail
    the ASCII test; ASCII-looking captions fail length/punctuation/value tests.
    """
    if has_values:
        return False
    t = normalize_caption(title)
    if not t or len(t) > 40:
        return False
    if any(c in _SENTENCE_PUNCT for c in t):
        return False
    return _ascii_fraction(t) >= 0.6
