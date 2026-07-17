"""Caption normalization and brand-separator detection (SDD 5.1, 5.2)."""
from __future__ import annotations

import re
import unicodedata

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍﻿"))
_WS = re.compile(r"\s+")
_WRAP_QUOTES = "\"'“”«»‘’"
# Bengali sentence punctuation। Latin punctuation. Captions have these; brand tokens don't.
_SENTENCE_PUNCT = set("।,.!?:;—–")


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


def _ascii_fraction(s: str) -> float:
    core = [c for c in s if not c.isspace()]
    if not core:
        return 0.0
    return sum(c.isascii() for c in core) / len(core)


def is_brand_separator(title: str, has_values: bool) -> bool:
    """A bare brand token row that splits a multi-brand matched file.

    Brand tokens ("bkash", "White Plus") are short, Latin-script, carry no
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
