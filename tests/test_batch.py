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
