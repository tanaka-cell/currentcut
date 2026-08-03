"""CurrentCut agent service — FastAPI."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import adk_pipeline, config, pipeline
from .models.schemas import (
    AgentRun, Asset, Claim, EgressLog, Project, ResearchResult, ScriptLine, Segment,
)
from .storage import store

app = FastAPI(title="CurrentCut Agent Service", version="0.1.0")


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
    _require_project(project_id)
    assets = pipeline.step_ingest(project_id, body.video_paths)
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
