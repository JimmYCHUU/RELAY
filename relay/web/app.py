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
