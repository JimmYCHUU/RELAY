"""Shared Playwright session handling (persistent profile → one-time 2FA login)."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path

from .. import config

log = logging.getLogger("relay.collectors")


@contextmanager
def persistent_page(profile: str, headed: bool = False):
    """Yield a Playwright page bound to a persistent local profile.

    The profile directory keeps cookies between runs, so the user completes the
    Facebook 2FA login exactly once (`relay login meta`, headed).
    """
    from playwright.sync_api import sync_playwright

    profile_dir = Path(config.PROFILE_DIR) / profile
    profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=not headed,
            viewport={"width": 1400, "height": 900},
            locale="en-US",
        )
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            yield page
        finally:
            ctx.close()


def login_meta() -> None:
    """Open a headed browser for the user to log into Facebook/Meta Business
    Suite (2FA included). Nothing is scraped; cookies persist in the profile."""
    with persistent_page("meta", headed=True) as page:
        page.goto("https://business.facebook.com/")
        log.info("Complete the login (incl. 2FA) in the opened window, then close it.")
        page.wait_for_event("close", timeout=0)
