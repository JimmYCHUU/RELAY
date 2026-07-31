"""Phase 8 — multi-brand cycles: batch collection and zipped reports."""
import io
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from tests.conftest import CAMPAIGN



@pytest.fixture()
def client(tmp_path, monkeypatch):
    from relay import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "db" / "runs.db")
    from relay.web import app as webapp
    monkeypatch.setattr(webapp, "UPLOADS", tmp_path / "uploads")
    return TestClient(webapp.app)


@pytest.fixture()
def two_runs(client):
    ids = []
    for brand in ("Brand A", "Brand B"):
        res = client.post("/api/run", json={
            "campaign": str(CAMPAIGN), "sheet": "April", "brand": brand,
        })
        assert res.status_code == 200, res.text
        ids.append(res.json()["run_id"])
    return ids


def test_batch_collect_dry_run_covers_all_brands(client, two_runs):
    res = client.post("/api/collect/batch", json={
        "run_ids": two_runs, "target": "x", "dry_run": True})
    assert res.status_code == 200
    assert res.json()["runs"] == 2
    s = {"state": "running"}
    for _ in range(100):
        s = client.get(f"/api/collect/batch/x?ids={','.join(two_runs)}").json()
        if s["state"] in ("finished", "error", "stopped"):
            break
        time.sleep(0.1)
    assert s["state"] == "finished", s
    assert set(s["runs"]) == set(two_runs)
    assert "dry-run" in s["message"]


def test_batch_report_zip(client, two_runs):
    res = client.post("/api/report/batch", json={"run_ids": two_runs})
    assert res.status_code == 200
    data = res.json()
    assert len(data["workbooks"]) == 2
    dl = client.get(f"/api/report/batch/download/{data['name']}")
    assert dl.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(dl.content))
    assert sorted(zf.namelist()) == sorted(data["workbooks"])


def test_batch_download_rejects_bad_names(client):
    assert client.get("/api/report/batch/download/..%2Fx.zip").status_code in (400, 404)
    assert client.get("/api/report/batch/download/notzip.txt").status_code == 400


def test_batch_collect_unknown_run_is_404(client):
    res = client.post("/api/collect/batch", json={
        "run_ids": ["nope"], "target": "x", "dry_run": True})
    assert res.status_code == 404


def test_autopilot_dry_run_completes_campaigns_in_load_order(client, two_runs):
    res = client.post("/api/autopilot", json={"run_ids": two_runs, "dry_run": True})
    assert res.status_code == 200
    assert res.json()["campaigns"] == 2
    s = {"state": "running"}
    for _ in range(100):
        s = client.get(f"/api/autopilot/status?ids={','.join(two_runs)}").json()
        if s["state"] in ("finished", "error", "stopped"):
            break
        time.sleep(0.1)
    assert s["state"] == "finished", s
    assert set(s["runs"]) == set(two_runs)
    assert "autopilot done" in s["message"]
    # campaign-major order: all of brand 1's platform passes before brand 2's
    brands = [e.split(" · ")[0] for e in s["events"]]
    assert brands == ["Brand A"] * 3 + ["Brand B"] * 3
    # caption repair runs before Facebook — it fills cells that pass would
    # otherwise pay a browser visit each to reach
    # Facebook first: it identifies posts and refreshes stale captions, so the
    # later passes work from a row that already describes itself correctly.
    stages = [e.split(" · ")[1].split(":")[0] for e in s["events"][:3]]
    assert stages == ["Facebook", "Instagram", "X"]


def test_autopilot_checks_meta_session_upfront(client, two_runs, tmp_path, monkeypatch):
    from relay import config
    monkeypatch.setattr(config, "PROFILE_DIR", tmp_path / "no-profiles")
    res = client.post("/api/autopilot", json={"run_ids": two_runs})
    assert res.status_code == 412
    assert res.json()["detail"] == "meta-session-required"


def test_autopilot_unknown_run_is_404(client):
    res = client.post("/api/autopilot", json={"run_ids": ["nope"], "dry_run": True})
    assert res.status_code == 404


def test_autopilot_stop_when_idle(client):
    assert client.post("/api/autopilot/stop").json() == {"stopping": False}


# --- the pacing budget no longer needs a human to restart it ---
#
# `SESSION_NAV_BUDGET` is a counter on one Pacer, not a quota that refills on a
# clock: restarting by hand always handed the collector 200 more immediately, so
# the manual restart was never the safety measure. The pause is. Autopilot now
# takes the pause itself and carries on.

def _budget_then(halts: int, calls: list, halt: str = "budget"):
    """A collector that runs out of budget `halts` times, then finishes."""
    def fake(result, pacer=None, progress=None, persist=None, **kw):
        calls.append(result.brand)
        progress.filled = 1
        if len(calls) <= halts:
            progress.state, progress.halt = "stopped", halt
            progress.message = "session budget of 200 navigations reached"
        else:
            progress.state, progress.message = "finished", "done"
        return progress.filled
    return fake


@pytest.fixture()
def fast_cooldown(monkeypatch):
    from relay import config
    monkeypatch.setattr(config, "NAV_BUDGET_COOLDOWN_S", 0.05)
    monkeypatch.setattr(config, "NAV_BUDGET_MAX_LAPS", 2)


def _drain(client, ids, tries=200):
    for _ in range(tries):
        s = client.get(f"/api/autopilot/status?ids={','.join(ids)}").json()
        if s["state"] in ("finished", "error", "stopped"):
            return s
        time.sleep(0.05)
    return s


def test_autopilot_waits_out_the_budget_and_resumes_itself(
        client, two_runs, fast_cooldown, monkeypatch):
    from relay.collectors import runner
    calls = []
    monkeypatch.setattr(runner, "resolve_facebook", _budget_then(2, calls))
    monkeypatch.setattr(runner, "collect_instagram", _budget_then(0, []))
    monkeypatch.setattr(runner, "collect_x", _budget_then(0, []))

    client.post("/api/autopilot", json={"run_ids": two_runs[:1], "dry_run": True})
    s = _drain(client, two_runs[:1])

    assert s["state"] == "finished", s
    assert len(calls) == 3, "two budget halts, two cooldowns, then a clean finish"
    # 3 Facebook bursts + Instagram + X, each filling one. Counting only the
    # last burst of a resumed collector would report 3.
    assert "5 cells filled" in s["message"]
    assert any("carrying on by itself" in e for e in s["events"])


def test_autopilot_stops_dead_on_a_challenge_page(
        client, two_runs, fast_cooldown, monkeypatch):
    """A checkpoint page is the account asking to be left alone. Coming back on
    a timer is the exact behaviour it is watching for, so nothing resumes."""
    from relay.collectors import runner
    calls = []
    monkeypatch.setattr(runner, "resolve_facebook",
                        _budget_then(9, calls, halt="challenge"))
    monkeypatch.setattr(runner, "collect_instagram", _budget_then(0, []))
    monkeypatch.setattr(runner, "collect_x", _budget_then(0, []))

    client.post("/api/autopilot", json={"run_ids": two_runs[:1], "dry_run": True})
    s = _drain(client, two_runs[:1])

    assert s["state"] == "stopped", s
    assert len(calls) == 1, "no second burst after a challenge"


def test_autopilot_gives_up_after_its_last_allowed_burst(
        client, two_runs, fast_cooldown, monkeypatch):
    from relay.collectors import runner
    calls = []
    monkeypatch.setattr(runner, "resolve_facebook", _budget_then(99, calls))
    monkeypatch.setattr(runner, "collect_instagram", _budget_then(0, []))
    monkeypatch.setattr(runner, "collect_x", _budget_then(0, []))

    client.post("/api/autopilot", json={"run_ids": two_runs[:1], "dry_run": True})
    s = _drain(client, two_runs[:1])

    assert s["state"] == "stopped", s
    assert len(calls) == 3, "the first burst plus NAV_BUDGET_MAX_LAPS more"
    assert any("bursts used" in e for e in s["events"])
