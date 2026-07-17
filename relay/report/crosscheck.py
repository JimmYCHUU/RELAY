"""Cross-check RELAY output against a reference report (SRS FR-23, SDD 5.7).

Also provides the reference-report parser (the hand-made monthly .xlsx),
reused by the E2E acceptance test.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

from ..matching.normalize import normalize_caption
from ..models import ReportRow, RunResult

# reference layout: No|Date|Name|L1|V|L2|V|L3|V|X|Imp|IG|V
_REF_SLOTS = {"fb1": (4, 5), "fb2": (6, 7), "fb3": (8, 9), "x": (10, 11), "ig": (12, 13)}


@dataclass
class RefRow:
    no: int
    caption: str
    links: dict[str, str | None]
    values: dict[str, int | None]


@dataclass
class CellDiff:
    row_no: int
    caption: str
    slot: str
    generated: int | None
    reference: int | None
    status: str  # equal | differs | only-generated | only-reference | both-empty


@dataclass
class CrossCheck:
    diffs: list[CellDiff] = field(default_factory=list)

    def summary(self, slots: tuple[str, ...] = ("fb1", "fb2", "fb3", "ig")) -> dict:
        scored = [d for d in self.diffs if d.slot in slots and d.status != "both-empty"]
        equal = [d for d in scored if d.status == "equal"]
        return {
            "cells": len(scored),
            "equal": len(equal),
            "accuracy": round(len(equal) / len(scored), 4) if scored else 1.0,
            "differs": [d for d in scored if d.status == "differs"],
            "only_generated": [d for d in scored if d.status == "only-generated"],
            "only_reference": [d for d in scored if d.status == "only-reference"],
        }


def parse_reference(path: str | Path, sheet: str) -> list[RefRow]:
    wb = openpyxl.load_workbook(path, data_only=True)
    try:
        ws = wb[sheet]
        rows: list[RefRow] = []
        for row in ws.iter_rows(min_row=3, max_col=13, values_only=True):
            no, caption = row[0], row[2]
            if isinstance(no, str) or no is None:   # footer rows ('Sum', ...) or blanks
                if isinstance(no, str) and no.strip().lower() in ("sum", "total views"):
                    break
                if caption is None:
                    continue
            if caption is None:
                continue
            links, values = {}, {}
            for slot, (lc, vc) in _REF_SLOTS.items():
                links[slot] = row[lc - 1]
                v = row[vc - 1]
                values[slot] = int(v) if isinstance(v, (int, float)) else None
            rows.append(RefRow(int(no) if no else len(rows) + 1, str(caption), links, values))
        return rows
    finally:
        wb.close()


def compare(result: RunResult, reference: list[RefRow]) -> CrossCheck:
    ref_by_key = {normalize_caption(r.caption): r for r in reference}
    cc = CrossCheck()
    for row in result.rows:
        ref = ref_by_key.get(normalize_caption(row.caption))
        for slot in _REF_SLOTS:
            gen = row.cells[slot].value
            refv = ref.values[slot] if ref else None
            if gen is None and refv is None:
                status = "both-empty"
            elif gen is None:
                status = "only-reference"
            elif refv is None:
                status = "only-generated"
            else:
                status = "equal" if gen == refv else "differs"
            cc.diffs.append(CellDiff(row.no, row.caption, slot, gen, refv, status))
    return cc
