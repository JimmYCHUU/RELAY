"""Shared Playwright session handling (persistent profile → one-time 2FA login)."""
from __future__ import annotations

import logging
import shutil
from contextlib import contextmanager
from pathlib import Path

from .. import config

log = logging.getLogger("relay.collectors")

_SYSTEM_CHROME = (
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
)


def _executable() -> str | None:
    """Prefer Playwright's bundled Chromium; fall back to a system browser."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            path = pw.chromium.executable_path
            if Path(path).exists():
                return None  # bundled browser available — let Playwright use it
    except Exception:
        pass
    for cand in _SYSTEM_CHROME:
        if shutil.which(cand) or Path(cand).exists():
            return cand
    return None


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
            executable_path=_executable(),
            headless=not headed,
            viewport={"width": 1400, "height": 900},
            locale="en-US",
        )
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            yield page
        finally:
            ctx.close()


def _block_media(page) -> None:
    """Abort image/video/font requests — every figure RELAY extracts is
    text/HTML, and skipping media keeps renderer memory and load times flat."""
    page.route("**/*", lambda route: route.abort()
               if route.request.resource_type in ("image", "media", "font")
               else route.continue_())


class MetaSession:
    """Persistent-profile Chromium that relaunches its context every
    `recycle_every` page visits. One context navigated through hundreds of
    heavy MBS/IG SPA pages grows its renderer heap until the machine swaps;
    cookies live in the on-disk profile, so a relaunch never loses the login."""

    def __init__(self, pw, profile_dir: str, headed: bool, recycle_every: int):
        self._pw = pw
        self._profile_dir = profile_dir
        self._headed = headed
        self._recycle_every = max(1, recycle_every)
        self._ctx = None
        self._page = None
        self._visits = 0

    def _launch(self):
        self._ctx = self._pw.chromium.launch_persistent_context(
            user_data_dir=self._profile_dir,
            executable_path=_executable(),
            headless=not self._headed,
            viewport={"width": 1400, "height": 900},
            locale="en-US",
        )
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        if config.BLOCK_MEDIA_META:
            _block_media(self._page)
        self._visits = 0

    def page(self):
        """The current page — counts one visit, recycling the context first
        when the threshold is reached."""
        if self._ctx is not None and self._visits >= self._recycle_every:
            log.info("recycling browser context after %d visits", self._visits)
            self.close()
        if self._ctx is None:
            self._launch()
        self._visits += 1
        return self._page

    def close(self):
        if self._ctx is not None:
            try:
                self._ctx.close()
            except Exception:
                pass
            self._ctx = None
            self._page = None


@contextmanager
def persistent_session(profile: str, headed: bool = False,
                       recycle_every: int | None = None):
    """Like persistent_page, but hands out pages through MetaSession so long
    batches get a fresh context every CONTEXT_RECYCLE_EVERY visits."""
    from playwright.sync_api import sync_playwright

    profile_dir = Path(config.PROFILE_DIR) / profile
    profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        sess = MetaSession(pw, str(profile_dir), headed,
                           recycle_every or config.CONTEXT_RECYCLE_EVERY)
        try:
            yield sess
        finally:
            sess.close()


@contextmanager
def anonymous_page():
    """A fresh logged-out browser page — used for public X scraping (C-3:
    no credentials, no persisted state)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=_executable(), headless=True)
        try:
            page = browser.new_page(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/126 Safari/537.36",
                viewport={"width": 1280, "height": 900},
            )
            # the Views figure is text — skip photos/video/fonts for much
            # faster loads (fine here: this context is logged out, C-3)
            _block_media(page)
            yield page
        finally:
            browser.close()


def login_meta() -> None:
    """Open a headed browser for the user to log into Facebook/Meta Business
    Suite (2FA included). Nothing is scraped; cookies persist in the profile."""
    try:
        with persistent_page("meta", headed=True) as page:
            page.goto("https://business.facebook.com/")
            log.info("Complete the login (incl. 2FA) in the opened window, then close it.")
            page.wait_for_event("close", timeout=0)
    except Exception:
        # Closing the whole browser window (the normal way) surfaces as
        # TargetClosedError rather than a clean close event — same meaning.
        pass
    # Marker distinguishes "sign-in window was opened and closed" from "browser
    # was merely launched once" — the profile dir alone can't tell those apart.
    (Path(config.PROFILE_DIR) / "meta" / ".relay-login-complete").touch()
