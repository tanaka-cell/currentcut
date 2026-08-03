"""CLI for local runs: python -m app.cli demo [--adk]"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import adk_pipeline, config, pipeline
from .models.schemas import Project
from .storage import store


def run_demo(use_adk: bool) -> None:
    config.ensure_dirs()
    demo_dir = config.DEMO_ASSETS_DIR
    videos = sorted(demo_dir.glob("*.mp4"))
    if not videos:
        print(f"No demo assets in {demo_dir}.")
        print("Generate them first:  python ../../scripts/make_demo_assets.py")
        sys.exit(1)

    project = Project(
        title="AI搭載型スマート弁当箱が話題 (Quick Judge Demo)",
        target_duration_seconds=90,
        air_date="2026-08-07",
        tone="energetic but not sensational",
        editorial_rules=["Never use off-record comments",
                         "Do not send unpublished information to external web search"],
    )
    store.put(project.id, "project", project)
    print(f"Project: {project.id}  ({project.title})")
    print(f"Gemini: {'MOCK' if config.gemini_is_mock() else 'REAL'} / "
          f"Parallel: {'MOCK' if config.parallel_is_mock() else 'REAL'}")

    paths = [str(v) for v in videos]
    if use_adk:
        report = adk_pipeline.run_overnight_adk(project.id, paths)
    else:
        report = pipeline.run_overnight(project.id, paths)

    print("\n===== MORNING REPORT =====")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nData: {config.DATA_DIR / project.id}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "demo":
        run_demo(use_adk="--adk" in args)
    else:
        print("usage: python -m app.cli demo [--adk]")
