"""CurrentCut agent service — FastAPI."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from . import adk_pipeline, config, demo, pipeline
from .agents import telop_sheet
from .models.schemas import (
    AgentRun, Asset, Claim, EgressLog, Project, ResearchResult, ScriptLine, Segment,
    TelopEntry,
)
from .storage import store

app = FastAPI(title="CurrentCut", version="0.2.0")

_STATIC = Path(__file__).resolve().parent / "static"


@app.get("/", response_class=HTMLResponse)
def index():
    return (_STATIC / "index.html").read_text(encoding="utf-8")


@app.post("/api/demo/start")
def demo_start():
    """Start a real overnight run on the bundled demo footage."""
    try:
        return {"project_id": demo.start()}
    except Exception as exc:
        raise HTTPException(500, str(exc))


@app.get("/api/demo/status/{project_id}")
def demo_status(project_id: str):
    return demo.status(project_id)


@app.get("/media/{project_id}/rough_cut.mp4")
def rough_cut(project_id: str):
    path = demo.rough_cut_path(project_id)
    if path is None:
        raise HTTPException(404, "rough cut not rendered yet")
    return FileResponse(path, media_type="video/mp4")


class CreateProject(BaseModel):
    title: str
    target_duration_seconds: int = 480
    air_date: str = ""
    tone: str = ""
    editorial_rules: list[str] = []


class AddAssets(BaseModel):
    video_paths: list[str]


@app.get("/healthz")
def healthz():
    return {
        "ok": True,
        "gemini_mode": "mock" if config.gemini_is_mock() else "real",
        "parallel_mode": "mock" if config.parallel_is_mock() else "real",
    }


@app.post("/projects")
def create_project(body: CreateProject):
    project = Project(**body.model_dump())
    store.put(project.id, "project", project)
    return project


@app.post("/projects/{project_id}/assets")
def add_assets(project_id: str, body: AddAssets):
    """Register footage. Paths are restricted to the bundled demo directory —
    a hosted service must not read arbitrary files off its own disk."""
    _require_project(project_id)
    allowed_root = config.DEMO_ASSETS_DIR.resolve()
    resolved: list[str] = []
    for raw in body.video_paths:
        path = Path(raw).resolve()
        if not path.is_file() or allowed_root not in path.parents:
            raise HTTPException(400, f"footage must be one of the bundled demo clips: {Path(raw).name}")
        resolved.append(str(path))
    assets = pipeline.step_ingest(project_id, resolved)
    return {"registered": [a.model_dump() for a in assets]}


@app.post("/projects/{project_id}/run")
def start_overnight_run(project_id: str):
    """Start Overnight Run (synchronous in Phase 1; async job in Phase 2)."""
    _require_project(project_id)
    report = adk_pipeline.run_overnight_adk(project_id)
    return report


@app.get("/projects/{project_id}/report")
def get_report(project_id: str):
    _require_project(project_id)
    return pipeline.morning_report(project_id)


@app.get("/projects/{project_id}/script")
def get_script(project_id: str):
    _require_project(project_id)
    return {
        "lines": [l.model_dump() for l in store.list(project_id, "script_lines", ScriptLine)],
        "claims": [c.model_dump() for c in store.list(project_id, "claims", Claim)],
        "sources": [r.model_dump() for r in store.list(project_id, "research_results", ResearchResult)],
    }


@app.get("/projects/{project_id}/telops")
def get_telops(project_id: str):
    """Drafted telop entries — timecode, type, characters, source attribution."""
    _require_project(project_id)
    return [t.model_dump() for t in store.list(project_id, "telops", TelopEntry)]


@app.get("/projects/{project_id}/telops.csv")
def get_telops_csv(project_id: str):
    _require_project(project_id)
    entries = store.list(project_id, "telops", TelopEntry)
    if not entries:
        raise HTTPException(404, "no telops drafted yet")
    path = telop_sheet.write_csv(entries, config.OUTPUT_DIR / project_id / "telops.csv")
    return FileResponse(path, media_type="text/csv", filename="telop_sheet.csv")


@app.post("/projects/{project_id}/telop-template")
async def upload_telop_template(project_id: str, file: UploadFile = File(...)):
    """Upload the programme's own telop order sheet (.xlsx).

    Gemini reads the header row to work out what each column means; the drafted
    telops are then written into a copy of that workbook, so the sheet keeps the
    station's formatting and the telop operator gets the form they know.
    """
    _require_project(project_id)
    if not (file.filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "upload the programme's telop sheet as .xlsx")

    project_dir = config.OUTPUT_DIR / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    template = project_dir / "telop_template.xlsx"
    template.write_bytes(await file.read())

    try:
        mapping = telop_sheet.infer_mapping(template)
    except Exception as exc:
        raise HTTPException(422, str(exc))
    (project_dir / "telop_mapping.json").write_text(
        mapping.model_dump_json(indent=1), encoding="utf-8")
    return {
        "recognised_columns": mapping.columns,
        "header_row": mapping.header_row,
        "first_data_row": mapping.first_data_row,
        "sheet": mapping.sheet_name,
        "notes": mapping.notes,
    }


@app.get("/projects/{project_id}/telop-sheet.xlsx")
def download_filled_sheet(project_id: str):
    """The programme's own sheet, filled in."""
    _require_project(project_id)
    project_dir = config.OUTPUT_DIR / project_id
    template = project_dir / "telop_template.xlsx"
    mapping_file = project_dir / "telop_mapping.json"
    if not template.exists() or not mapping_file.exists():
        raise HTTPException(404, "upload the programme's telop sheet first")
    entries = store.list(project_id, "telops", TelopEntry)
    if not entries:
        raise HTTPException(404, "no telops drafted yet")

    mapping = telop_sheet.ColumnMapping.model_validate_json(
        mapping_file.read_text(encoding="utf-8"))
    out = telop_sheet.fill_sheet(template, mapping, entries, project_dir / "telop_sheet.xlsx")
    return FileResponse(
        out, filename="telop_sheet.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/projects/{project_id}/segments")
def get_segments(project_id: str):
    _require_project(project_id)
    return [s.model_dump() for s in store.list(project_id, "segments", Segment)]


@app.get("/projects/{project_id}/egress")
def get_egress_log(project_id: str):
    """Confidentiality Firewall audit trail — what was (not) sent outside."""
    _require_project(project_id)
    return [e.model_dump() for e in store.list(project_id, "egress_log", EgressLog)]


@app.get("/projects/{project_id}/trace")
def get_agent_trace(project_id: str):
    """Judge-facing proof of real tool usage. No keys, no raw transcripts."""
    _require_project(project_id)
    runs = store.list(project_id, "agent_runs", AgentRun)
    return [
        {k: v for k, v in r.model_dump().items() if k != "input_summary"} | {
            "input_summary": r.input_summary[:80]
        }
        for r in runs
    ]


def _require_project(project_id: str) -> Project:
    project = store.get(project_id, "project", Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    return project
