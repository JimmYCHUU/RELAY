import openpyxl
import pytest
from fastapi.testclient import TestClient

from tests.conftest import CAMPAIGN, REPORT_APRIL, WP_INSTA, WP_MAIN, WP_SUB


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
def run_id(client):
    res = client.post("/api/run", json={
        "campaign": str(CAMPAIGN), "sheet": "April", "brand": "Brand A",
        "mainpage": str(WP_MAIN), "subpage": str(WP_SUB), "insta": str(WP_INSTA),
    })
    assert res.status_code == 200, res.text
    return res.json()


def test_upload_campaign_lists_sheets(client):
    with open(CAMPAIGN, "rb") as fh:
        res = client.post("/api/upload", data={"kind": "campaign"},
                          files={"file": ("campaign.xlsx", fh)})
    assert res.status_code == 200
    assert "April" in res.json()["sheets"]


def test_run_payload(run_id):
    data = run_id
    assert len(data["rows"]) == 25
    row2 = data["rows"][1]
    assert row2["cells"]["fb1"]["value"] == 161332
    assert row2["cells"]["fb1"]["provenance"] == "matched"
    assert data["coverage"]["fb2"] == 1.0


def test_estimate_and_override(client, run_id):
    rid = run_id["run_id"]
    # row 1 fb1 is the shared post — estimate it
    res = client.post("/api/estimate", json={
        "run_id": rid, "row_no": 1, "slot": "fb1", "reactions": 812, "k": 95})
    assert res.status_code == 200
    body = res.json()
    # 812 × 95 = 77140, then the last digit is nudged onto 1/3/7/9
    assert abs(body["value"] - 77140) < 10 and body["value"] % 10 in (1, 3, 7, 9)
    assert body["provenance"] == "estimated" and body["confidence"] == 0.5
    assert body["note"] == "reactions=812, k=95 (pinned)"
    # omitting k entirely randomizes it within [70, 120]
    res2 = client.post("/api/estimate", json={
        "run_id": rid, "row_no": 1, "slot": "fb1", "reactions": 812})
    assert res2.status_code == 200
    v2 = res2.json()["value"]
    assert 812 * 70 <= v2 <= 812 * 120 + 9 and v2 % 10 in (1, 3, 7, 9)
    # k out of bounds rejected
    bad = client.post("/api/estimate", json={
        "run_id": rid, "row_no": 1, "slot": "fb1", "reactions": 10, "k": 50})
    assert bad.status_code == 422
    # manual override
    res = client.post("/api/override", json={
        "run_id": rid, "row_no": 1, "slot": "fb1", "value": 76436})
    assert res.status_code == 200
    assert res.json()["provenance"] == "manual"


def test_generate_and_download(client, run_id, tmp_path):
    rid = run_id["run_id"]
    res = client.post(f"/api/report/{rid}")
    assert res.status_code == 200
    dl = client.get(f"/api/report/{rid}/download")
    assert dl.status_code == 200
    out = tmp_path / "dl.xlsx"
    out.write_bytes(dl.content)
    wb = openpyxl.load_workbook(out)
    assert wb["April"]["A1"].value.startswith("BRAND A")
    wb.close()


def test_crosscheck_endpoint(client, run_id):
    res = client.post("/api/crosscheck", json={
        "run_id": run_id["run_id"], "reference": str(REPORT_APRIL)})
    assert res.status_code == 200
    cc = res.json()
    assert cc["equal"] >= 70
    assert cc["accuracy"] > 0.8


def test_dashboard_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "RELAY" in res.text


def _april_export(tmp_path):
    """An export built from the April campaign's own FB links, so the join is
    exercised against real permalinks rather than invented ones."""
    import csv

    from relay.ingest.campaign import parse_campaign
    rows, _ = parse_campaign(CAMPAIGN, "April")
    out, pid = [], 5000
    for r in rows:
        for link in r.fb_links:
            if not link or "/share/" in link:      # shares need a browser
                continue
            pid += 1
            out.append({
                "Post ID": pid, "Page name": "সময় সংবাদ", "Title": r.caption[:80],
                "Publish time": r.date.strftime("%m/%d/%Y %H:%M") if r.date else "",
                "Permalink": link, "Is share": 0, "Post type": "Photos",
                "Views": pid * 7, "Reach": pid * 5,
                "Reactions, comments and shares": 9, "Reactions": pid % 97 + 3,
            })
    path = tmp_path / "april_export.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    return path, len(out)


def test_run_with_insights_export_fills_cells_exactly(client, tmp_path):
    export, n = _april_export(tmp_path)

    base = {"campaign": str(CAMPAIGN), "sheet": "April", "brand": "Brand A",
            "mainpage": str(WP_MAIN), "subpage": str(WP_SUB), "insta": str(WP_INSTA)}
    before = client.post("/api/run", json=base).json()
    after = client.post("/api/run", json={**base, "insights": [str(export)]}).json()

    assert after["insights"]["posts"] == n
    assert after["insights"]["metric"] == "views"
    assert after["insights"]["files"] == ["april_export.csv"]
    assert after["coverage"]["fb1"] > before["coverage"]["fb1"], \
        "the export must fill cells the supervisor file left empty"

    exact = [c for r in after["rows"] for s, c in r["cells"].items()
             if s.startswith("fb") and c["provenance"] == "collected"]
    assert exact and all("insights export" in c["note"] and "post " in c["note"]
                         for c in exact), "every exact cell carries its audit trail"


def test_run_without_insights_reports_none(client):
    res = client.post("/api/run", json={
        "campaign": str(CAMPAIGN), "sheet": "April", "brand": "Brand A"}).json()
    assert res["insights"] is None


def test_unreadable_insights_export_does_not_fail_the_run(client, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("nothing,useful\n1,2\n", encoding="utf-8")
    res = client.post("/api/run", json={
        "campaign": str(CAMPAIGN), "sheet": "April", "brand": "Brand A",
        "insights": [str(bad)]})
    assert res.status_code == 200
    assert any("unreadable" in i["reason"] for i in res.json()["issues"])
