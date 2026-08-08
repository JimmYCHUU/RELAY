"""SQLite persistence of runs for auditability (SRS FR-26)."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .models import LINK_REMOVED_NOTE, CellValue, RunResult

# row_no is intentionally NOT unique: campaign sheets are hand-filled, so No
# can repeat or be blank. Row identity for the audit log is positional, not the
# human No — the report generator is what guarantees a unique No in the output.
# row_idx is that positional identity (enumerate order), the key the collector
# checkpoints and the resume path use.
_CELLS_COLUMNS = "run_id, row_no, slot, link, value, provenance, confidence, note"
_CELLS_DDL = """
CREATE TABLE IF NOT EXISTS cells (
    run_id INTEGER NOT NULL REFERENCES runs(id),
    row_no INTEGER,
    slot TEXT NOT NULL,
    link TEXT,
    value INTEGER,
    provenance TEXT NOT NULL,
    confidence REAL NOT NULL,
    note TEXT,
    row_idx INTEGER,
    reach INTEGER,
    engagement INTEGER,
    removed_link TEXT,
    clicks INTEGER
);
CREATE INDEX IF NOT EXISTS ix_cells_key ON cells (run_id, row_no, slot);
"""

# Columns added after the table shipped; each is ALTERed in on an existing DB.
_CELLS_ADDED = (
    ("row_idx", "INTEGER"),
    # Reach and engagement ride along with the headline figure. Without them a
    # resume, or a hand-typed pair, came back as a bare view count and the
    # report's Reach / Engagement columns silently emptied themselves.
    ("reach", "INTEGER"),
    ("engagement", "INTEGER"),
    # The URL a person struck off this slot by hand because the post is gone
    # from the platform. Kept rather than merely blanked so the removal can be
    # re-applied to a fresh run of the same sheet — which still lists the link.
    ("removed_link", "TEXT"),
    ("clicks", "INTEGER"),
)

# The companion figures, in one place: every statement below writes or reads all
# of them, and a column added to `cells` but forgotten in one of those five
# statements is exactly how a figure survives a collection and then vanishes on
# resume. Order is the order the SQL and its parameters both use.
_COMPANIONS = ("reach", "engagement", "clicks")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    brand TEXT NOT NULL,
    month TEXT NOT NULL,
    inputs TEXT NOT NULL,
    output_file TEXT,
    status TEXT NOT NULL DEFAULT 'matched',
    summary TEXT
);
""" + _CELLS_DDL + """
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
    # WAL keeps the per-target checkpoint writes from blocking dashboard reads
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    try:  # migrate databases created before the summary column existed
        conn.execute("ALTER TABLE runs ADD COLUMN summary TEXT")
    except sqlite3.OperationalError:
        pass
    for name, sqltype in _CELLS_ADDED:
        try:  # migrate a database created before this column existed
            conn.execute(f"ALTER TABLE cells ADD COLUMN {name} {sqltype}")
        except sqlite3.OperationalError:
            pass
    _migrate_cells(conn)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_cells_pos ON cells (run_id, row_idx, slot)")
    return conn


def _migrate_cells(conn: sqlite3.Connection) -> None:
    """Older DBs keyed cells on PRIMARY KEY (run_id, row_no, slot), which
    assumes a unique No per row. A repeated or blank No then crashed save_run
    with an IntegrityError. Rebuild the table without the constraint, preserving
    history (legacy rows had unique No, so they copy over cleanly)."""
    info = conn.execute("PRAGMA table_info(cells)").fetchall()
    if not (info and any(col[5] for col in info)):  # col[5] = pk flag
        return
    conn.executescript(
        "DROP INDEX IF EXISTS ix_cells_key;\n"
        "ALTER TABLE cells RENAME TO cells_legacy;\n"
        + _CELLS_DDL
        + f"INSERT INTO cells ({_CELLS_COLUMNS}) "
          f"SELECT {_CELLS_COLUMNS} FROM cells_legacy;\n"
        "DROP TABLE cells_legacy;\n"
    )


def _summarize(result: RunResult) -> str:
    cells = [c for r in result.rows for slot, c in r.cells.items() if r.links.get(slot)]
    missing = sum(1 for c in cells if c.value is None)
    estimated = sum(1 for c in cells if c.provenance == "estimated")
    parts = [f"{len(result.rows)} rows"]
    parts.append(f"{missing} cells flagged for review" if missing else "all cells resolved")
    if estimated:
        parts.append(f"{estimated} estimated (≈)")
    return " · ".join(parts)


def save_run(result: RunResult, inputs: dict, db_path: str | Path | None = None) -> int:
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO runs (created_at, brand, month, inputs, summary) VALUES (?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), result.brand, result.month,
             json.dumps(inputs), _summarize(result)),
        )
        run_id = cur.lastrowid
        cols = f"{_CELLS_COLUMNS}, row_idx, " + ", ".join(_COMPANIONS)
        conn.executemany(
            f"INSERT INTO cells ({cols}) "
            f"VALUES ({','.join('?' * (cols.count(',') + 1))})",
            [
                (run_id, r.no, slot, r.links.get(slot), c.value, c.provenance,
                 c.confidence, c.note, idx,
                 *(getattr(c, name) for name in _COMPANIONS))
                for idx, r in enumerate(result.rows) for slot, c in r.cells.items()
            ],
        )
        return run_id


def update_cell(run_id: int, row_idx: int, slot: str, cell: CellValue,
                db_path: str | Path | None = None) -> None:
    """Checkpoint one collected cell so a crash mid-collection loses nothing."""
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE cells SET value=?, provenance=?, confidence=?, note=?, "
            + ", ".join(f"{name}=?" for name in _COMPANIONS)
            + " WHERE run_id=? AND row_idx=? AND slot=?",
            (cell.value, cell.provenance, cell.confidence, cell.note,
             *(getattr(cell, name) for name in _COMPANIONS),
             run_id, row_idx, slot),
        )


def load_cells(run_id: int, db_path: str | Path | None = None) -> list[dict]:
    """Cells worth restoring into a fresh run of the same inputs — anything a
    collector or the user filled in, keyed by position."""
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT row_idx, slot, link, value, provenance, confidence, note, "
            + ", ".join(_COMPANIONS) +
            " FROM cells WHERE run_id=? AND row_idx IS NOT NULL "
            "AND value IS NOT NULL "
            "AND provenance IN ('collected','estimated','manual')",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def hydrate_cells(result: RunResult, cells: list[dict]) -> int:
    """Restore previously collected values into a freshly matched RunResult.
    Only cells whose position AND link still agree are restored — an edited
    sheet shifts rows, and a mismatched link means 're-collect'. Cells the
    matcher already filled are left alone. Returns the number restored."""
    restored = 0
    for c in cells:
        idx = c["row_idx"]
        if idx is None or idx >= len(result.rows):
            continue
        row = result.rows[idx]
        slot = c["slot"]
        if slot not in row.cells or row.links.get(slot) != c["link"]:
            continue
        if row.cells[slot].value is not None:
            continue
        row.cells[slot] = CellValue(c["value"], c["provenance"],
                                    c["confidence"], c["note"],
                                    **{n: c.get(n) for n in _COMPANIONS})
        restored += 1
    return restored


def load_removed_links(run_id: int, db_path: str | Path | None = None) -> list[dict]:
    """Links a person struck off this run by hand, with the URL each replaced."""
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT row_idx, slot, removed_link FROM cells "
            "WHERE run_id=? AND row_idx IS NOT NULL AND removed_link IS NOT NULL",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def apply_removed_links(result: RunResult, removals: list[dict]) -> int:
    """Re-strike links a person already removed once, on a fresh run.

    The campaign sheet still lists the post — that is the whole point of the
    feature, that nobody went back and deleted the link — so a re-run puts it
    straight back and the cell goes back to reading as outstanding work. Only a
    slot whose link is still character-for-character the one that was struck is
    re-struck: a changed link is a different post and deserves its own look.
    """
    removed = 0
    for r in removals:
        idx = r["row_idx"]
        if idx is None or idx >= len(result.rows):
            continue
        row = result.rows[idx]
        slot = r["slot"]
        if slot not in row.cells or row.links.get(slot) != r["removed_link"]:
            continue
        row.links[slot] = None
        row.cells[slot] = CellValue.missing(LINK_REMOVED_NOTE)
        removed += 1
    return removed


def _run_key(inputs: dict) -> tuple:
    """Identity of a run for resume purposes. Uploads are stored under a random
    per-upload prefix ('a1b2c3d4_campaign.xlsx'), so a re-uploaded sheet gets a
    new path — compare the original filename instead."""
    name = Path(inputs.get("campaign") or "").name
    m = re.match(r"^[0-9a-f]{8}_(.+)$", name)
    if m:
        name = m.group(1)
    return (name, inputs.get("sheet"), inputs.get("brand"))


def find_resumable_run(inputs: dict, db_path: str | Path | None = None) -> int | None:
    """Most recent run created from the same campaign file/sheet/brand — the
    previous attempt whose collected values a new run can inherit."""
    key = _run_key(inputs)
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT id, inputs FROM runs ORDER BY id DESC").fetchall()
    for rid, blob in rows:
        try:
            prev = json.loads(blob)
        except ValueError:
            continue
        if _run_key(prev) == key:
            return rid
    return None


def record_override(run_id: int, row_no: int, slot: str, old, new,
                    db_path: str | Path | None = None,
                    cell: CellValue | None = None,
                    row_idx: int | None = None) -> None:
    """Log a dashboard edit and write the new value through.

    `cell` carries the value's real provenance, and now its reach, engagement
    and clicks. Without it this defaulted to 'manual'/1.0, which silently
    relabelled dashboard *estimates* as hand-entered values — they then came
    back from a resume without their ≈ marking and with false confidence.

    `row_idx` addresses the row by position. A campaign sheet's No is
    hand-filled and can repeat, so keying the write on it wrote one person's
    typed figure into every row that happens to share that number. Callers that
    know the position pass it; the row_no fallback is what the CLI and the older
    tests use, where No is unique.
    """
    provenance = cell.provenance if cell is not None else "manual"
    confidence = cell.confidence if cell is not None else 1.0
    note = cell.note if cell is not None else "manual entry"
    companions = tuple(getattr(cell, n) if cell is not None else None
                       for n in _COMPANIONS)
    where, key = ("row_idx", row_idx) if row_idx is not None else ("row_no", row_no)
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO overrides VALUES (?,?,?,?,?,?)",
            (run_id, row_no, slot, old, new, datetime.now(timezone.utc).isoformat()),
        )
        conn.execute(
            "UPDATE cells SET value=?, provenance=?, confidence=?, note=?, "
            + ", ".join(f"{n}=?" for n in _COMPANIONS)
            + f" WHERE run_id=? AND {where}=? AND slot=?",
            (new, provenance, confidence, note, *companions, run_id, key, slot),
        )


def record_link_removal(run_id: int, row_no: int, slot: str, url: str,
                        old_value: int | None = None, row_idx: int | None = None,
                        db_path: str | Path | None = None) -> None:
    """Log that a link was struck off by hand and blank the cell behind it.

    The URL is kept in `removed_link` rather than thrown away: the campaign
    sheet still carries it, so a re-run of the same sheet would hand the cell
    straight back unless the removal can be recognised and re-applied.
    """
    where, key = ("row_idx", row_idx) if row_idx is not None else ("row_no", row_no)
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO overrides VALUES (?,?,?,?,?,?)",
            (run_id, row_no, slot, old_value, None,
             datetime.now(timezone.utc).isoformat()),
        )
        conn.execute(
            "UPDATE cells SET link=NULL, value=NULL, "
            + "".join(f"{n}=NULL, " for n in _COMPANIONS)
            + "provenance='missing', confidence=0.0, note=?, removed_link=? "
            f"WHERE run_id=? AND {where}=? AND slot=?",
            (LINK_REMOVED_NOTE, url, run_id, key, slot),
        )


def set_output(run_id: int, output_file: str, db_path: str | Path | None = None) -> None:
    with _connect(db_path) as conn:
        conn.execute("UPDATE runs SET output_file=?, status='generated' WHERE id=?",
                     (output_file, run_id))


def discard_run(run_id: int, db_path: str | Path | None = None) -> None:
    """Mark a run the user threw out of the cycle — the wrong sheet, usually.

    The row and its cells stay: this table is the audit log, and "a run was
    started and abandoned" is part of the history. Only the status changes, so
    the activity feed stops presenting it as work in hand.
    """
    with _connect(db_path) as conn:
        conn.execute("UPDATE runs SET status='discarded' WHERE id=?", (run_id,))


def list_runs(db_path: str | Path | None = None) -> list[dict]:
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM runs ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]
