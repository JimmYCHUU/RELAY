"""RELAY dashboard backend (SRS FR-24)."""
from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path, PureWindowsPath

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

app = FastAPI(title="RELAY", version="1.0.0")
log = logging.getLogger("relay.web")

UPLOADS = config.DATA_DIR / "uploads"
_runs: dict[str, RunResult] = {}
_run_db_ids: dict[str, int] = {}
_run_inputs: dict[str, dict] = {}
_MAX_RUNS = 32


def _evict_runs() -> None:
    """_runs is per-session working memory, not history — cap it. An evicted
    run is recoverable through /api/run: the SQLite checkpoints restore every
    collected value."""
    while len(_runs) > _MAX_RUNS:
        old = next(iter(_runs))
        _runs.pop(old, None)
        _run_db_ids.pop(old, None)
        _run_inputs.pop(old, None)


def _persist_cb(pairs):
    """Checkpoint hook for the collector threads: maps each RunResult back to
    its DB run id and writes every filled cell to SQLite as it lands, so a
    crash/power-off mid-collection loses nothing."""
    ids = {id(res): db_id for res, db_id in pairs}

    def persist(run, row_idx, slot, cell):
        db_id = ids.get(id(run))
        if db_id is not None:
            store.update_cell(db_id, row_idx, slot, cell)
    return persist


def _insights_summary(result: RunResult) -> dict | None:
    """What the export accounted for, so the dashboard can show the user how
    much of the report is exact rather than estimated."""
    index = getattr(result, "insights", None)
    if index is None or not len(index):
        return None
    exact = sum(1 for r in result.rows for s in ("fb1", "fb2", "fb3")
                if r.links.get(s) and r.cells[s].provenance == "collected")
    return {
        "posts": len(index),
        "files": [Path(f).name for f in index.files],
        "filled": exact,
        "metric": config.INSIGHTS_METRIC,
    }


def _serialize(run_id: str, result: RunResult) -> dict:
    return {
        "run_id": run_id,
        "brand": result.brand,
        "month": result.month,
        "coverage": result.coverage(),
        "issues": [vars(i) for i in result.issues],
        "insights": _insights_summary(result),
        "rows": [
            {
                "no": r.no,
                "date": r.date.isoformat() if r.date else None,
                "caption": r.caption,
                "original_caption": r.original_caption,
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
    # Meta's own content exports — the source of essentially every figure.
    # Facebook joins by link, caption or post id; Instagram joins exactly by the
    # post's shortcode, which is stable between a copied link and the export.
    insights: list[str] = Field(default_factory=list)
    ig_insights: list[str] = Field(default_factory=list)


@app.post("/api/run")
def run(req: RunReq) -> dict:
    try:
        result = run_pipeline(
            req.campaign, req.sheet, req.brand,
            insights_paths=list(req.insights) or None,
            ig_insights_paths=list(req.ig_insights) or None,
        )
    except (ValueError, FileNotFoundError, KeyError) as exc:
        # A 400 here reads as "your sheet is wrong", so a bug inside the parser
        # arrives disguised as bad input (a `%-d` strftime on Windows once
        # surfaced as a bare "Invalid format string"). Log the traceback and
        # name the tab, so the next one is diagnosable from the message alone.
        log.exception("run failed: sheet=%r campaign=%s", req.sheet, req.campaign)
        detail = str(exc) or type(exc).__name__
        if req.sheet and req.sheet not in detail:
            detail = f"sheet '{req.sheet}': {detail}"
        raise HTTPException(400, detail) from exc
    inputs = req.model_dump()
    # Resume: inherit values a previous run of the same campaign/sheet/brand
    # already collected (checkpointed per cell), so a crash, power-off, or
    # dashboard restart never re-scrapes what's done.
    restored = 0
    prev_id = store.find_resumable_run(inputs)
    if prev_id:
        restored = store.hydrate_cells(result, store.load_cells(prev_id))
    run_id = uuid.uuid4().hex[:12]
    _runs[run_id] = result
    _run_inputs[run_id] = inputs
    _run_db_ids[run_id] = store.save_run(result, inputs)
    _evict_runs()
    out = _serialize(run_id, result)
    out["restored"] = restored
    return out


def _get_run(run_id: str) -> RunResult:
    if run_id not in _runs:
        raise HTTPException(404, "unknown run id (runs are in-memory per session)")
    return _runs[run_id]


class CellReq(BaseModel):
    run_id: str
    row_no: int
    slot: str = Field(pattern="^(fb1|fb2|fb3|x|ig)$")


class OverrideReq(CellReq):
    value: int | None


def _find_row(result: RunResult, row_no: int):
    for r in result.rows:
        if r.no == row_no:
            return r
    raise HTTPException(404, f"row {row_no} not found")


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
    target: str = Field(pattern="^(x|fb|ig)$")
    dry_run: bool = False


_batch_jobs: dict[str, "Progress"] = {}


def _autopilot_running() -> bool:
    return _autopilot_job is not None and _autopilot_job.state == "running"


@app.post("/api/collect/batch")
def collect_batch(req: BatchCollectReq) -> dict:
    """One collection pass over every brand in the cycle — a single browser
    session and one shared Pacer budget (safer than per-brand resets)."""
    import threading

    from ..collectors.base import Pacer
    from ..collectors.runner import (Progress, collect_instagram, collect_x,
                                     meta_profile_exists, resolve_facebook)

    results = [_get_run(rid) for rid in req.run_ids]
    existing = _batch_jobs.get(req.target)
    if existing and existing.state == "running":
        raise HTTPException(409, "collection already running for this target")
    if _autopilot_running():
        raise HTTPException(409, "autopilot is running — stop it first")
    if req.target in ("fb", "ig") and not req.dry_run \
            and not meta_profile_exists():
        raise HTTPException(412, "meta-session-required")

    progress = Progress()
    _batch_jobs[req.target] = progress
    persist = _persist_cb([(res, _run_db_ids[rid])
                           for rid, res in zip(req.run_ids, results)])

    def work():
        if req.target == "x":
            pacer = Pacer(min_delay=config.X_PACE_MIN_S,
                          max_delay=config.X_PACE_MAX_S, dry_run=req.dry_run)
            collect_x(results, pacer=pacer, progress=progress, persist=persist)
        elif req.target == "ig":
            pacer = Pacer(dry_run=req.dry_run)
            collect_instagram(results, pacer=pacer, progress=progress,
                              persist=persist)
        else:
            pacer = Pacer(dry_run=req.dry_run)
            resolve_facebook(results, pacer=pacer, progress=progress,
                             persist=persist)

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


class AutopilotReq(BaseModel):
    run_ids: list[str] = Field(min_length=1)
    dry_run: bool = False


class AutopilotJob:
    """Cycle-level progress: one campaign after another in load order,
    X → FB → IG within each."""

    def __init__(self, run_ids: list[str]):
        self.run_ids = run_ids
        self.campaigns = len(run_ids)
        self.campaign_idx = 0
        self.brand = ""
        self.target = ""
        self.sub = None                  # the running collector's Progress
        self.state = "running"           # running | finished | stopped | error
        self.message = ""
        self.stop_requested = False
        self.events: list[str] = []

    def log(self, line: str) -> None:
        self.events.append(line)
        del self.events[:-60]


_autopilot_job: AutopilotJob | None = None


@app.post("/api/autopilot")
def autopilot_start(req: AutopilotReq) -> dict:
    """Hands-free cycle: every campaign in load order, X → FB → IG within
    each, one Pacer budget per platform across the whole cycle. The Meta
    session is checked up front — nothing runs until it exists."""
    import threading

    from ..collectors.base import Pacer
    from ..collectors.runner import (Progress, collect_instagram, collect_x,
                                     meta_profile_exists, resolve_facebook)

    global _autopilot_job
    results = [_get_run(rid) for rid in req.run_ids]
    if _autopilot_running():
        raise HTTPException(409, "autopilot already running")
    others = list(_batch_jobs.values()) + list(_jobs.values())
    if any(p.state == "running" for p in others):
        raise HTTPException(409, "a collection is already running — stop it first")

    def needs_meta(result: RunResult) -> bool:
        return any(row.links.get(slot) and row.cells[slot].value is None
                   for row in result.rows for slot in ("fb1", "fb2", "fb3", "ig"))

    if not req.dry_run and any(needs_meta(r) for r in results) \
            and not meta_profile_exists():
        raise HTTPException(412, "meta-session-required")

    job = AutopilotJob(req.run_ids)
    _autopilot_job = job
    pacers = {
        "x": Pacer(min_delay=config.X_PACE_MIN_S, max_delay=config.X_PACE_MAX_S,
                   dry_run=req.dry_run),
        "fb": Pacer(dry_run=req.dry_run),
        "ig": Pacer(dry_run=req.dry_run),
    }
    persist = _persist_cb([(res, _run_db_ids[rid])
                           for rid, res in zip(req.run_ids, results)])
    collectors = {
        "x": lambda res, sub: collect_x(res, pacer=pacers["x"], progress=sub,
                                        persist=persist),
        "fb": lambda res, sub: resolve_facebook(res, pacer=pacers["fb"],
                                                progress=sub, persist=persist),
        "ig": lambda res, sub: collect_instagram(res, pacer=pacers["ig"],
                                                 progress=sub, persist=persist),
    }
    labels = {"fb": "Facebook", "ig": "Instagram", "x": "X"}

    def work():
        filled = 0
        try:
            for idx, result in enumerate(results, start=1):
                if job.stop_requested:
                    break
                job.campaign_idx, job.brand = idx, result.brand
                # Facebook first: it is the pass that identifies posts and
                # refreshes stale captions, so everything after it works from a
                # row that already describes itself correctly.
                for target in ("fb", "ig", "x"):
                    if job.stop_requested:
                        break
                    sub = Progress()
                    job.target, job.sub = target, sub
                    collectors[target](result, sub)
                    filled += sub.filled
                    job.log(f"{result.brand} · {labels[target]}: {sub.message}")
                    if sub.state == "stopped" and not sub.stop_requested:
                        # pacing budget or challenge page — halt the whole
                        # cycle; a later re-run picks up the remaining cells
                        job.state, job.message = "stopped", sub.message
                        return
            if job.stop_requested:
                job.state = "stopped"
                job.message = f"stopped — {filled} cells filled so far"
            else:
                job.state = "finished"
                job.message = (f"autopilot done — {filled} cells filled across "
                               f"{job.campaigns} campaign(s)")
        except Exception as exc:
            job.state, job.message = "error", f"{type(exc).__name__}: {exc}"

    threading.Thread(target=work, daemon=True, name="autopilot").start()
    return {"started": True, "campaigns": job.campaigns}


@app.get("/api/autopilot/status")
def autopilot_status(ids: str = "") -> dict:
    id_list = [i for i in ids.split(",") if i]
    runs = {rid: _serialize(rid, _get_run(rid)) for rid in id_list}
    job = _autopilot_job
    if job is None:
        return {"state": "idle", "runs": runs}
    sub = job.sub
    events = job.events + (sub.events if sub else [])
    return {
        "state": job.state, "message": job.message,
        "brand": job.brand, "campaign": job.campaign_idx,
        "campaigns": job.campaigns, "target": job.target,
        "total": sub.total if sub else 0, "done": sub.done if sub else 0,
        "filled": sub.filled if sub else 0, "current": sub.current if sub else "",
        "events": events[-8:],
        "runs": runs,
    }


@app.post("/api/autopilot/stop")
def autopilot_stop() -> dict:
    job = _autopilot_job
    if job is None or job.state != "running":
        return {"stopping": False}
    job.stop_requested = True
    if job.sub:
        job.sub.stop_requested = True
    return {"stopping": True}


class ReportGroup(BaseModel):
    """One delivered workbook. Several run ids means several tabs of one
    brand's campaign sheet folded into a single continuous report."""
    run_ids: list[str] = Field(min_length=1)
    label: str | None = None


class BatchReportReq(BaseModel):
    # Either shape works: `groups` for the merge-aware dashboard, a flat
    # `run_ids` for the older callers and the CLI, where each run is its own
    # workbook exactly as before.
    groups: list[ReportGroup] = Field(default_factory=list)
    run_ids: list[str] = Field(default_factory=list)
    comments: bool = True

    def resolved(self) -> list[ReportGroup]:
        if self.groups:
            return self.groups
        if self.run_ids:
            return [ReportGroup(run_ids=[rid]) for rid in self.run_ids]
        raise HTTPException(400, "no runs to report on")


_REPORT_SUFFIXES = (".xlsx", ".zip")
_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _safe_output(name: str) -> Path:
    """Resolve a generated-report filename inside OUTPUT_DIR, or refuse it.

    Checked as a *Windows* path on every platform: a backslash separates
    directories only on Windows, so `PurePosixPath("sub\\x.xlsx").name` returns
    the whole string and a guard written against the running platform would let
    "sub\\x.xlsx" through on the Linux box and mean something else on the
    supervisor's desktop.
    """
    if PureWindowsPath(name).name != name \
            or PureWindowsPath(name).suffix.lower() not in _REPORT_SUFFIXES:
        raise HTTPException(400, "bad report name")
    return config.OUTPUT_DIR / name


def _build_group(group: ReportGroup) -> Path:
    """Write one workbook for a group of runs and return its path."""
    from ..report.merge import merge_runs

    results = [_get_run(rid) for rid in group.run_ids]
    brands = {r.brand for r in results}
    if len(brands) > 1:
        raise HTTPException(
            400, f"cannot merge different brands into one workbook: "
                 f"{', '.join(sorted(brands))}")
    merged = merge_runs(results, group.label)
    out = config.OUTPUT_DIR / f"{merged.brand} ({merged.month}).xlsx"
    build_report(merged, out)
    for rid in group.run_ids:
        store.set_output(_run_db_ids[rid], str(out))
    return out


@app.post("/api/report/group")
def generate_group(group: ReportGroup) -> dict:
    """One workbook for one brand, merging every tab in the group."""
    out = _build_group(group)
    return {"path": str(out), "name": out.name}


@app.post("/api/report/batch")
def generate_batch(req: BatchReportReq) -> dict:
    """One workbook per brand (sponsors never see each other's numbers),
    bundled into a zip for the user."""
    import zipfile

    groups = req.resolved()
    paths = [_build_group(g) for g in groups]
    month = _get_run(groups[0].run_ids[0]).month
    zpath = config.OUTPUT_DIR / f"RELAY reports ({month}).zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in paths:
            z.write(f, arcname=f.name)
    return {"name": zpath.name, "workbooks": [p.name for p in paths]}


@app.get("/api/report/download/{name}")
def download_named(name: str):
    """Download any generated workbook or archive by filename — a merged report
    belongs to several runs, so no single run id addresses it."""
    path = _safe_output(name)
    if not path.exists():
        raise HTTPException(404, "report not generated yet")
    media = "application/zip" if path.suffix.lower() == ".zip" else _XLSX_MEDIA
    return FileResponse(path, media_type=media, filename=name)


@app.get("/api/report/batch/download/{name}")
def download_batch(name: str):
    path = _safe_output(name)
    if path.suffix.lower() != ".zip":
        raise HTTPException(400, "bad archive name")
    if not path.exists():
        raise HTTPException(404, "archive not generated yet")
    return FileResponse(path, media_type="application/zip", filename=name)


@app.post("/api/report/{run_id}")
def generate(run_id: str, comments: bool = True) -> dict:
    result = _get_run(run_id)
    out = config.OUTPUT_DIR / f"{result.brand} ({result.month}).xlsx"
    build_report(result, out)
    store.set_output(_run_db_ids[run_id], str(out))
    return {"path": str(out), "name": out.name}


@app.get("/api/report/{run_id}/download")
def download(run_id: str):
    result = _get_run(run_id)
    out = config.OUTPUT_DIR / f"{result.brand} ({result.month}).xlsx"
    if not out.exists():
        raise HTTPException(404, "report not generated yet")
    return FileResponse(out, media_type=_XLSX_MEDIA, filename=out.name)


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
    target: str = Field(pattern="^(x|fb|ig)$")
    dry_run: bool = False


_jobs: dict[tuple[str, str], "Progress"] = {}


@app.post("/api/collect")
def collect(req: CollectReq) -> dict:
    import threading

    from ..collectors.base import Pacer
    from ..collectors.runner import (Progress, collect_instagram, collect_x,
                                     meta_profile_exists, resolve_facebook)

    result = _get_run(req.run_id)
    key = (req.run_id, req.target)
    existing = _jobs.get(key)
    if existing and existing.state == "running":
        raise HTTPException(409, "collection already running for this run")
    if _autopilot_running():
        raise HTTPException(409, "autopilot is running — stop it first")
    if req.target in ("fb", "ig") and not req.dry_run \
            and not meta_profile_exists():
        # 412 → the dashboard auto-opens the sign-in browser via /api/login/meta
        raise HTTPException(412, "meta-session-required")

    progress = Progress()
    _jobs[key] = progress
    persist = _persist_cb([(result, _run_db_ids[req.run_id])])

    def work():
        if req.target == "x":
            pacer = Pacer(min_delay=config.X_PACE_MIN_S,
                          max_delay=config.X_PACE_MAX_S, dry_run=req.dry_run)
            collect_x(result, pacer=pacer, progress=progress, persist=persist)
        elif req.target == "ig":
            pacer = Pacer(dry_run=req.dry_run)
            collect_instagram(result, pacer=pacer, progress=progress,
                              persist=persist)
        else:
            pacer = Pacer(dry_run=req.dry_run)
            resolve_facebook(result, pacer=pacer, progress=progress,
                             persist=persist)

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
