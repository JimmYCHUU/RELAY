"""Portability guards for the Windows desktop, where the supervisor runs RELAY.

The dashboard reported a Ruchi run as `400 Bad Request — "Invalid format string"`
on Windows and nowhere else. The cause was `f"{fill:%-d %b}"` in the campaign
parser's blank-date repair: `%-d` is a glibc extension, and the Windows C runtime
rejects it outright. It only fired on a sheet that actually had a blank Date to
backfill, which is why two of Ruchi's three tabs failed and the third did not.

The bug is one character wide and would come back the next time someone writes a
date into a message, so the guard here is a scan of the source rather than a test
of that one call site.
"""
from __future__ import annotations

import io
import re
import tokenize
from datetime import datetime
from pathlib import Path

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "relay"

# `%-d`/`%-m`/… (glibc) and `%#d`/… (MSVC): each drops zero-padding, and neither
# runtime accepts the other's spelling. `time.strftime` is the portable subset.
_NO_PAD = re.compile(r"%[-#][aAbBcdHIjmMpSUwWxXyYZ]")


def _sources() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def _format_strings(path: Path):
    """Every string literal in a module, with its line number.

    Tokenized rather than grepped so a comment may name the directive it is
    warning about — the two call sites this bug touched now do exactly that.
    """
    src = path.read_text(encoding="utf-8")
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type in (tokenize.STRING, getattr(tokenize, "FSTRING_MIDDLE", -1)):
            yield tok.start[0], tok.string


def test_no_platform_specific_strftime_directives():
    offenders = []
    for path in _sources():
        for lineno, text in _format_strings(path):
            if _NO_PAD.search(text):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {text.strip()}")
    assert not offenders, (
        "glibc/MSVC-only strftime directives crash on the other platform — "
        "use `{dt.day}` or `%d` instead:\n" + "\n".join(offenders))


def _campaign_with_a_blank_date(path: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Brand", None, None, None, None, None, None, None])
    ws.append(["No", "Date", "Content's name", "Content's Link",
               "Content's Link 2", "Content's Link 3", "X, Link 4", "Instagram"])
    link = "https://www.facebook.com/somoynews.tv/posts/pfbid0A"
    ws.append([1, datetime(2026, 6, 5), "first", link, None, None, None, None])
    # the row that trips it: a caption and a link, but no Date
    ws.append([2, None, "second", link, None, None, None, None])
    wb.save(path)
    return path


def test_a_backfilled_date_is_reported_without_a_strftime_extension(tmp_path):
    """The note this produces is the one that crashed. It must read the same on
    both platforms and carry no leftover format directive."""
    from relay.ingest.campaign import parse_campaign

    rows, issues = parse_campaign(_campaign_with_a_blank_date(tmp_path / "c.xlsx"),
                                  "Sheet")
    assert rows[1].date == datetime(2026, 6, 5)
    note = next(i.reason for i in issues if "filled from adjacent" in i.reason)
    assert note == "empty Date filled from adjacent row (5 Jun)"
    assert "%" not in note


def test_the_run_endpoint_names_the_tab_when_a_sheet_fails(tmp_path):
    """A bare "Invalid format string" told the user nothing about where it came
    from — a 400 from /api/run now says which tab failed."""
    from fastapi.testclient import TestClient

    from relay.web.app import app

    wb = openpyxl.Workbook()
    wb.active.append(["nothing", "resembling", "a header"])
    path = tmp_path / "headerless.xlsx"
    wb.save(path)

    res = TestClient(app).post("/api/run", json={
        "campaign": str(path), "sheet": "Sheet", "brand": "Ruchi"})
    assert res.status_code == 400
    assert "Sheet" in res.json()["detail"]


@pytest.mark.parametrize("name", [
    "sub\\evil.xlsx",           # a backslash is a path separator on Windows only
    "../evil.xlsx",
    "sub/evil.xlsx",
    "report.exe",
])
def test_report_downloads_reject_a_name_that_is_not_a_plain_filename(name):
    from fastapi import HTTPException

    from relay.web.app import _safe_output

    with pytest.raises(HTTPException) as exc:
        _safe_output(name)
    assert exc.value.status_code == 400


@pytest.mark.parametrize("title,expected", [
    ("June", "June"),
    ("June/July [draft]", "June-July -draft-"),      # Excel rejects / [ ]
    ("x" * 40, "x" * 31),                            # and caps titles at 31
    ("", "Report"),
])
def test_sheet_titles_are_sanitized_for_excel(title, expected):
    from relay.report.generator import _safe_title

    assert _safe_title(title) == expected
