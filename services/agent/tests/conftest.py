"""Test env is prepared BEFORE app modules are imported (config reads env at import)."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

os.environ["CURRENTCUT_FORCE_MOCK"] = "gemini,parallel"


@pytest.fixture(scope="session")
def workdir(tmp_path_factory):
    root = tmp_path_factory.mktemp("currentcut")
    os.environ["CURRENTCUT_DATA_DIR"] = str(root / "data")
    os.environ["CURRENTCUT_OUTPUT_DIR"] = str(root / "output")
    return root


@pytest.fixture(scope="session")
def demo_clips(workdir):
    """Two tiny synthetic clips + ground-truth sidecars (mock Gemini input)."""
    import json

    clips_dir = workdir / "clips"
    clips_dir.mkdir()

    def make_clip(name: str, duration: float, segments: list[dict]) -> Path:
        mp4 = clips_dir / f"{name}.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-f", "lavfi", "-i", f"color=c=0x224466:s=320x180:d={duration}:r=30",
             "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
             "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-shortest",
             str(mp4)],
            check=True,
        )
        mp4.with_suffix(".mp4.analysis.json").write_text(
            json.dumps({"segments": segments}, ensure_ascii=False), encoding="utf-8")
        return mp4

    interview = make_clip("interview", 12.0, [
        {"start_seconds": 0.0, "end_seconds": 4.0, "speaker": "社長",
         "transcript": "現在、全国に80店舗あります。",
         "visual_summary": "社長インタビュー", "shot_type": "interview",
         "usability_score": 0.9},
        {"start_seconds": 4.0, "end_seconds": 8.0, "speaker": "社長",
         "transcript": "価格は1,980円です。",
         "visual_summary": "社長インタビュー", "shot_type": "interview",
         "usability_score": 0.9},
        {"start_seconds": 8.0, "end_seconds": 12.0, "speaker": "社長",
         "transcript": "ここはオフレコですが、来月銀座に新店舗を出します。",
         "visual_summary": "社長インタビュー", "shot_type": "interview",
         "usability_score": 0.9},
    ])
    broll = make_clip("broll", 6.0, [
        {"start_seconds": 0.0, "end_seconds": 6.0, "speaker": "",
         "transcript": "", "visual_summary": "商品のクローズアップ",
         "shot_type": "broll", "usability_score": 0.8},
    ])
    return [interview, broll]


@pytest.fixture(scope="session")
def overnight_run(demo_clips):
    """One full mock-mode overnight run shared by the acceptance tests."""
    from app import pipeline
    from app.models.schemas import Project
    from app.storage import store

    project = Project(title="acceptance", target_duration_seconds=60)
    store.put(project.id, "project", project)
    report = pipeline.run_overnight(project.id, [str(c) for c in demo_clips])
    return project.id, report
