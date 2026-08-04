"""Live per-item progress log for the Overnight Run screen.

AgentRun (pipeline.py) records one row per pipeline step — enough for the
agent trace table, too coarse to watch a step while it runs. This adds one
line per item within a step (one clip watched, one segment labelled, one
claim checked) so the run screen can show what is happening right now, not
just which step is active.

Never raises: a broken log must not break the run it is describing.
"""
from __future__ import annotations

from .models.schemas import ProgressEvent
from .storage import store


def emit(project_id: str, step: str, state: str, text: str) -> None:
    try:
        store.put(project_id, "progress_events", ProgressEvent(
            project_id=project_id, step=step, state=state, text=text[:160]))
    except Exception:
        pass


def recent(project_id: str, step: str, limit: int = 6) -> list[dict]:
    try:
        events = [e for e in store.list(project_id, "progress_events", ProgressEvent)
                  if e.step == step]
    except Exception:
        return []
    events.sort(key=lambda e: e.created_at)
    return [e.model_dump() for e in events[-limit:]]
