"""Checkpoint/resume: per-cell persistence, hydration, and browser recycling."""
import sqlite3
from contextlib import contextmanager

from relay import store
from relay.models import SLOTS, CellValue, ReportRow, RunResult


def make_result(n=3):
    rows = []
    for i in range(n):
        links = {"fb1": f"https://facebook.com/p/{i}", "fb2": None, "fb3": None,
                 "x": f"https://x.com/somoytv/status/{100 + i}", "ig": None}
        cells = {s: CellValue.missing("not matched") for s in SLOTS}
        rows.append(ReportRow(no=i + 1, date=None, caption=f"post {i}",
                              links=links, cells=cells))
    return RunResult(brand="Brand C", month="April", rows=rows)


def test_update_cell_and_load_cells_roundtrip(tmp_path):
    db = tmp_path / "runs.db"
    inputs = {"campaign": "ab12cd34_Brand C.xlsx", "sheet": "April", "brand": "Brand C"}
    run_id = store.save_run(make_result(), inputs, db_path=db)
    store.update_cell(run_id, 0, "fb1", CellValue(123, "collected", 1.0, "mbs"), db_path=db)
    store.update_cell(run_id, 2, "x", CellValue(456, "estimated", 0.6, "k=95"), db_path=db)
    got = {(c["row_idx"], c["slot"]): c["value"] for c in store.load_cells(run_id, db_path=db)}
    assert got == {(0, "fb1"): 123, (2, "x"): 456}  # missing cells excluded


def test_find_resumable_run_matches_reuploaded_file(tmp_path):
    """Uploads get a fresh random prefix each session — the same sheet
    re-uploaded after a PC restart must still find its previous run."""
    db = tmp_path / "runs.db"
    store.save_run(make_result(), {"campaign": "11111111_Brand C.xlsx",
                                   "sheet": "April", "brand": "Brand C"}, db_path=db)
    b = store.save_run(make_result(), {"campaign": "22222222_Brand C.xlsx",
                                       "sheet": "April", "brand": "Brand C"}, db_path=db)
    store.save_run(make_result(), {"campaign": "33333333_White.xlsx",
                                   "sheet": "April", "brand": "Brand A"}, db_path=db)
    assert store.find_resumable_run(
        {"campaign": "/data/uploads/99999999_Brand C.xlsx",
         "sheet": "April", "brand": "Brand C"}, db_path=db) == b
    assert store.find_resumable_run(
        {"campaign": "deadbeef_Other.xlsx", "sheet": "April", "brand": "Nope"},
        db_path=db) is None


def test_hydrate_cells_restores_and_guards(tmp_path):
    db = tmp_path / "runs.db"
    run_id = store.save_run(make_result(), {"campaign": "c.xlsx", "sheet": "April",
                                            "brand": "Brand C"}, db_path=db)
    store.update_cell(run_id, 0, "fb1", CellValue(123, "collected", 1.0, "mbs"), db_path=db)
    store.update_cell(run_id, 1, "x", CellValue(456, "collected", 1.0, "x"), db_path=db)
    fresh = make_result()
    fresh.rows[1].links["x"] = "https://x.com/other/status/999"  # sheet edited
    restored = store.hydrate_cells(fresh, store.load_cells(run_id, db_path=db))
    assert restored == 1
    assert fresh.rows[0].cells["fb1"].value == 123
    assert fresh.rows[0].cells["fb1"].provenance == "collected"
    assert fresh.rows[1].cells["x"].value is None  # link changed -> re-collect


def test_legacy_db_gains_row_idx(tmp_path):
    """Pre-checkpoint databases have no row_idx column; opening them must
    migrate cleanly, and their NULL-row_idx cells must never hydrate."""
    db = tmp_path / "runs.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
CREATE TABLE runs (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
    brand TEXT NOT NULL, month TEXT NOT NULL, inputs TEXT NOT NULL,
    output_file TEXT, status TEXT NOT NULL DEFAULT 'matched');
CREATE TABLE cells (run_id INTEGER NOT NULL, row_no INTEGER, slot TEXT NOT NULL,
    link TEXT, value INTEGER, provenance TEXT NOT NULL, confidence REAL NOT NULL,
    note TEXT);
INSERT INTO runs (created_at, brand, month, inputs) VALUES ('t','Brand C','April','{}');
INSERT INTO cells VALUES (1, 1, 'fb1', 'https://f', 5, 'collected', 1.0, '');
""")
    conn.commit()
    conn.close()
    assert store.load_cells(1, db_path=db) == []  # legacy rows: row_idx IS NULL
    run_id = store.save_run(make_result(), {"campaign": "c.xlsx", "sheet": "April",
                                            "brand": "Brand C"}, db_path=db)
    store.update_cell(run_id, 0, "x", CellValue(9, "collected", 1.0, ""), db_path=db)
    assert store.load_cells(run_id, db_path=db)[0]["value"] == 9


def _fake_x(monkeypatch, views=111):
    import relay.collectors.browser as browser
    import relay.collectors.xpublic as xpublic

    class FakeSession:
        def page(self):
            return object()

    @contextmanager
    def fake_session(recycle_every=None):
        yield FakeSession()

    monkeypatch.setattr(browser, "anonymous_session", fake_session)
    monkeypatch.setattr(xpublic, "collect_x_views",
                        lambda page, url, pacer: CellValue(views, "collected", 1.0, "t"))


def test_collect_x_checkpoints_and_resumes(monkeypatch):
    from relay.collectors.base import Pacer
    from relay.collectors.runner import collect_x

    _fake_x(monkeypatch)
    pacer = Pacer()
    pacer._sleep = lambda s: None
    result = make_result()
    calls = []
    filled = collect_x(result, pacer=pacer,
                       persist=lambda run, idx, slot, cell: calls.append((idx, slot, cell.value)))
    assert filled == 3
    assert calls == [(0, "x", 111), (1, "x", 111), (2, "x", 111)]
    # a second pass has nothing left to do — filled cells are skipped
    calls.clear()
    assert collect_x(result, pacer=pacer,
                     persist=lambda *a: calls.append(a)) == 0
    assert calls == []


def test_checkpoint_failure_never_aborts_collection(monkeypatch):
    from relay.collectors.base import Pacer
    from relay.collectors.runner import collect_x

    _fake_x(monkeypatch)
    pacer = Pacer()
    pacer._sleep = lambda s: None
    result = make_result()

    def broken_persist(run, idx, slot, cell):
        raise RuntimeError("db locked")

    assert collect_x(result, pacer=pacer, persist=broken_persist) == 3
    assert all(r.cells["x"].value == 111 for r in result.rows)


def test_meta_session_recycles(monkeypatch, tmp_path):
    import relay.collectors.browser as browser

    class FakePage:
        def route(self, *a, **k):
            pass

    class FakeCtx:
        def __init__(self):
            self.pages = [FakePage()]
            self.closed = False

        def new_page(self):
            return FakePage()

        def close(self):
            self.closed = True

    launched = []

    class FakeChromium:
        def launch_persistent_context(self, **kw):
            ctx = FakeCtx()
            launched.append(ctx)
            return ctx

    class FakePW:
        chromium = FakeChromium()

    monkeypatch.setattr(browser, "_executable", lambda: None)
    sess = browser.MetaSession(FakePW(), str(tmp_path), headed=False, recycle_every=2)
    a = sess.page()
    b = sess.page()
    assert a is b and len(launched) == 1
    sess.page()  # third visit crosses the threshold -> recycle
    assert len(launched) == 2 and launched[0].closed and not launched[1].closed
    sess.close()
    assert launched[1].closed


def test_anonymous_session_recycles_too(monkeypatch):
    """X is the collector with the most visits to make in a cycle — 427 against
    Facebook's 150 in a real July — and it was the one holding a single page
    open for all of them."""
    import relay.collectors.browser as browser

    class FakePage:
        def route(self, *a, **k):
            pass

    class FakeBrowser:
        def __init__(self):
            self.closed = False

        def new_page(self, **kw):
            return FakePage()

        def close(self):
            self.closed = True

    launched = []

    class FakeChromium:
        def launch(self, **kw):
            b = FakeBrowser()
            launched.append(b)
            return b

    class FakePW:
        chromium = FakeChromium()

    monkeypatch.setattr(browser, "_executable", lambda: None)
    sess = browser.AnonymousSession(FakePW(), headed=False, recycle_every=2)
    a = sess.page()
    assert sess.page() is a and len(launched) == 1
    sess.page()                       # third visit crosses the threshold
    assert len(launched) == 2 and launched[0].closed and not launched[1].closed
    sess.close()
    assert launched[1].closed


def test_collect_x_asks_the_session_for_a_page_every_visit(monkeypatch):
    """Recycling only happens if the collector re-asks — holding one page in a
    local variable is exactly the bug this replaced."""
    from relay.collectors.base import Pacer
    from relay.collectors.runner import collect_x
    import relay.collectors.browser as browser
    import relay.collectors.xpublic as xpublic

    asked = []

    class FakeSession:
        def page(self):
            asked.append(1)
            return object()

    @contextmanager
    def fake_session(recycle_every=None):
        yield FakeSession()

    monkeypatch.setattr(browser, "anonymous_session", fake_session)
    monkeypatch.setattr(xpublic, "collect_x_views",
                        lambda page, url, pacer: CellValue(5, "collected", 1.0, "t"))
    pacer = Pacer()
    pacer._sleep = lambda s: None
    collect_x(make_result(3), pacer=pacer)
    assert len(asked) == 3, "one page request per post, not one for the batch"


def test_override_preserves_a_dashboard_estimate_s_provenance(tmp_path):
    """record_override used to hardcode provenance='manual', confidence=1.0,
    so a dashboard *estimate* came back from a resume looking hand-entered —
    losing its ≈ marking and claiming full confidence it never had."""
    db = tmp_path / "runs.db"
    inputs = {"campaign": "c.xlsx", "sheet": "April", "brand": "Brand C"}
    run_id = store.save_run(make_result(), inputs, db_path=db)

    est = CellValue(77137, "estimated", 0.5, "reactions=812, k=95 (pinned)")
    store.record_override(run_id, 1, "fb1", None, est.value, db_path=db, cell=est)

    with sqlite3.connect(db) as conn:
        got = conn.execute(
            "SELECT value, provenance, confidence, note FROM cells "
            "WHERE run_id=? AND row_no=? AND slot='fb1'", (run_id, 1)).fetchone()
    assert got == (77137, "estimated", 0.5, "reactions=812, k=95 (pinned)")


def test_override_without_a_cell_still_records_a_manual_entry(tmp_path):
    db = tmp_path / "runs.db"
    inputs = {"campaign": "c.xlsx", "sheet": "April", "brand": "Brand C"}
    run_id = store.save_run(make_result(), inputs, db_path=db)
    store.record_override(run_id, 1, "fb1", None, 500, db_path=db)
    with sqlite3.connect(db) as conn:
        got = conn.execute(
            "SELECT value, provenance, confidence FROM cells "
            "WHERE run_id=? AND row_no=? AND slot='fb1'", (run_id, 1)).fetchone()
    assert got == (500, "manual", 1.0)
