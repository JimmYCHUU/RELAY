"""Caption matcher: exact → prefix → fuzzy, one-to-one consumption (SDD 5.3)."""
from __future__ import annotations

from rapidfuzz import fuzz

from .. import config
from ..models import CampaignRow, Match, MatchedRow
from .normalize import normalize_caption


def match_rows(campaign: list[CampaignRow], matched: list[MatchedRow]) -> list[Match]:
    """One Match per campaign row; each matched row consumed at most once."""
    keys = [normalize_caption(m.title) for m in matched]
    taken = [False] * len(matched)
    result: list[Match | None] = [None] * len(campaign)

    # pass 1: exact normalized equality, in order (duplicates consume in order)
    index: dict[str, list[int]] = {}
    for i, k in enumerate(keys):
        index.setdefault(k, []).append(i)
    for ci, row in enumerate(campaign):
        ck = normalize_caption(row.caption)
        if not ck:
            continue  # caption-less rows never caption-match; links carry them
        for mi in index.get(ck, []):
            if not taken[mi]:
                taken[mi] = True
                result[ci] = Match(matched[mi], "exact", 1.0)
                break

    # pass 2: truncated-title prefix match
    for ci, row in enumerate(campaign):
        if result[ci]:
            continue
        ck = normalize_caption(row.caption)
        for mi, mk in enumerate(keys):
            if taken[mi]:
                continue
            shorter, longer = sorted((ck, mk), key=len)
            if len(shorter) >= config.PREFIX_MIN_LEN and longer.startswith(shorter):
                taken[mi] = True
                result[ci] = Match(matched[mi], "prefix", 0.98)
                break

    # pass 3: fuzzy
    for ci, row in enumerate(campaign):
        if result[ci]:
            continue
        ck = normalize_caption(row.caption)
        if not ck:
            result[ci] = Match(None, "none", 0.0)
            continue
        best_score, best_mi = 0.0, -1
        for mi, mk in enumerate(keys):
            if taken[mi]:
                continue
            score = fuzz.token_set_ratio(ck, mk) / 100.0
            if score > best_score:
                best_score, best_mi = score, mi
        if best_mi >= 0 and best_score >= config.FUZZY_REVIEW:
            taken[best_mi] = True
            tier = "fuzzy" if best_score >= config.FUZZY_HIGH else "review"
            result[ci] = Match(matched[best_mi], tier, round(best_score, 3))
        else:
            result[ci] = Match(None, "none", round(best_score, 3))

    return [m for m in result if m is not None]
