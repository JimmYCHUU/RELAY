"""Acceptance gate (SRS AC-1): reproduce the real April White Plus report.

Ground-truth caveats, established with the analyst:
- X column excluded — reference values are fabricated.
- Cells the analyst recovered manually (empty in the supervisor files) come back
  as `only-reference`: they are NOT errors, they are exactly the cells RELAY
  routes to heuristic/collector recovery.
- FB3 rule (highest of remaining subpage values) may deviate from the analyst's
  in-order manual pick; deviations must be surfaced, not hidden.
"""
from relay.report.crosscheck import compare, parse_reference
from tests.conftest import REPORT_APRIL

SLOTS = ("fb1", "fb2", "fb3", "ig")

# Cells where the analyst's April judgment call deviated from their stated
# rules; RELAY flags these for review (low confidence / discard note) rather
# than silently matching the manual pick.
#   (7, fb3): Link 3 is a share/p post. The subpage file's single value 195953
#   was manually moved to FB1 by the analyst and FB3 estimated as 16416; RELAY
#   assigns the value to its rule slot and marks it "shared-post slot — verify".
KNOWN_DEVIATIONS = {(7, "fb3")}


def test_e2e_against_april_ground_truth(april_result):
    reference = parse_reference(REPORT_APRIL, "April")
    assert len(reference) == 25
    cc = compare(april_result, reference)
    s = cc.summary(SLOTS)

    # Every cell RELAY fills must equal the hand-made report, except documented
    # rule deviations (FB3-highest vs manual in-order pick).
    unexplained = [
        d for d in s["differs"]
        if (d.row_no, d.slot) not in KNOWN_DEVIATIONS
        and not (d.slot == "fb3" and _is_rule_deviation(april_result, d))
    ]
    assert not unexplained, f"unexplained diffs: {unexplained}"

    # RELAY must never invent values the analyst didn't have.
    assert not s["only_generated"], s["only_generated"]

    # only-reference cells = manual recoveries; they must all be flagged missing
    for d in s["only_reference"]:
        row = next(r for r in april_result.rows if r.no == d.row_no)
        assert row.cells[d.slot].provenance == "missing"

    # Accuracy over the cells RELAY resolves: everything it fills is right.
    filled = [d for d in cc.diffs if d.slot in SLOTS and d.generated is not None]
    correct = [d for d in filled if d.status == "equal"
               or (d.row_no, d.slot) in KNOWN_DEVIATIONS
               or (d.slot == "fb3" and _is_rule_deviation(april_result, d))]
    assert len(filled) >= 70  # sanity: the pipeline actually resolved the month
    assert len(correct) == len(filled)


def _is_rule_deviation(result, diff) -> bool:
    """True when RELAY picked the highest remaining subpage value while the
    analyst picked an in-order value that is also among the candidates."""
    row = next(r for r in result.rows if r.no == diff.row_no)
    note = row.cells["fb3"].note
    return "discarded" in note and str(diff.reference) in note


def test_match_quality(april_result):
    tiers = april_result.match_tiers
    strong = {"exact", "prefix", "fuzzy", "n/a"}
    weak = [
        (no, src, t) for no, m in tiers.items() for src, t in m.items()
        if t not in strong and t != "none"
    ]
    assert not weak, f"low-confidence matches need review: {weak}"


def test_coverage_summary(april_result):
    cov = april_result.coverage()
    # supervisor files resolve most FB1 and nearly all FB2/FB3/IG linked slots
    assert cov["ig"] >= 0.9
    assert cov["fb2"] >= 0.9
    # The supervisor's mainpage file resolves only ~half of FB1 (13/25 empty in
    # April); the rest are exactly the manual-recovery cells RELAY flags.
    assert cov["fb1"] >= 0.45
