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


def _clip_maker(clips_dir: Path):
    import json

    clips_dir.mkdir(parents=True, exist_ok=True)

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

    return make_clip


@pytest.fixture(scope="session")
def demo_clips(workdir):
    """Two tiny synthetic clips + ground-truth sidecars (mock Gemini input)."""
    make_clip = _clip_maker(workdir / "clips")

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
def demo_clips_en(workdir):
    """The same shape of shoot in English.

    The judges for this contest run the demo in English, and until this fixture
    existed every acceptance test was in Japanese — so the caption limits, the
    director-facing notes and the language detection were all exercised on the
    one language that already worked.
    """
    make_clip = _clip_maker(workdir / "clips_en")

    interview = make_clip("interview_en", 12.0, [
        {"start_seconds": 0.0, "end_seconds": 4.0, "speaker": "Owner",
         "transcript": "We have eighty stores across the country now.",
         "visual_summary": "Owner interview", "shot_type": "interview",
         "usability_score": 0.9},
        {"start_seconds": 4.0, "end_seconds": 8.0, "speaker": "Owner",
         "transcript": "We do about two hundred cups a day here.",
         "visual_summary": "Owner interview", "shot_type": "interview",
         "usability_score": 0.9},
        {"start_seconds": 8.0, "end_seconds": 12.0, "speaker": "Owner",
         "transcript": "Off the record, we are opening in Brooklyn next month.",
         "visual_summary": "Owner interview", "shot_type": "interview",
         "usability_score": 0.9},
    ])
    broll = make_clip("broll_en", 6.0, [
        {"start_seconds": 0.0, "end_seconds": 6.0, "speaker": "",
         "transcript": "", "visual_summary": "Close-up of the product",
         "shot_type": "broll", "usability_score": 0.8},
    ])
    return [interview, broll]


def _run(clips) -> tuple:
    from app import pipeline
    from app.models.schemas import Project
    from app.storage import store

    project = Project(title="acceptance", target_duration_seconds=60)
    store.put(project.id, "project", project)
    report = pipeline.run_overnight(project.id, [str(c) for c in clips])
    return project.id, report


@pytest.fixture(scope="session")
def overnight_run(demo_clips):
    """One full mock-mode overnight run shared by the acceptance tests."""
    return _run(demo_clips)


@pytest.fixture(scope="session")
def overnight_run_en(demo_clips_en):
    """The same run on an English shoot."""
    return _run(demo_clips_en)
