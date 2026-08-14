"""How long the service keeps what it was given.

A visitor uploads their own rushes to the public demo, watches the run, and
closes the tab. Nothing then removed the footage: it sat in the data directory
for as long as the instance lived, beside the next visitor's. On Cloud Run that
happens to be /tmp and the instance is replaced eventually, but "it will
probably be restarted" is a deployment accident, not a retention policy, and the
same code run on a laptop keeps everything for ever.

So: a sweep, on a stated clock, that runs when the service starts and again
before each new run — no scheduler to install, and the busier the instance the
more often it tidies. The demo's own bundled footage is not touched; it is part
of the repository, not something anyone gave us.
"""
from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path

from . import config

# Long enough that a director can come back to last night's run in the morning
# — the whole promise of the product — and short enough that nobody's rushes are
# still on a public demo a week later.
RETENTION_HOURS = int(os.getenv("CURRENTCUT_RETENTION_HOURS", "48"))


def _age_hours(path: Path) -> float:
    try:
        return (time.time() - path.stat().st_mtime) / 3600
    except OSError:
        return 0.0


def _remove(path: Path) -> bool:
    """Delete a directory, then look. `ignore_errors=True` returns quietly when
    a file is locked — which on Windows is often — and the caller then reports a
    deletion that did not happen."""
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        logging.warning("could not remove %s — it is still there", path)
        return False
    return True


def sweep(older_than_hours: int | None = None) -> dict:
    """Remove expired uploads and the runs made from them. Returns what it did."""
    limit = RETENTION_HOURS if older_than_hours is None else older_than_hours
    removed, kept, failed = 0, 0, 0

    roots = [config.UPLOAD_DIR, config.DATA_DIR, config.OUTPUT_DIR]
    protected = {config.UPLOAD_DIR.resolve()}
    for root in roots:
        if not root.exists():
            continue
        for child in root.iterdir():
            if not child.is_dir() or child.resolve() in protected:
                continue
            if _age_hours(child) < limit:
                kept += 1
                continue
            if _remove(child):
                removed += 1
            else:
                failed += 1
    if removed or failed:
        logging.info("retention sweep: removed %d, kept %d, could not remove %d",
                     removed, kept, failed)
    return {"removed": removed, "kept": kept, "failed": failed,
            "older_than_hours": limit}
