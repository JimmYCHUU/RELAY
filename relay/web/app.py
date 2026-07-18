"""RELAY dashboard backend (SRS FR-24)."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import config, store
from ..ingest.campaign import list_sheets
from ..models import RunResult
from ..pipeline import run_pipeline
from ..report.crosscheck import compare, parse_reference
from ..report.generator import build_report
from ..resolve.heuristic import apply_estimate

app = FastAPI(title="RELAY", version="1.0.0")

UPLOADS = config.DATA_DIR / "uploads"
_runs: dict[str, RunResult] = {}
_run_db_ids: dict[str, int] = {}
_run_inputs: dict[str, dict] = {}


def _serialize(run_id: str, result: RunResult) -> dict:
    return {
        "run_id": run_id,
        "brand": result.brand,
        "month": result.month,
        "coverage": result.coverage(),
        "issues": [vars(i) for i in result.issues],
        "tiers": result.match_tiers,
        "rows": [
            {
                "no": r.no,
                "date": r.date.isoformat() if r.date else None,
                "caption": r.caption,
                "links": r.links,
                "cells": {
                    s: {
                        "value": c.value,
                        "provenance": c.provenance,
                        "confidence": c.confidence,
                        "note": c.note,
                    }
                    for s, c in r.cells.items()
                },
            }
            for r in result.rows
        ],
    }


@app.post("/api/upload")
async def upload(kind: str = Form(...), file: UploadFile = File(...)) -> dict:
    UPLOADS.mkdir(parents=True, exist_ok=True)
    dest = UPLOADS / f"{uuid.uuid4().hex[:8]}_{file.filename}"
    with dest.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    out = {"path": str(dest), "name": file.filename, "kind": kind}
    if kind in ("campaign", "reference"):
        try:
            out["sheets"] = list_sheets(dest)
        except Exception as exc:
            raise HTTPException(400, f"Not a readable .xlsx: {exc}") from exc
    return out


class RunReq(BaseModel):
    campaign: str
    sheet: str
    brand: str
    mainpage: str | None = None
    subpage: str | None = None
    insta: str | None = None


@app.post("/api/run")
def run(req: RunReq) -> dict:
    try:
        result = run_pipeline(
            req.campaign, req.sheet, req.brand,
            mainpage_path=req.mainpage, subpage_path=req.subpage, insta_path=req.insta,
        )
    except (ValueError, FileNotFoundError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc
    run_id = uuid.uuid4().hex[:12]
    _runs[run_id] = result
    inputs = req.model_dump()
    _run_inputs[run_id] = inputs
    _run_db_ids[run_id] = store.save_run(result, inputs)
    return _serialize(run_id, result)


def _get_run(run_id: str) -> RunResult:
    if run_id not in _runs:
        raise HTTPException(404, "unknown run id (runs are in-memory per session)")
    return _runs[run_id]


class CellReq(BaseModel):
    run_id: str
    row_no: int
    slot: str = Field(pattern="^(fb1|fb2|fb3|x|ig)$")


class EstimateReq(CellReq):
    reactions: int = Field(ge=0)
    k: float = Field(default=config.K_DEFAULT, ge=config.K_MIN, le=config.K_MAX)


class OverrideReq(CellReq):
    value: int | None


def _find_row(result: RunResult, row_no: int):
    for r in result.rows:
        if r.no == row_no:
            return r
    raise HTTPException(404, f"row {row_no} not found")


@app.post("/api/estimate")
def estimate(req: EstimateReq) -> dict:
    result = _get_run(req.run_id)
    row = _find_row(result, req.row_no)
    try:
        row.cells[req.slot] = apply_estimate(row.cells[req.slot], req.reactions, req.k)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    store.record_override(_run_db_ids[req.run_id], req.row_no, req.slot,
                          None, row.cells[req.slot].value)
    c = row.cells[req.slot]
    return {"value": c.value, "provenance": c.provenance, "confidence": c.confidence,
            "note": c.note}


@app.post("/api/override")
def override(req: OverrideReq) -> dict:
    result = _get_run(req.run_id)
    row = _find_row(result, req.row_no)
    old = row.cells[req.slot].value
    from ..models import CellValue
    row.cells[req.slot] = CellValue(req.value, "manual", 1.0, "manual entry")
    store.record_override(_run_db_ids[req.run_id], req.row_no, req.slot, old, req.value)
    return {"value": req.value, "provenance": "manual", "confidence": 1.0,
            "note": "manual entry"}


class BatchCollectReq(BaseModel):
    run_ids: list[str] = Field(min_length=1)
    target: str = Field(pattern="^(x|fb)$")
    k: float = Field(default=config.K_DEFAULT, ge=config.K_MIN, le=config.K_MAX)
    dry_run: bool = False


_batch_jobs: dict[str, "Progress"] = {}


@app.post("/api/collect/batch")
def collect_batch(req: BatchCollectReq) -> dict:
    """One collection pass over every brand in the cycle — a single browser
    session and one shared Pacer budget (safer than per-brand resets)."""
    import threading

    from ..collectors.base import Pacer
    from ..collectors.runner import (Progress, collect_facebook, collect_x,
                                     meta_profile_exists)

    results = [_get_run(rid) for rid in req.run_ids]
    existing = _batch_jobs.get(req.target)
    if existing and existing.state == "running":
        raise HTTPException(409, "collection already running for this target")
    if req.target == "fb" and not req.dry_run and not meta_profile_exists():
        raise HTTPException(412, "meta-session-required")

    progress = Progress()
    _batch_jobs[req.target] = progress

    def work():
        if req.target == "x":
            pacer = Pacer(min_delay=config.X_PACE_MIN_S,
                          max_delay=config.X_PACE_MAX_S, dry_run=req.dry_run)
            collect_x(results, pacer=pacer, progress=progress)
        else:
            pacer = Pacer(dry_run=req.dry_run)
            collect_facebook(results, req.k, pacer=pacer, progress=progress)

    threading.Thread(target=work, daemon=True, name=f"collect-batch-{req.target}").start()
    return {"started": True, "target": req.target, "runs": len(results)}


@app.get("/api/collect/batch/{target}")
def collect_batch_status(target: str, ids: str = "") -> dict:
    id_list = [i for i in ids.split(",") if i]
    runs = {rid: _serialize(rid, _get_run(rid)) for rid in id_list}
    p = _batch_jobs.get(target)
    if p is None:
        return {"state": "idle", "runs": runs}
    return {
        "state": p.state, "total": p.total, "done": p.done, "filled": p.filled,
        "current": p.current, "message": p.message, "events": p.events[-8:],
        "runs": runs,
    }


@app.post("/api/collect/batch/{target}/stop")
def collect_batch_stop(target: str) -> dict:
    p = _batch_jobs.get(target)
    if p is None or p.state != "running":
        return {"stopping": False}
    p.stop_requested = True
    return {"stopping": True}


class BatchReportReq(BaseModel):
    run_ids: list[str] = Field(min_length=1)
    comments: bool = True


@app.post("/api/report/batch")
def generate_batch(req: BatchReportReq) -> dict:
    """One workbook per brand (sponsors never see each other's numbers),
    bundled into a zip for the user."""
    import zipfile

    results = [_get_run(rid) for rid in req.run_ids]
    paths = []
    for rid, result in zip(req.run_ids, results):
        out = config.OUTPUT_DIR / f"{result.brand} ({result.month}).xlsx"
        build_report(result, out, estimate_comments=req.comments)
        store.set_output(_run_db_ids[rid], str(out))
        paths.append(out)
    month = results[0].month
    zpath = config.OUTPUT_DIR / f"RELAY reports ({month}).zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in paths:
            z.write(f, arcname=f.name)
    return {"name": zpath.name, "workbooks": [p.name for p in paths]}


@app.get("/api/report/batch/download/{name}")
def download_batch(name: str):
    if "/" in name or ".." in name or not name.endswith(".zip"):
        raise HTTPException(400, "bad archive name")
    path = config.OUTPUT_DIR / name
    if not path.exists():
        raise HTTPException(404, "archive not generated yet")
    return FileResponse(path, media_type="application/zip", filename=name)


@app.post("/api/report/{run_id}")
def generate(run_id: str, comments: bool = True) -> dict:
    result = _get_run(run_id)
    out = config.OUTPUT_DIR / f"{result.brand} ({result.month}).xlsx"
    build_report(result, out, estimate_comments=comments)
    store.set_output(_run_db_ids[run_id], str(out))
    return {"path": str(out), "name": out.name}


@app.get("/api/report/{run_id}/download")
def download(run_id: str):
    result = _get_run(run_id)
    out = config.OUTPUT_DIR / f"{result.brand} ({result.month}).xlsx"
    if not out.exists():
        raise HTTPException(404, "report not generated yet")
    return FileResponse(
        out,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=out.name,
    )


_meta_login = {"running": False, "error": None}


@app.post("/api/login/meta")
def meta_login_start() -> dict:
    """Open a headed browser on this machine for the one-time Meta sign-in.
    Works when RELAY runs directly on the desktop (not inside Docker)."""
    import threading

    from ..collectors.runner import meta_profile_exists

    if _meta_login["running"]:
        return {"status": "running"}
    if meta_profile_exists():
        return {"status": "already"}

    def work():
        _meta_login.update(running=True, error=None)
        try:
            from ..collectors.browser import login_meta
            login_meta()
        except Exception as exc:  # e.g. no display inside a container
            _meta_login["error"] = (
                f"Could not open a browser window ({type(exc).__name__}). "
                "If RELAY runs in Docker, run `python -m relay.cli login meta` "
                "on the host instead — the session folder is shared."
            )
        finally:
            _meta_login["running"] = False

    threading.Thread(target=work, daemon=True, name="meta-login").start()
    return {"status": "started"}


@app.get("/api/login/meta/status")
def meta_login_status() -> dict:
    from ..collectors.runner import meta_profile_exists
    return {
        "running": _meta_login["running"],
        "ready": (not _meta_login["running"]) and meta_profile_exists(),
        "error": _meta_login["error"],
    }


class CollectReq(BaseModel):
    run_id: str
    target: str = Field(pattern="^(x|fb)$")
    k: float = Field(default=config.K_DEFAULT, ge=config.K_MIN, le=config.K_MAX)
    dry_run: bool = False


_jobs: dict[tuple[str, str], "Progress"] = {}


@app.post("/api/collect")
def collect(req: CollectReq) -> dict:
    import threading

    from ..collectors.base import Pacer
    from ..collectors.runner import (Progress, collect_facebook, collect_x,
                                     meta_profile_exists)

    result = _get_run(req.run_id)
    key = (req.run_id, req.target)
    existing = _jobs.get(key)
    if existing and existing.state == "running":
        raise HTTPException(409, "collection already running for this run")
    if req.target == "fb" and not req.dry_run and not meta_profile_exists():
        # 412 → the dashboard auto-opens the sign-in browser via /api/login/meta
        raise HTTPException(412, "meta-session-required")

    progress = Progress()
    _jobs[key] = progress

    def work():
        if req.target == "x":
            pacer = Pacer(min_delay=config.X_PACE_MIN_S,
                          max_delay=config.X_PACE_MAX_S, dry_run=req.dry_run)
            collect_x(result, pacer=pacer, progress=progress)
        else:
            pacer = Pacer(dry_run=req.dry_run)
            collect_facebook(result, req.k, pacer=pacer, progress=progress)

    threading.Thread(target=work, daemon=True, name=f"collect-{req.target}").start()
    return {"started": True, "target": req.target}


@app.post("/api/collect/{run_id}/{target}/stop")
def collect_stop(run_id: str, target: str) -> dict:
    p = _jobs.get((run_id, target))
    if p is None or p.state != "running":
        return {"stopping": False}
    p.stop_requested = True
    return {"stopping": True}


@app.get("/api/collect/{run_id}/{target}")
def collect_status(run_id: str, target: str) -> dict:
    result = _get_run(run_id)
    p = _jobs.get((run_id, target))
    if p is None:
        return {"state": "idle"}
    return {
        "state": p.state, "total": p.total, "done": p.done, "filled": p.filled,
        "current": p.current, "message": p.message, "events": p.events[-8:],
        "run": _serialize(run_id, result),
    }


class CrossReq(BaseModel):
    run_id: str
    reference: str
    sheet: str | None = None


@app.post("/api/crosscheck")
def crosscheck(req: CrossReq) -> dict:
    result = _get_run(req.run_id)
    try:
        ref = parse_reference(req.reference, req.sheet or result.month)
    except (KeyError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(400, f"cannot read reference: {exc}") from exc
    cc = compare(result, ref)
    s = cc.summary()
    return {
        "cells": s["cells"],
        "equal": s["equal"],
        "accuracy": s["accuracy"],
        "differs": [vars(d) for d in s["differs"]],
        "only_generated": [vars(d) for d in s["only_generated"]],
        "only_reference": [vars(d) for d in s["only_reference"]],
    }


@app.get("/api/runs")
def runs() -> list[dict]:
    return store.list_runs()


static_dir = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
