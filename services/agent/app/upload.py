"""Guarded footage upload for the hosted demo.

The public instance runs on our API keys, so every guard here is cost armour:
file count, per-file and total size, total duration (probed with ffprobe, not
trusted from the client), and a per-day run budget. Limits are config values —
see config.UPLOAD_* — and the UI states them up front rather than letting a
visitor discover them by failing.

The quota file is instance-local and resets if Cloud Run replaces the
instance. That is acceptable for a demo guard: the budget is "roughly N runs a
day", not billing-grade accounting.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import uuid
from datetime import date
from pathlib import Path

from fastapi import HTTPException, UploadFile

from . import config, demo
from .agents.footage_logger import probe_duration

_quota_lock = threading.Lock()

_CHUNK = 1 << 20  # 1 MiB


def _quota_path() -> Path:
    return config.DATA_DIR / "upload_quota.json"


def _runs_today() -> int:
    try:
        d = json.loads(_quota_path().read_text(encoding="utf-8"))
        return d["count"] if d.get("date") == date.today().isoformat() else 0
    except (OSError, ValueError, KeyError):
        return 0


def _record_run() -> None:
    _quota_path().write_text(json.dumps(
        {"date": date.today().isoformat(), "count": _runs_today() + 1}),
        encoding="utf-8")


def _safe_name(filename: str) -> str:
    """Keep the basename the director will recognise; drop anything path-like."""
    name = Path(filename or "clip").name
    return re.sub(r"[^\w.\-]", "_", name) or "clip"


async def save_uploads(files: list[UploadFile]) -> list[str]:
    """Validate and store the uploaded clips; return their paths.

    Raises HTTPException with a message a visitor can act on. Everything is
    checked server-side — the browser's accept= filter is a convenience, not a
    guard.
    """
    if not files:
        raise HTTPException(400, "no files were uploaded")
    if len(files) > config.UPLOAD_MAX_FILES:
        raise HTTPException(400,
            f"up to {config.UPLOAD_MAX_FILES} clips per run; {len(files)} were sent")

    per_file_cap = config.UPLOAD_MAX_FILE_MB * (1 << 20)
    total_cap = config.UPLOAD_MAX_TOTAL_MB * (1 << 20)

    batch_dir = config.UPLOAD_DIR / uuid.uuid4().hex[:12]
    batch_dir.mkdir(parents=True, exist_ok=True)

    saved: list[Path] = []
    total_bytes = 0
    try:
        for f in files:
            name = _safe_name(f.filename)
            if Path(name).suffix.lower() not in config.UPLOAD_ALLOWED_SUFFIXES:
                raise HTTPException(400,
                    f"{name}: only {', '.join(config.UPLOAD_ALLOWED_SUFFIXES)} files are accepted")
            dest = batch_dir / name
            written = 0
            with open(dest, "wb") as out:
                while chunk := await f.read(_CHUNK):
                    written += len(chunk)
                    total_bytes += len(chunk)
                    if written > per_file_cap:
                        raise HTTPException(413,
                            f"{name} is over the {config.UPLOAD_MAX_FILE_MB} MB per-file cap")
                    if total_bytes > total_cap:
                        raise HTTPException(413,
                            f"the upload is over the {config.UPLOAD_MAX_TOTAL_MB} MB total cap")
                    out.write(chunk)
            saved.append(dest)

        # Duration comes from the file itself, never from the client.
        total_seconds = 0.0
        for path in saved:
            try:
                total_seconds += probe_duration(path)
            except Exception:
                raise HTTPException(400,
                    f"{path.name} is not a readable video (ffprobe could not open it)")
        if total_seconds > config.UPLOAD_MAX_TOTAL_MINUTES * 60:
            raise HTTPException(413,
                f"footage totals {total_seconds/60:.1f} minutes; the demo cap is "
                f"{config.UPLOAD_MAX_TOTAL_MINUTES} minutes")
    except Exception:
        # The file being written when the cap fired is on disk but not yet in
        # `saved` — remove the whole batch directory, not a list of names.
        shutil.rmtree(batch_dir, ignore_errors=True)
        raise

    return [str(p) for p in saved]


_QUOTA_MESSAGE = ("the public demo's daily budget for uploaded-footage runs is "
                  "used up — try again tomorrow, or run the bundled demo")


async def start_uploaded_run(files: list[UploadFile], title: str = "") -> str:
    """The whole guarded path: quota, validation, storage, launch.

    The lock is never held across an await: an async handler that sleeps on a
    threading lock blocks the event loop, and the request holding the lock can
    then never resume to release it. The cost is a small race where two
    simultaneous uploads both pass the early check — the re-check before
    recording keeps the budget roughly honest, which is all it promises.
    """
    with _quota_lock:
        if _runs_today() >= config.UPLOAD_RUNS_PER_DAY:
            raise HTTPException(429, _QUOTA_MESSAGE)
    clips = await save_uploads(files)
    with _quota_lock:
        if _runs_today() >= config.UPLOAD_RUNS_PER_DAY:
            for p in clips:
                Path(p).unlink(missing_ok=True)
            raise HTTPException(429, _QUOTA_MESSAGE)
        _record_run()
    return demo.start_uploaded(title.strip()[:120], clips)
