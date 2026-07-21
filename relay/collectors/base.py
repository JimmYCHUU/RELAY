"""Pacing / account-safety layer every collector must go through (NFR-6).

Hard guarantees:
- randomized inter-visit delay within [PACE_MIN_S, PACE_MAX_S];
- a hard per-session navigation budget (BudgetExceeded, session preserved);
- immediate abort when a challenge/checkpoint page is detected;
- dry-run mode performs zero network activity.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field

from .. import config

log = logging.getLogger("relay.collectors")


class BudgetExceeded(RuntimeError):
    pass


class ChallengeDetected(RuntimeError):
    """A checkpoint/captcha page appeared — stop immediately, keep the session."""


@dataclass
class Pacer:
    min_delay: float = config.PACE_MIN_S
    max_delay: float = config.PACE_MAX_S
    budget: int = config.SESSION_NAV_BUDGET
    dry_run: bool = False
    visits: int = 0
    log_lines: list[str] = field(default_factory=list)
    _sleep = staticmethod(time.sleep)
    _rand = staticmethod(random.uniform)

    def before_visit(self, url: str) -> None:
        if self.visits >= self.budget:
            raise BudgetExceeded(
                f"session budget of {self.budget} navigations reached — "
                "run again later; the login session is preserved"
            )
        self.visits += 1
        line = f"visit {self.visits}/{self.budget}: {url}"
        self.log_lines.append(line)
        if self.dry_run:
            log.info("[dry-run] %s", line)
            return
        delay = self._rand(self.min_delay, self.max_delay)
        log.info("%s (waiting %.1fs)", line, delay)
        self._sleep(delay)

    def check_challenge(self, page_url: str, page_text: str) -> None:
        haystack = (page_url + " " + page_text[:2000]).lower()
        for marker in config.CHALLENGE_MARKERS:
            if marker in haystack:
                raise ChallengeDetected(
                    f"challenge marker '{marker}' detected at {page_url}; "
                    "aborting collection — complete the check manually in a "
                    "normal browser, then retry"
                )


def parse_compact_number(text: str, rng: random.Random | None = None) -> int | None:
    """'812' -> 812 exactly; suffixed figures get their hidden digits back:
    '76.4K' -> 764xx, '1.7K' -> 17xx (e.g. 1783), '1.2M' -> 12xxxxx.

    A compact 'K/M/B' display already rounded the real count away, so writing
    the bare 1700 into a report reads machine-made. The resurrected digits are
    random within the display's precision and end odd (never 0 or 5), matching
    the estimate style. Exact figures (no suffix) are never altered.
    Bengali digits OK.
    """
    if not text:
        return None
    bn = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
    s = (text.strip().translate(bn).replace(",", "")
         .replace("\u00a0", " ").replace("\u202f", " ").strip())
    mult = 1.0
    for suffix, m in (("k", 1e3), ("m", 1e6), ("b", 1e9)):
        if s.lower().endswith(suffix):
            s, mult = s[: -len(suffix)], m
            break
    try:
        base = int(float(s) * mult)
    except ValueError:
        return None
    if mult == 1.0:
        return base                      # exact count -- keep it exact
    decimals = len(s.split(".", 1)[1]) if "." in s else 0
    step = int(mult) // (10 ** decimals)  # '1.7K' -> 100, '12K' -> 1000
    if step <= 1:
        return base
    r = rng or random.Random()
    v = base + r.randrange(step)
    return v - v % 10 + r.choice((1, 3, 7, 9))
