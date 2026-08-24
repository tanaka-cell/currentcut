"""What one day of this instance is allowed to cost.

Every run of the pipeline spends real money: Gemini reads each clip, Parallel is
called for each claim that clears the gate, ffmpeg burns CPU for minutes. The
hosted demo runs on our keys, so the bill for anybody's curiosity is ours.

The upload route was given a daily budget when it was written, because uploading
footage obviously looked expensive. The demo button beside it — which runs the
very same pipeline over nine clips — was given none, and the rate limiter would
happily let a script start hundreds of runs a minute. That is the same mistake
this codebase keeps making in different rooms: the guard went on the door that
looked dangerous rather than on the thing that actually spends.

So the budget lives here, at the one point every run passes through, and it
counts runs rather than requests.

Two numbers, because they stop different things:

- **How many at once.** This is the one that matters against a burst, and it is
  the one a visitor never notices: a person runs the demo, watches it, and runs
  it again. Nobody legitimately starts four at the same moment.
- **How many in a day.** A backstop against a slow drip that stays under the
  first limit. Set far above what a day of genuine interest looks like — during
  judging this has to say yes to every judge who presses it, and a demo that
  answers "budget spent" to the person evaluating it has failed at the only job
  it has.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import date
from pathlib import Path

from fastapi import HTTPException

from . import config

# Runs of the bundled demo, per day. Generous: this is the button a judge
# presses, and being told to come back tomorrow is worse than the bill.
DEMO_RUNS_PER_DAY = int(os.getenv("CURRENTCUT_DEMO_RUNS_PER_DAY", "60"))
# Pipelines in flight at once, counting demo and uploaded footage together —
# they cost the same because they are the same pipeline.
MAX_CONCURRENT_RUNS = int(os.getenv("CURRENTCUT_MAX_CONCURRENT_RUNS", "3"))

_lock = threading.Lock()
_in_flight = 0


def _path() -> Path:
    return config.DATA_DIR / "run_budget.json"


def _read() -> dict:
    """Today's tally. Instance-local and reset when Cloud Run replaces the
    instance, which is honest for a demo guard: the promise is "roughly N a
    day", not billing-grade accounting. The provider's own spending cap is the
    thing that is actually load-bearing, and it is set in their console."""
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if data.get("date") == date.today().isoformat() else {}


def spent_today(kind: str) -> int:
    return int(_read().get(kind, 0))


def record(kind: str) -> None:
    data = _read()
    data["date"] = date.today().isoformat()
    data[kind] = int(data.get(kind, 0)) + 1
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _path().write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass  # a budget we cannot write is not a reason to refuse the run


class RunSlot:
    """Held for the length of one pipeline run.

    A context manager rather than a counter the caller increments, because the
    run happens on a worker thread and the slot has to come back when that
    thread ends — including when it ends by raising, which is exactly when
    somebody forgets.
    """

    def __enter__(self) -> "RunSlot":
        return self

    def __exit__(self, *_exc) -> None:
        release()


def claim(kind: str, *, daily_limit: int | None = None) -> None:
    """Take a slot for one run, or refuse the run. Raises HTTPException(429)."""
    global _in_flight
    with _lock:
        if _in_flight >= MAX_CONCURRENT_RUNS:
            raise HTTPException(429, (
                "the demo is already running for someone else — "
                "give it a minute and press again"))
        if daily_limit is not None and spent_today(kind) >= daily_limit:
            raise HTTPException(429, (
                "this instance's runs for today are used up — try again "
                "tomorrow, or deploy your own from the repository"))
        _in_flight += 1
        record(kind)


def release() -> None:
    global _in_flight
    with _lock:
        _in_flight = max(0, _in_flight - 1)


def in_flight() -> int:
    with _lock:
        return _in_flight
