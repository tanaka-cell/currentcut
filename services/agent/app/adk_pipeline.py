"""Google ADK orchestration layer.

An LlmAgent ("overnight_director") is given the pipeline steps as tools and
instructed to run the overnight workflow. This is the runtime entrypoint when
Gemini credentials exist; without them we fall back to the deterministic
`pipeline.run_overnight` and report provider="mock" honestly.

google-adk >= 1.36: LlmAgent, Runner, InMemorySessionService.
"""
from __future__ import annotations

import asyncio

from . import config, pipeline
from .models.schemas import AgentRun, now_iso
from .storage import store

_INSTRUCTION = """You are the overnight edit-suite supervisor for CurrentCut,
an AI night-shift assistant for TV directors. A director has gone to rest.
Run the overnight workflow for the given project_id by calling the tools IN
THIS ORDER, each exactly once, passing the same project_id:
1. analyze_footage
2. classify_confidentiality
3. extract_claims
4. run_research
5. write_script
6. draft_telops
7. render_rough_cut
Never skip confidentiality before research. After the final tool, reply with
one short line: DONE <number of script lines> lines.

Call each tool by the bare name listed above. Do not qualify it with an
application, package or namespace prefix — "analyze_footage", never
"currentcut.analyze_footage".
"""


def _tools(project_id_hint: str):
    # ADK builds tool schemas from signatures + docstrings.
    def analyze_footage(project_id: str) -> str:
        """Analyze all registered footage assets with Gemini video understanding.

        Args:
            project_id: The CurrentCut project id.
        Returns:
            Summary of segments produced.
        """
        segments = pipeline.step_analyze(project_id)
        return f"{len(segments)} segments logged"

    def classify_confidentiality(project_id: str) -> str:
        """Label every segment (PUBLIC/OFF_THE_RECORD/...) and set egress permissions.

        Args:
            project_id: The CurrentCut project id.
        Returns:
            Count of restricted segments.
        """
        segments = pipeline.step_confidentiality(project_id)
        restricted = sum(1 for s in segments if not s.allow_external_search)
        return f"{len(segments)} labeled, {restricted} restricted"

    def extract_claims(project_id: str) -> str:
        """Extract verifiable claims and safe external search queries.

        Args:
            project_id: The CurrentCut project id.
        Returns:
            Count of claims.
        """
        claims = pipeline.step_claims(project_id)
        return f"{len(claims)} claims extracted"

    def run_research(project_id: str) -> str:
        """Verify claims against the public web via the Parallel Search API egress gate.

        Args:
            project_id: The CurrentCut project id.
        Returns:
            Count of research results.
        """
        results = pipeline.step_research(project_id)
        return f"{len(results)} sources retrieved"

    def write_script(project_id: str) -> str:
        """Write the source-linked TV script from airable segments only.

        Args:
            project_id: The CurrentCut project id.
        Returns:
            Count of script lines.
        """
        lines = pipeline.step_script(project_id)
        return f"{len(lines)} script lines"

    def draft_telops(project_id: str) -> str:
        """Draft the telop order sheet the station's telop operator will type from.

        Args:
            project_id: The CurrentCut project id.
        Returns:
            Count of telop entries.
        """
        entries = pipeline.step_telops(project_id)
        return f"{len(entries)} telop entries drafted"

    def render_rough_cut(project_id: str) -> str:
        """Render the rough-cut MP4 + SRT + EDL with FFmpeg.

        Args:
            project_id: The CurrentCut project id.
        Returns:
            Rough cut metadata.
        """
        cut = pipeline.step_rough_cut(project_id)
        return f"mp4={cut['mp4']} duration={cut['duration_seconds']}s"

    return [analyze_footage, classify_confidentiality, extract_claims,
            run_research, write_script, draft_telops, render_rough_cut]


async def _run_adk_async(project_id: str) -> str:
    from google.adk.agents import LlmAgent
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    agent = LlmAgent(
        name="overnight_director",
        model=config.GEMINI_REASONING_MODEL,
        instruction=_INSTRUCTION,
        tools=_tools(project_id),
    )
    session_service = InMemorySessionService()
    runner = Runner(app_name="currentcut", agent=agent, session_service=session_service)
    await session_service.create_session(app_name="currentcut", user_id="director",
                                         session_id=project_id)
    message = types.Content(role="user", parts=[types.Part(
        text=f"Run the overnight workflow for project_id={project_id}")])
    final_text = ""
    async for event in runner.run_async(user_id="director", session_id=project_id,
                                        new_message=message):
        if event.is_final_response() and event.content and event.content.parts:
            final_text = "".join(p.text or "" for p in event.content.parts)
    return final_text


def _run_in_fixed_order(project_id: str, orchestrator_error: str) -> dict:
    """Run the same seven steps, in the same order, without the agent.

    Used when ADK orchestration itself fails. Recorded as its own run so the
    trace says who actually did the work.
    """
    fallback = AgentRun(project_id=project_id, agent_name="fixed_order_fallback",
                        provider="code", model_or_tool="pipeline.run_overnight",
                        status="running")
    store.put(project_id, "agent_runs", fallback)
    report = pipeline.run_overnight(project_id)
    fallback.status = "completed"
    fallback.completed_at = now_iso()
    fallback.output_summary = (
        "ADK orchestration failed (" + orchestrator_error[:120] + "); the same "
        "seven steps ran in the same fixed order from code")
    store.put(project_id, "agent_runs", fallback)

    from .models.schemas import Project
    project = store.get(project_id, "project", Project, project_id)
    if project:
        project.status = "first_cut_ready"
        store.put(project_id, "project", project)
    return report


def run_overnight_adk(project_id: str, video_paths: list[str] | None = None) -> dict:
    """ADK-driven overnight run, with honest fallback when no credentials."""
    config.ensure_dirs()
    if video_paths:
        pipeline.step_ingest(project_id, video_paths)

    if config.gemini_is_mock():
        run = AgentRun(project_id=project_id, agent_name="adk_orchestrator",
                       provider="mock", model_or_tool="deterministic-fallback",
                       status="completed", completed_at=now_iso(),
                       output_summary="No Gemini credentials: deterministic pipeline used")
        store.put(project_id, "agent_runs", run)
        return pipeline.run_overnight(project_id)

    run = AgentRun(project_id=project_id, agent_name="adk_orchestrator",
                   provider="adk", model_or_tool=config.GEMINI_REASONING_MODEL)
    store.put(project_id, "agent_runs", run)
    try:
        final = asyncio.run(_run_adk_async(project_id))
        run.status = "completed"
        run.output_summary = final[:200]
    except Exception as exc:
        # The conductor failed, not the work. Gemini sometimes calls a tool by
        # a qualified name ("currentcut.analyze_footage") that ADK will not
        # resolve, and one bad name used to cost a director the whole night.
        # The seven steps and their order are fixed either way, so run them
        # from code — and leave both facts in the trace rather than papering
        # over a failure the director is entitled to see.
        run.status = "failed"
        run.error = str(exc)[:300]
        run.completed_at = now_iso()
        store.put(project_id, "agent_runs", run)
        return _run_in_fixed_order(project_id, str(exc))
    run.completed_at = now_iso()
    store.put(project_id, "agent_runs", run)

    cut = None
    try:
        import json as _json
        meta = (config.OUTPUT_DIR / project_id / "rough_cut_meta.json")
        if meta.exists():
            cut = _json.loads(meta.read_text(encoding="utf-8"))
    except Exception:
        pass
    from .models.schemas import Project
    project = store.get(project_id, "project", Project, project_id)
    if project:
        project.status = "first_cut_ready"
        store.put(project_id, "project", project)
    return pipeline.morning_report(project_id, cut)
