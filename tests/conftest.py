import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SAMPLES = ROOT

CAMPAIGN = SAMPLES / "White Plus Updated FB Photocard Campaign _ Mar'26.xlsx"
REPORT_APRIL = SAMPLES / "White Plus FB Photocard (April).xlsx"
WP_MAIN = SAMPLES / "white plus mainpage matched (1).xlsx"
WP_SUB = SAMPLES / "white plus subpage matched (2).xlsx"
WP_INSTA = SAMPLES / "white plus insta matched (3).xlsx"
ALL_MAIN_APRIL = SAMPLES / "April social card mainpage matched.xlsx"
ALL_MAIN_PENDING = SAMPLES / "Pendding social card mainpage matched.xlsx"
ALL_SUB_PENDING = SAMPLES / "pending social card subpage matched (1).xlsx"


def pytest_collection_modifyitems(config, items):
    """The sample workbooks hold real sponsor data and are git-ignored; when
    they're absent (e.g. CI), skip everything that depends on them."""
    if CAMPAIGN.exists():
        return
    skip = pytest.mark.skip(reason="local sample workbooks not present (excluded from git)")
    file_bound = {"test_ingest", "test_e2e", "test_web", "test_generator"}
    for item in items:
        mod = item.module.__name__.split(".")[-1]
        if mod in file_bound or "april_result" in getattr(item, "fixturenames", ()):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def april_campaign():
    from relay.ingest.campaign import parse_campaign
    rows, issues = parse_campaign(CAMPAIGN, "April")
    return rows, issues


@pytest.fixture(scope="session")
def april_result():
    from relay.pipeline import run_pipeline
    return run_pipeline(
        CAMPAIGN, "April", "White Plus",
        mainpage_path=WP_MAIN, subpage_path=WP_SUB, insta_path=WP_INSTA,
    )
