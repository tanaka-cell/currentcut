"""A failing conductor must not cost the director the night.

The orchestrator is an LlmAgent, so it can fail in ways the work itself has
not: observed in the wild, Gemini called a tool as "currentcut.analyze_footage"
and ADK refused the qualified name, ending the run before a single clip was
read. The steps and their order are fixed, so nothing about that failure makes
the night's work impossible — only unsupervised.

These pin the two halves of the answer: the run still finishes, and the trace
still says the agent failed.
"""
import pytest

from app import adk_pipeline, config, pipeline
from app.models.schemas import AgentRun, Project
from app.storage import store


def _project(project_id: str) -> None:
    store.put(project_id, "project", Project(id=project_id, title="Broken conductor"))


def _runs(project_id: str) -> list[AgentRun]:
    return store.list(project_id, "agent_runs", AgentRun)


def test_a_failed_agent_still_produces_the_morning_report(monkeypatch, tmp_path):
    project_id = "prj_orchestrator_fail"
    _project(project_id)

    def explode(_pid):
        raise ValueError("Tool 'currentcut.analyze_footage' not found.")

    ran = {}

    def fake_overnight(pid):
        ran["pid"] = pid
        return {"claims_checked": 0, "note": "deterministic"}

    monkeypatch.setattr(adk_pipeline, "_run_adk_async", explode)
    monkeypatch.setattr(config, "gemini_is_mock", lambda: False)
    monkeypatch.setattr(pipeline, "run_overnight", fake_overnight)

    report = adk_pipeline.run_overnight_adk(project_id)

    assert ran["pid"] == project_id, "the fixed-order pipeline never ran"
    assert report["note"] == "deterministic"


def test_the_trace_still_says_the_agent_failed(monkeypatch):
    """Falling back quietly would turn a real failure into a clean-looking run.
    Both entries have to survive: the agent that failed, and the code that
    finished the work."""
    project_id = "prj_orchestrator_fail_trace"
    _project(project_id)

    def explode(_pid):
        raise ValueError("Tool 'currentcut.analyze_footage' not found.")

    monkeypatch.setattr(adk_pipeline, "_run_adk_async", explode)
    monkeypatch.setattr(config, "gemini_is_mock", lambda: False)
    monkeypatch.setattr(pipeline, "run_overnight", lambda pid: {"ok": True})

    adk_pipeline.run_overnight_adk(project_id)

    runs = {run.agent_name: run for run in _runs(project_id)}
    assert runs["adk_orchestrator"].status == "failed"
    assert "currentcut.analyze_footage" in runs["adk_orchestrator"].error
    assert runs["fixed_order_fallback"].status == "completed"
    assert runs["fixed_order_fallback"].provider == "code"


def test_the_instruction_names_the_mistake_to_avoid():
    """The fallback is the net, not the fix. The agent is told plainly which
    name shape ADK rejects, so the net is rarely needed."""
    assert "currentcut.analyze_footage" in adk_pipeline._INSTRUCTION
    assert "bare name" in adk_pipeline._INSTRUCTION
