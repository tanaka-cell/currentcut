"""CLI for local runs: python -m app.cli demo [--adk] [en|ja]"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import adk_pipeline, config, demo, pipeline
from .models.schemas import Project
from .storage import store


def run_demo(use_adk: bool, shoot: str = "") -> None:
    config.ensure_dirs()
    shoot = shoot or config.DEFAULT_DEMO_SHOOT
    demo_dir = config.demo_dir(shoot)
    videos = sorted(demo_dir.glob("*.mp4"))
    if not videos:
        print(f"No demo assets in {demo_dir}.")
        print(f"Generate them first:  python ../../scripts/make_demo_assets.py {shoot}")
        sys.exit(1)

    project = Project(
        title=demo.SHOOT_TITLES.get(shoot, "Quick Judge Demo"),
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
        shoot = next((a for a in args[1:] if a in config.DEMO_SHOOTS), "")
        run_demo(use_adk="--adk" in args, shoot=shoot)
    else:
        print(f"usage: python -m app.cli demo [--adk] [{'|'.join(config.DEMO_SHOOTS)}]")
