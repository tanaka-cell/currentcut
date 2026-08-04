"""Overnight Run pipeline.

Each step is a plain function (testable, mockable). `run_overnight` executes
them in order and records an AgentRun per step. The ADK layer
(`adk_pipeline.py`) exposes these same steps as tools so the ADK agent
genuinely drives the run when credentials are present.
"""
from __future__ import annotations

import time
from pathlib import Path

from . import config, progress
from .agents import claims as claims_agent
from .agents import confidentiality as conf_agent
from .agents import footage_logger, research, scriptwriter, telop
from .agents import rough_cut as rough_cut_agent
from .clients.gemini_client import gemini
from .clients.parallel_client import parallel
from .models.schemas import (
    AgentRun, Asset, Claim, Confidentiality, Project, RESTRICTED_LABELS, ResearchResult,
    ScriptLine, Segment, TelopEntry, now_iso,
)
from .storage import store


def _record(project_id: str, agent_name: str, provider: str, model_or_tool: str,
            fn, input_summary: str = ""):
    run = AgentRun(project_id=project_id, agent_name=agent_name, provider=provider,
                   model_or_tool=model_or_tool, input_summary=input_summary)
    store.put(project_id, "agent_runs", run)
    t0 = time.monotonic()
    try:
        result = fn()
        run.status = "completed"
        run.output_summary = _summarize(agent_name, result)
        return result
    except Exception as exc:
        run.status = "failed"
        run.error = str(exc)[:300]
        raise
    finally:
        run.latency_ms = int((time.monotonic() - t0) * 1000)
        run.completed_at = now_iso()
        store.put(project_id, "agent_runs", run)


def _plural(n: int, one: str, many: str = "") -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _summarize(agent_name: str, result) -> str:
    """What this step actually found, in words a director would use.

    Every step used to report "N items" — which told a reader nothing, and said
    "1 items" when there was one of them. This is the only place the run's
    progress is described, so it is worth saying something.
    """
    if isinstance(result, dict):
        if "duration_seconds" in result:
            return (f"{result['duration_seconds']:.0f}s cut from "
                    f"{_plural(result.get('lines_used', 0), 'line')}")
        return ", ".join(f"{k}={v}" for k, v in list(result.items())[:4])

    if not isinstance(result, list):
        return str(result)[:200]

    n = len(result)
    if agent_name == "footage_logger":
        speech = sum(1 for s in result if getattr(s, "transcript", "").strip())
        return f"{_plural(n, 'segment')}, {speech} with speech"
    if agent_name == "confidentiality":
        held = sum(1 for s in result if not getattr(s, "allow_script_use", True))
        return (f"{_plural(n, 'segment')} labelled"
                + (f", {held} held back" if held else ", none held back"))
    if agent_name == "claim_extraction":
        checkable = sum(1 for c in result if getattr(c, "allow_external_search", False))
        return f"{_plural(n, 'claim')}, {checkable} checkable against public sources"
    if agent_name == "parallel_research":
        return f"{_plural(n, 'source')} retrieved and judged"
    if agent_name == "scriptwriter":
        return _plural(n, "script line")
    if agent_name == "telop_draft":
        sourced = sum(1 for t in result if getattr(t, "source_note", ""))
        return f"{_plural(n, 'caption')}, {sourced} carrying a source"
    return _plural(n, "item")


# ---------- individual steps (also exposed as ADK tools) ----------

def step_ingest(project_id: str, video_paths: list[str]) -> list[Asset]:
    return [footage_logger.register_asset(project_id, p) for p in video_paths]


def step_analyze(project_id: str) -> list[Segment]:
    assets = store.list(project_id, "assets", Asset)
    segments: list[Segment] = []
    for i, asset in enumerate(assets, 1):
        progress.emit(project_id, "footage_logger", "running",
                       f"Watching clip {i}/{len(assets)}: {asset.filename}")
        clip_segments = _record(
            project_id, "footage_logger", gemini.provider, config.GEMINI_VIDEO_MODEL,
            lambda a=asset: footage_logger.analyze_asset(project_id, a),
            input_summary=asset.filename,
        )
        progress.emit(project_id, "footage_logger", "done",
                       f"Clip {i}/{len(assets)}: {asset.filename} — {len(clip_segments)} segments")
        segments.extend(clip_segments)
    return segments


def step_confidentiality(project_id: str) -> list[Segment]:
    segments = store.list(project_id, "segments", Segment)
    return _record(project_id, "confidentiality", gemini.provider,
                   config.GEMINI_FAST_MODEL if not gemini.mock else "rule-layer",
                   lambda: conf_agent.classify_segments(project_id, segments),
                   input_summary=f"{len(segments)} segments")


def step_claims(project_id: str) -> list[Claim]:
    segments = store.list(project_id, "segments", Segment)
    return _record(project_id, "claim_extraction", gemini.provider,
                   config.GEMINI_FAST_MODEL if not gemini.mock else "rule-layer",
                   lambda: claims_agent.extract_claims(project_id, segments),
                   input_summary=f"{len(segments)} segments")


def step_research(project_id: str, after_date: str | None = None) -> list[ResearchResult]:
    segments = store.list(project_id, "segments", Segment)
    claims = store.list(project_id, "claims", Claim)
    parallel.calls_this_run = 0
    return _record(project_id, "parallel_research", parallel.provider, "search-api/basic",
                   lambda: research.research_claims(project_id, claims, segments, after_date),
                   input_summary=f"{len(claims)} claims")


def step_script(project_id: str) -> list[ScriptLine]:
    project = store.get(project_id, "project", Project, project_id)
    segments = store.list(project_id, "segments", Segment)
    claims = store.list(project_id, "claims", Claim)
    research_results = store.list(project_id, "research_results", ResearchResult)
    return _record(project_id, "scriptwriter", "code", "story-arc-v1",
                   lambda: scriptwriter.write_script(project, segments, claims, research_results),
                   input_summary=f"{len(segments)} segments, {len(claims)} claims")


def step_telops(project_id: str) -> list[TelopEntry]:
    lines = store.list(project_id, "script_lines", ScriptLine)
    segments = store.list(project_id, "segments", Segment)
    claims = store.list(project_id, "claims", Claim)
    research_results = store.list(project_id, "research_results", ResearchResult)
    return _record(project_id, "telop_draft", gemini.provider,
                   config.GEMINI_FAST_MODEL if not gemini.mock else "rule-layer",
                   lambda: telop.draft_telops(project_id, lines, segments, claims, research_results),
                   input_summary=f"{len(lines)} script lines")


def step_rough_cut(project_id: str) -> dict:
    lines = store.list(project_id, "script_lines", ScriptLine)
    assets = store.list(project_id, "assets", Asset)
    return _record(project_id, "rough_cut", "ffmpeg", "edl-v1",
                   lambda: rough_cut_agent.render_rough_cut(project_id, lines, assets),
                   input_summary=f"{len(lines)} script lines")


# ---------- full run ----------

def run_overnight(project_id: str, video_paths: list[str] | None = None) -> dict:
    config.ensure_dirs()
    if video_paths:
        step_ingest(project_id, video_paths)
    step_analyze(project_id)
    step_confidentiality(project_id)
    step_claims(project_id)
    step_research(project_id)
    step_script(project_id)
    step_telops(project_id)
    cut = step_rough_cut(project_id)

    project = store.get(project_id, "project", Project, project_id)
    if project:
        project.status = "first_cut_ready"
        store.put(project_id, "project", project)
    return morning_report(project_id, cut)


def _saved_cut(project_id: str) -> dict:
    meta = config.OUTPUT_DIR / project_id / "rough_cut_meta.json"
    if not meta.exists():
        return {}
    try:
        import json
        return json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def morning_report(project_id: str, cut: dict | None = None) -> dict:
    segments = store.list(project_id, "segments", Segment)
    claims = store.list(project_id, "claims", Claim)
    protected = [s for s in segments if s.confidentiality in (
        Confidentiality.CONFIDENTIAL, Confidentiality.OFF_THE_RECORD,
        Confidentiality.PERSONAL_DATA)]
    needs_review = [s for s in segments if s.confidentiality == Confidentiality.NEEDS_HUMAN_REVIEW]
    checked = [c for c in claims if c.last_checked_at]
    total_footage = sum(s.end_seconds - s.start_seconds for s in segments)
    # A held segment that looks partly usable is the one thing a director should
    # not have to go looking for: the material is there, and only a boundary
    # decision stands between them and it.
    awaiting_boundary = [s for s in segments if s.release_proposal]
    # A dated claim is not the same as a claim that will change. A source can
    # state a real expiry ("valid until Aug 31"), or it can simply be the only
    # evidence and describe 2014, or it can carry a date that is the date a
    # still-current rule came in. Only the first two are worth a director's
    # attention before they lock the structure, and they are not the same
    # warning — so each says which it is rather than sharing one line.
    _RECHECK_WORDING = {
        "source_states_a_date": "a source attaches a date or period to this figure",
        "stale_evidence": "the only source found describes an earlier year",
    }
    volatile = [c for c in claims
                if c.recheck_before_lock and c.recheck_reason in _RECHECK_WORDING]
    return {
        "status": "FIRST CUT READY FOR DIRECTOR REVIEW",
        "footage_minutes_analyzed": round(total_footage / 60, 1),
        "claims_checked": len(checked),
        "confidential_moments_protected": len(protected),
        "claims_to_recheck_before_lock": [
            {"claim_id": c.id, "claim_text": c.claim_text, "note": c.volatility_note,
             "why": _RECHECK_WORDING[c.recheck_reason]}
            for c in volatile
        ],
        "decisions_need_review": len(needs_review)
        + len([c for c in claims if c.requires_human_approval]),
        "held_awaiting_your_decision": [
            {
                "segment_id": s.id,
                "why_held": s.confidentiality.value,
                "alert": (f"{len([p for p in s.release_proposal if p.proposed_label not in RESTRICTED_LABELS])}"
                          f" of {len(s.release_proposal)} sentences here look usable, "
                          "but where the off-record part starts is your call — "
                          "nothing has been released."),
                "sentences": [p.model_dump() for p in s.release_proposal],
            }
            for s in awaiting_boundary
        ],
        # A later GET of the report must still describe the cut that was made.
        "rough_cut": cut or _saved_cut(project_id),
    }
