"""Fold several tabs of one brand's campaign workbook into a single report.

A sponsor's workbook is one campaign kept in several tabs — Ruchi's June runs as
`June`, `June ratio 2` and `8 Teams Special` — and the sponsor is handed one
file, not three. Matching still runs per tab (each has its own header row, its
own blank-date repair and its own brand colour to read), so this joins the
finished runs rather than the sheets: one continuous table, renumbered end to
end, with a `Source tab` column recording where each row came from.

Only tabs of the same brand ever merge. Two brands in one cycle stay two
workbooks — the rule that a sponsor never sees another sponsor's numbers is
older than this module and is not relaxed by it.
"""
from __future__ import annotations

from dataclasses import replace

from ..models import RunResult


def merge_runs(results: list[RunResult], label: str | None = None) -> RunResult:
    """One RunResult carrying every row of `results`, in the given order.

    Rows are copied, not moved: the source runs stay intact and keep serving the
    review screen, the collectors and the resume checkpoints, all of which are
    keyed per tab. Regenerating a merged report therefore never mutates what the
    dashboard is showing.
    """
    if not results:
        raise ValueError("nothing to merge")
    if len(results) == 1 and not label:
        return results[0]

    first = results[0]
    # A one-tab group has nothing to disambiguate, so it gets no Source column
    # even when it was named — the label already says what the file is.
    stamp = len(results) > 1
    rows = [replace(row, source_sheet=res.month if stamp else row.source_sheet)
            for res in results for row in res.rows]

    # A per-cell note carries the position of the row it is about, and the merged
    # table renumbers every row after the first tab's. Shifting each note by its
    # tab's offset keeps it pointing at its own cell rather than at whatever row
    # now sits at that index.
    issues, offset = [], 0
    for res in results:
        issues += [i if i.row_idx is None else replace(i, row_idx=i.row_idx + offset)
                   for i in res.issues]
        offset += len(res.rows)

    merged = RunResult(
        brand=first.brand,
        month=label or first.month,
        rows=rows,
        issues=issues,
        # The tabs of one workbook are one campaign wearing one brand colour;
        # where a later tab was left unbranded, the first one that carries a
        # colour speaks for the file.
        accent=next((r.accent for r in results if r.accent), None),
        # Every tab was matched against the same exports, so any of the indexes
        # answers a "where did this figure come from" lookup identically.
        insights=first.insights,
    )
    return merged
