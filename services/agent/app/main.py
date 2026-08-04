"""CurrentCut agent service — FastAPI."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from . import adk_pipeline, config, demo, pipeline, upload
from .agents import confidentiality, house_style, telop_form, telop_sheet
from .models.schemas import (
    AgentRun, Asset, Claim, EgressLog, Project, RESTRICTED_LABELS, ResearchResult,
    ScriptLine, Segment, TelopEntry,
)
from .storage import store

app = FastAPI(title="CurrentCut", version="0.2.0")

_STATIC = Path(__file__).resolve().parent / "static"


@app.get("/", response_class=HTMLResponse)
def index():
    return (_STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/static/hero_frame.jpg")
def hero_frame():
    return FileResponse(_STATIC / "hero_frame.jpg", media_type="image/jpeg")


@app.post("/api/demo/start")
def demo_start(shoot: str = ""):
    """Start a real overnight run on the bundled demo footage.

    `shoot` picks which shoot to run — see config.DEMO_SHOOTS. Omitted, it runs
    the English one, because that is what a visitor will be reading.
    """
    try:
        return {"project_id": demo.start(shoot)}
    except Exception as exc:
        raise HTTPException(500, str(exc))


@app.get("/api/demo/shoots")
def demo_shoots():
    return {"default": config.DEFAULT_DEMO_SHOOT,
            "shoots": [{"id": s, "title": demo.SHOOT_TITLES.get(s, s),
                        "clips": len(demo.demo_clips(s))}
                       for s in config.DEMO_SHOOTS]}


@app.get("/api/demo/status/{project_id}")
def demo_status(project_id: str):
    return demo.status(project_id)


@app.post("/api/upload/start")
async def upload_start(files: list[UploadFile] = File(...), title: str = Form("")):
    """Run the overnight pipeline on footage the visitor uploads.

    Guarded (count, size, probed duration, daily budget) because this public
    instance runs on our API keys — see upload.py. Returns the same project_id
    the demo returns, so the caller polls the same status endpoint.
    """
    return {"project_id": await upload.start_uploaded_run(files, title),
            "limits": {
                "max_files": config.UPLOAD_MAX_FILES,
                "max_file_mb": config.UPLOAD_MAX_FILE_MB,
                "max_total_mb": config.UPLOAD_MAX_TOTAL_MB,
                "max_total_minutes": config.UPLOAD_MAX_TOTAL_MINUTES,
            }}


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


@app.get("/projects/{project_id}/telop-manuscript.xlsx")
def download_manuscript(project_id: str):
    """The director's テロップ原稿 — the file that goes to the edit house.

    This is the everyday deliverable and needs no template: the edit house pours
    it into the programme's own form. Available whether or not a template has
    been uploaded.
    """
    project = _require_project(project_id)
    entries = store.list(project_id, "telops", TelopEntry)
    if not entries:
        raise HTTPException(404, "no telops drafted yet")
    path = telop_sheet.write_manuscript(
        entries, config.OUTPUT_DIR / project_id / "telop_manuscript.xlsx",
        title=project.title, air_date=project.air_date)
    return FileResponse(
        path, filename="テロップ原稿.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/projects/{project_id}/telops.csv")
def get_telops_csv(project_id: str):
    _require_project(project_id)
    entries = store.list(project_id, "telops", TelopEntry)
    if not entries:
        raise HTTPException(404, "no telops drafted yet")
    path = telop_sheet.write_csv(entries, config.OUTPUT_DIR / project_id / "telops.csv")
    return FileResponse(path, media_type="text/csv", filename="telop_manuscript.csv")


@app.post("/projects/{project_id}/telop-template")
async def upload_telop_template(project_id: str, file: UploadFile = File(...)):
    """Upload the programme's own telop form — spreadsheet, image or PDF.

    Optional. Without one you still get the テロップ原稿 above, which is what most
    programmes actually need. Upload one when you want CurrentCut to fill the
    programme's own form as well.

    A workbook is read for its structure and filled in place. An image or PDF is
    treated as a paper order pad: Gemini locates the area where the characters
    go, you confirm it once, and one sheet is printed per telop.
    """
    _require_project(project_id)
    name = (file.filename or "").lower()
    suffix = Path(name).suffix
    project_dir = config.OUTPUT_DIR / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    body = await file.read()

    if suffix in (".xlsx", ".xlsm"):
        template = project_dir / f"telop_template{suffix}"
        template.write_bytes(body)
        try:
            mapping = telop_sheet.infer_mapping(template)
        except Exception as exc:
            raise HTTPException(422, str(exc))
        (project_dir / "telop_mapping.json").write_text(
            mapping.model_dump_json(indent=1), encoding="utf-8")
        return {
            "kind": "spreadsheet",
            "recognised_fields": {k: f"{v.column}+{v.row_offset}"
                                  for k, v in mapping.fields.items()},
            "first_data_row": mapping.first_data_row,
            "rows_per_entry": mapping.row_stride,
            "entries_per_sheet": mapping.entries_per_sheet,
            "sheets": mapping.sheet_names,
            "max_chars_per_line": mapping.max_chars_per_line,
            "notes": mapping.notes,
        }

    if suffix in (".jpg", ".jpeg", ".png", ".pdf"):
        form = project_dir / f"telop_form{suffix}"
        form.write_bytes(body)
        try:
            area = telop_form.infer_text_area(form)
        except Exception as exc:
            raise HTTPException(422, str(exc))
        (project_dir / "telop_area.json").write_text(
            area.model_dump_json(indent=1), encoding="utf-8")
        return {"kind": "form", "text_area": area.box,
                "reading_direction": area.reading_direction, "note": area.note}

    raise HTTPException(400, "upload the form as .xlsx, .jpg, .png or .pdf")


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

    mapping = telop_sheet.SheetMapping.model_validate_json(
        mapping_file.read_text(encoding="utf-8"))
    try:
        out = telop_sheet.fill_sheet(template, mapping, entries,
                                     project_dir / "telop_sheet.xlsx")
    except OverflowError as exc:
        raise HTTPException(422, str(exc))
    return FileResponse(
        out, filename="telop_sheet.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


class TextAreaOverride(BaseModel):
    box: list[int]
    reading_direction: str = "horizontal"


@app.put("/projects/{project_id}/telop-form/area")
def set_text_area(project_id: str, body: TextAreaOverride):
    """Adjust where the characters are printed. Stored with the programme."""
    _require_project(project_id)
    if len(body.box) != 4 or not all(0 <= v <= 1000 for v in body.box):
        raise HTTPException(400, "box must be [ymin, xmin, ymax, xmax] within 0-1000")
    area = telop_form.TextArea(box=body.box, reading_direction=body.reading_direction,
                               confirmed_by_director=True, note="set by the director")
    (config.OUTPUT_DIR / project_id / "telop_area.json").write_text(
        area.model_dump_json(indent=1), encoding="utf-8")
    return {"text_area": area.box, "confirmed": True}


@app.post("/projects/{project_id}/telop-form/render")
def render_telop_forms(project_id: str):
    """One filled sheet per telop: a PDF to print and JPEGs to send."""
    _require_project(project_id)
    project_dir = config.OUTPUT_DIR / project_id
    forms = [p for p in project_dir.glob("telop_form.*")]
    area_file = project_dir / "telop_area.json"
    if not forms or not area_file.exists():
        raise HTTPException(404, "upload the programme's telop form first")
    entries = store.list(project_id, "telops", TelopEntry)
    if not entries:
        raise HTTPException(404, "no telops drafted yet")

    area = telop_form.TextArea.model_validate_json(area_file.read_text(encoding="utf-8"))
    try:
        result = telop_form.render_sheets(forms[0], area, entries, project_dir / "telop_sheets")
    except Exception as exc:
        raise HTTPException(422, str(exc))
    return result


@app.get("/projects/{project_id}/telop-sheets.pdf")
def download_telop_pdf(project_id: str):
    _require_project(project_id)
    pdf = config.OUTPUT_DIR / project_id / "telop_sheets" / "telop_sheets.pdf"
    if not pdf.exists():
        raise HTTPException(404, "render the sheets first")
    return FileResponse(pdf, media_type="application/pdf", filename="telop_sheets.pdf")


@app.post("/projects/{project_id}/house-style")
async def learn_house_style(project_id: str, files: list[UploadFile] = File(...)):
    """Learn the corner's running order from editions it has already aired.

    Upload past scripts of the SAME recurring corner (.txt/.md/.pdf/.docx).
    Around 30–50 gives a reliable shape; ten is enough to see the obvious
    pattern. What comes back is a readable profile the director can correct —
    not a trained model. The scripts are the programme's own material and are
    never sent to external search.
    """
    _require_project(project_id)
    upload_dir = config.OUTPUT_DIR / project_id / "past_scripts"
    upload_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    for item in files[:house_style.MAX_SCRIPTS]:
        name = Path(item.filename or "").name
        if not name.lower().endswith(house_style.SUPPORTED):
            continue
        path = upload_dir / name
        path.write_bytes(await item.read())
        saved.append(path)
    if not saved:
        raise HTTPException(400, f"upload past scripts as {', '.join(house_style.SUPPORTED)}")

    try:
        style = house_style.learn(project_id, saved)
    except Exception as exc:
        raise HTTPException(422, str(exc))
    return style.model_dump()


@app.get("/projects/{project_id}/house-style")
def get_house_style(project_id: str):
    _require_project(project_id)
    style = house_style.load(project_id)
    if style is None:
        raise HTTPException(404, "no past scripts have been learned from yet")
    return style.model_dump()


@app.put("/projects/{project_id}/house-style")
def correct_house_style(project_id: str, body: house_style.HouseStyle):
    """The director's corrections win. This is the point of keeping the profile
    readable rather than training a model on the scripts."""
    _require_project(project_id)
    body.project_id = project_id
    body.confirmed_by_director = True
    store.put(project_id, "house_style", body)
    return body.model_dump()


class ReleaseBody(BaseModel):
    release_indexes: list[int]
    confirmed_by: str


@app.post("/projects/{project_id}/segments/{segment_id}/release")
def confirm_release(project_id: str, segment_id: str, body: ReleaseBody):
    """Settle where an off-record remark starts, and release the rest.

    The only route by which held material becomes usable. It takes a name
    because releasing someone's off-record remark is a person's decision and a
    person's responsibility — the tool proposes a boundary and will not act on
    its own proposal.
    """
    _require_project(project_id)
    if not body.confirmed_by.strip():
        raise HTTPException(400, "confirmed_by is required: a person has to own this decision")
    segment = store.get(project_id, "segments", Segment, segment_id)
    if segment is None:
        raise HTTPException(404, "no such segment")
    try:
        pieces = confidentiality.confirm_release(
            project_id, segment, body.release_indexes, body.confirmed_by.strip())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    # The script and everything downstream of it were built without this
    # material; rebuild them so the release actually reaches the cut.
    pipeline.step_script(project_id)
    pipeline.step_telops(project_id)
    cut = pipeline.step_rough_cut(project_id)
    return {"released": [p.model_dump() for p in pieces
                         if p.confidentiality not in RESTRICTED_LABELS],
            "still_held": [p.model_dump() for p in pieces
                           if p.confidentiality in RESTRICTED_LABELS],
            "report": pipeline.morning_report(project_id, cut)}


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
