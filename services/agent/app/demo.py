"""One-click Quick Judge Demo: runs the real pipeline in the background.

Nothing here is pre-generated. Pressing the button starts an actual overnight
run — Gemini analyses the footage, the Parallel Search API is called for the
claims that clear the egress gate, and FFmpeg renders the cut. Progress is read
back from the AgentRun records the pipeline writes as it goes.
"""
from __future__ import annotations

import threading
import traceback
from pathlib import Path

from . import adk_pipeline, config, progress
from .models.schemas import AgentRun, Project
from .storage import store

# Order matters: the UI renders this as the Overnight Run checklist.
STEPS = [
    ("footage_logger", "Footage Logger", "Gemini reads every clip"),
    ("confidentiality", "Confidentiality", "Label each segment, decide what may leave"),
    ("claim_extraction", "Claim Extraction", "Pull out checkable, self-contained claims"),
    ("parallel_research", "Parallel Research", "Verify public claims on the live web"),
    ("scriptwriter", "Scriptwriter", "Write the source-linked script"),
    ("telop_draft", "Telop Sheet", "Draft the captions the station will set"),
    ("rough_cut", "Rough Cut", "Cut the preview with FFmpeg"),
]

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def demo_clips(shoot: str = "") -> list[str]:
    return [str(p) for p in sorted(config.demo_dir(shoot).glob("*.mp4"))]


# One story, shot in two places. The titles are the director's, so each is in
# the language the shoot was made in.
SHOOT_TITLES = {
    "en": "The corner coffee shop against convenience-store coffee (Quick Judge Demo)",
    "ja": "コンビニコーヒーに押される街の喫茶店 (Quick Judge Demo)",
}


def _launch(title: str, clips: list[str]) -> str:
    """Create a project for these clips and run the pipeline on a worker thread."""
    project = Project(
        title=title,
        target_duration_seconds=90,
        air_date="",
        tone="energetic but not sensational",
        editorial_rules=[
            "Never use off-record comments",
            "Do not send unpublished information to external web search",
        ],
        status="running",
    )
    store.put(project.id, "project", project)

    with _lock:
        _jobs[project.id] = {"state": "running", "error": ""}

    def run() -> None:
        try:
            adk_pipeline.run_overnight_adk(project.id, clips)
            with _lock:
                _jobs[project.id]["state"] = "done"
        except Exception as exc:
            traceback.print_exc()
            with _lock:
                _jobs[project.id] = {"state": "failed", "error": str(exc)[:400]}

    threading.Thread(target=run, daemon=True).start()
    return project.id


def start(shoot: str = "") -> str:
    """Run the bundled demo shoot."""
    config.ensure_dirs()
    shoot = shoot or config.DEFAULT_DEMO_SHOOT
    if shoot not in config.DEMO_SHOOTS:
        raise RuntimeError(f"unknown shoot {shoot!r}; known: {', '.join(config.DEMO_SHOOTS)}")
    clips = demo_clips(shoot)
    if not clips:
        raise RuntimeError(f"no demo footage found in {config.demo_dir(shoot)}")
    return _launch(SHOOT_TITLES.get(shoot, shoot), clips)


def start_uploaded(title: str, clips: list[str]) -> str:
    """Run on footage a visitor uploaded. Validation happened at the API layer;
    this trusts nothing about the content beyond that and runs the same
    pipeline the demo runs."""
    config.ensure_dirs()
    if not clips:
        raise RuntimeError("no uploaded footage to run")
    return _launch(title or "Uploaded footage (Overnight Run)", clips)


def status(project_id: str) -> dict:
    with _lock:
        job = dict(_jobs.get(project_id, {"state": "unknown", "error": ""}))

    runs = store.list(project_id, "agent_runs", AgentRun)
    by_name: dict[str, AgentRun] = {}
    for run in runs:
        # Footage Logger runs once per clip; show the latest.
        prev = by_name.get(run.agent_name)
        if prev is None or run.started_at >= prev.started_at:
            by_name[run.agent_name] = run

    steps = []
    for name, label, detail in STEPS:
        run = by_name.get(name)
        matching = [r for r in runs if r.agent_name == name]
        state = run.status if run else "pending"
        steps.append({
            "name": name,
            "label": label,
            "detail": detail,
            "state": state,
            "provider": run.provider if run else "",
            "output": "; ".join(r.output_summary for r in matching if r.output_summary)[:120],
            "latency_ms": sum(r.latency_ms for r in matching),
            # Live sub-log — what this step is doing right now (clip N/M being
            # watched, a claim being checked, a segment held back). Only worth
            # fetching for the step actually running.
            "log": progress.recent(project_id, name) if state == "running" else [],
        })
    job["steps"] = steps
    job["project_id"] = project_id
    return job


def rough_cut_path(project_id: str) -> Path | None:
    p = config.OUTPUT_DIR / project_id / "rough_cut.mp4"
    return p if p.exists() else None
