"""SQLite persistence of runs for auditability (SRS FR-26)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .models import RunResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    brand TEXT NOT NULL,
    month TEXT NOT NULL,
    inputs TEXT NOT NULL,
    output_file TEXT,
    status TEXT NOT NULL DEFAULT 'matched'
);
CREATE TABLE IF NOT EXISTS cells (
    run_id INTEGER NOT NULL REFERENCES runs(id),
    row_no INTEGER NOT NULL,
    slot TEXT NOT NULL,
    link TEXT,
    value INTEGER,
    provenance TEXT NOT NULL,
    confidence REAL NOT NULL,
    note TEXT,
    PRIMARY KEY (run_id, row_no, slot)
);
CREATE TABLE IF NOT EXISTS overrides (
    run_id INTEGER NOT NULL REFERENCES runs(id),
    row_no INTEGER NOT NULL,
    slot TEXT NOT NULL,
    old_value INTEGER,
    new_value INTEGER,
    created_at TEXT NOT NULL
);
"""


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    return conn


def save_run(result: RunResult, inputs: dict, db_path: str | Path | None = None) -> int:
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO runs (created_at, brand, month, inputs) VALUES (?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), result.brand, result.month,
             json.dumps(inputs)),
        )
        run_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO cells VALUES (?,?,?,?,?,?,?,?)",
            [
                (run_id, r.no, slot, r.links.get(slot), c.value, c.provenance,
                 c.confidence, c.note)
                for r in result.rows for slot, c in r.cells.items()
            ],
        )
        return run_id


def record_override(run_id: int, row_no: int, slot: str, old, new,
                    db_path: str | Path | None = None) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO overrides VALUES (?,?,?,?,?,?)",
            (run_id, row_no, slot, old, new, datetime.now(timezone.utc).isoformat()),
        )
        conn.execute(
            "UPDATE cells SET value=?, provenance='manual', confidence=1.0 "
            "WHERE run_id=? AND row_no=? AND slot=?",
            (new, run_id, row_no, slot),
        )


def set_output(run_id: int, output_file: str, db_path: str | Path | None = None) -> None:
    with _connect(db_path) as conn:
        conn.execute("UPDATE runs SET output_file=?, status='generated' WHERE id=?",
                     (output_file, run_id))


def list_runs(db_path: str | Path | None = None) -> list[dict]:
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM runs ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]
