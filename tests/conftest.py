import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SAMPLES = ROOT

# The sample workbooks are the client's own files: sponsor campaign sheets and
# real Business Suite exports. They are
# git-ignored, and so are their *names* — a filename like
# "<sponsor> FB Photocard (April).xlsx" identifies the sponsor on its own.
#
# So the names live in `tests/samples_local.py`, which is git-ignored too. Copy
# `tests/samples_local.example.py` to `tests/samples_local.py` and fill in your
# own filenames to run the file-bound tests. Without it every path below points
# at something that does not exist, and those tests skip themselves — which is
# exactly what CI does.
try:
    from tests import samples_local as _local
except ImportError:                     # no local samples configured
    _local = None


def _sample(attr: str) -> Path:
    """A sample path from the local config, or a name that cannot exist."""
    return SAMPLES / getattr(_local, attr, f"__no_local_sample__{attr}")


def local_value(attr: str, default=None):
    """A workbook-specific expected value (a sheet tab name, a brand section
    key) that only makes sense against the local files."""
    return getattr(_local, attr, default)


CAMPAIGN = _sample("CAMPAIGN")
REPORT_APRIL = _sample("REPORT_APRIL")
# A real Business Suite content export. Like the workbooks above it holds live
# data, so tests that use it skip when it is absent — the synthetic fixtures in
# test_insights.py cover the same behaviour without it.
INSIGHTS_EXPORT = _sample("INSIGHTS_EXPORT")
# The Facebook export covering the same month as CAMPAIGN's April tab. Every
# figure in `april_result` comes from here, so it is what the acceptance tests
# measure against — the supervisor matched files it used to use are gone.
INSIGHTS_APRIL = _sample("INSIGHTS_APRIL")


def pytest_collection_modifyitems(config, items):
    """The sample workbooks hold real sponsor data and are git-ignored; when
    they're absent (e.g. CI), skip everything that depends on them."""
    if CAMPAIGN.exists():
        return
    skip = pytest.mark.skip(reason="local sample workbooks not present (excluded from git)")
    file_bound = {"test_ingest", "test_e2e", "test_web", "test_generator"}
    # Fixtures that open a sample workbook themselves, in modules whose other
    # tests are synthetic — skipping the whole module would cost real coverage,
    # so these are skipped per-test instead. `two_runs` posts CAMPAIGN to
    # /api/run, which is a 400 rather than a skip when the file is absent.
    file_bound_fixtures = {"april_result", "two_runs"}
    for item in items:
        mod = item.module.__name__.split(".")[-1]
        fixtures = set(getattr(item, "fixturenames", ()))
        if mod in file_bound or fixtures & file_bound_fixtures:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def april_campaign():
    from relay.ingest.campaign import parse_campaign
    rows, issues = parse_campaign(CAMPAIGN, "April")
    return rows, issues


@pytest.fixture(scope="session")
def april_result():
    from relay.pipeline import run_pipeline
    return run_pipeline(CAMPAIGN, "April", "Brand A",
                        insights_paths=[INSIGHTS_APRIL] if INSIGHTS_APRIL else None)
