"""Regression: hand-filled campaign sheets can repeat or blank the No column.

That must not crash persistence (it used to trip a UNIQUE constraint → 500),
and the delivered report must still carry a clean, unique No.
"""
import openpyxl

from relay import store
from relay.models import CellValue, ReportRow, RunResult
from relay.report.generator import build_report


def _dup_result() -> RunResult:
    def row(no, cap):
        return ReportRow(
            no=no, date=None, caption=cap,
            links={s: None for s in ("fb1", "fb2", "fb3", "x", "ig")},
            cells={s: CellValue.missing() for s in ("fb1", "fb2", "fb3", "x", "ig")},
        )
    # two rows share No 1 (a stray lead row auto-numbered onto a real No 1)
    return RunResult(brand="Cocola Food", month="June",
                     rows=[row(1, "Jusika"), row(1, "Match Schedule"), row(2, "KHELAR")])


def test_save_run_tolerates_duplicate_no(tmp_path):
    db = tmp_path / "runs.db"
    run_id = store.save_run(_dup_result(), {"sheet": "June"}, db_path=db)
    assert isinstance(run_id, int)


def test_legacy_unique_pk_db_migrates(tmp_path):
    """A DB created with the old PRIMARY KEY (run_id, row_no, slot) is rebuilt
    on connect, so save_run stops crashing on it."""
    db = tmp_path / "legacy.db"
    import sqlite3
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE runs (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT,"
        " brand TEXT, month TEXT, inputs TEXT, output_file TEXT, status TEXT, summary TEXT);"
        "CREATE TABLE cells (run_id INTEGER, row_no INTEGER, slot TEXT, link TEXT,"
        " value INTEGER, provenance TEXT, confidence REAL, note TEXT,"
        " PRIMARY KEY (run_id, row_no, slot));"
        "CREATE TABLE overrides (run_id INTEGER, row_no INTEGER, slot TEXT,"
        " old_value INTEGER, new_value INTEGER, created_at TEXT);"
        "INSERT INTO cells VALUES (1, 7, 'fb1', NULL, 5, 'matched', 1.0, '');"
    )
    conn.commit()
    conn.close()

    run_id = store.save_run(_dup_result(), {"sheet": "June"}, db_path=db)
    assert isinstance(run_id, int)
    # legacy history survives the rebuild
    with store._connect(db) as c:
        assert c.execute("SELECT value FROM cells WHERE row_no=7").fetchone()[0] == 5


def test_report_renumbers_to_unique_no(tmp_path):
    out = tmp_path / "report.xlsx"
    build_report(_dup_result(), out)
    wb = openpyxl.load_workbook(out)
    ws = wb.active
    nos = [ws.cell(row=3 + i, column=1).value for i in range(3)]
    wb.close()
    assert nos == [1, 2, 3]
