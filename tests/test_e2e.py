"""Acceptance gate (SRS AC-1): reproduce the real April Brand A report.

The reference is the analyst's hand-made workbook. RELAY now derives every
figure from Meta's own export instead of the supervisor's matched files, so
"reproduce" means something more exact than equality — two whole classes of
difference are expected, and both are RELAY being right rather than wrong:

* **Drift.** A figure the analyst read by hand keeps accruing views afterwards;
  the export was pulled later. The residual is small and one-directional, which
  is why `config.INSIGHTS_METRIC` settled on Views (see its comment).
* **FB2/FB3 exchanged.** The supervisor file listed a row's subpage values in
  whatever order its scraper found them and the hand-made report copied that
  order. RELAY puts each figure on the slot whose page actually earned it, so a
  row's two subpage values are sometimes the other way round from the reference.

Anything else is a real disagreement and fails.

Other ground-truth caveats, established with the analyst:
- X column excluded — reference values are fabricated.
- Cells the analyst recovered manually come back as `only-reference`: they are
  the cells RELAY routes to the post-id pass, not errors.
"""
from relay.report.crosscheck import compare, parse_reference
from tests.conftest import REPORT_APRIL

SLOTS = ("fb1", "fb2", "fb3", "ig")

# How far a figure may have moved between the analyst reading it and the export
# being pulled. Every drift diff across April sits well inside this.
DRIFT = 0.05

# Row 7's Link 3 is a share/p post. The analyst moved the subpage's single value
# to FB1 by hand and estimated FB3 as 16416; RELAY reports what the export
# attributes to that post. A judgment call, not a defect on either side.
KNOWN_DEVIATIONS = {(7, "fb3")}


def _near(a, b) -> bool:
    return a is not None and b not in (None, 0) and abs(a - b) / b <= DRIFT


def _classify(diff, by_row) -> str:
    if (diff.row_no, diff.slot) in KNOWN_DEVIATIONS:
        return "known deviation"
    if _near(diff.generated, diff.reference):
        return "drift"
    other = {"fb2": "fb3", "fb3": "fb2"}.get(diff.slot)
    twin = by_row.get(diff.row_no, {}).get(other) if other else None
    if twin is not None and _near(diff.generated, twin.reference):
        return "exchanged"
    return "UNEXPLAINED"


def test_e2e_against_april_ground_truth(april_result):
    reference = parse_reference(REPORT_APRIL, "April")
    assert len(reference) == 25
    cc = compare(april_result, reference)
    s = cc.summary(SLOTS)

    by_row: dict[int, dict] = {}
    for d in cc.diffs:
        by_row.setdefault(d.row_no, {})[d.slot] = d

    unexplained = [d for d in s["differs"] if _classify(d, by_row) == "UNEXPLAINED"]
    assert not unexplained, f"unexplained diffs: {unexplained}"

    # RELAY must never invent values the analyst didn't have.
    assert not s["only_generated"], s["only_generated"]

    # only-reference cells = manual recoveries; they must all be flagged missing
    for d in s["only_reference"]:
        row = next(r for r in april_result.rows if r.no == d.row_no)
        assert row.cells[d.slot].provenance == "missing"

    # sanity: the export actually resolved a usable share of the month
    filled = [d for d in cc.diffs if d.slot in SLOTS and d.generated is not None]
    assert len(filled) >= 40


def test_nothing_the_export_fills_is_a_guess(april_result):
    """Every value present after matching came from Meta's own file, exactly.
    Nothing is estimated any more, and nothing is inferred from a multiplier."""
    for row in april_result.rows:
        for slot in SLOTS:
            cell = row.cells[slot]
            if cell.value is not None:
                assert cell.provenance == "collected", (row.no, slot, cell)
                assert "insights export" in cell.note


def test_an_ambiguous_caption_leaves_the_cell_for_the_post_id_pass(april_result):
    """April row 9's story ran twice on two pages, twenty minutes apart, both
    copies carrying the same caption. Ranking them put a 678-view duplicate in
    the report where the live post had 6,519, so the caption join refuses the
    slot outright and says why — the post-id pass settles it exactly."""
    row = next(r for r in april_result.rows if r.no == 9)
    assert row.cells["fb2"].value is None and row.cells["fb3"].value is None
    reasons = [i.reason for i in april_result.issues if i.row == 9]
    assert any("same story twice" in r for r in reasons), reasons


def test_coverage_summary(april_result):
    cov = april_result.coverage()
    # The Facebook export alone accounts for most of the month's FB cells; what
    # it cannot reach is left to the post-id pass rather than estimated.
    assert cov["fb1"] >= 0.4
    assert cov["fb2"] >= 0.5
    # Instagram needs its own export, which this fixture does not supply.
    assert cov["ig"] == 0.0
