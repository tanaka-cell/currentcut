"""Footage Logger Agent — understands each asset via Gemini video analysis."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from .. import config
from ..clients.gemini_client import gemini
from ..models.schemas import Asset, Segment
from ..storage import store


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        [config.FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def register_asset(project_id: str, video_path: str | Path) -> Asset:
    path = Path(video_path).resolve()
    asset = Asset(
        project_id=project_id,
        filename=path.name,
        storage_uri=str(path),
        duration_seconds=probe_duration(path),
        hash=file_hash(path),
    )
    store.put(project_id, "assets", asset)
    return asset


def _cache_key(asset: Asset) -> str:
    """Everything that determines the analysis, not just the media.

    Keying on the media hash alone is wrong in two ways. In mock mode the answer
    comes from the `.analysis.json` sidecar, so two clips with identical video
    and different sidecars collide — which is how an English shoot silently came
    back with the Japanese shoot's transcripts. And in real mode the answer
    depends on which model watched it, so a model change must not be served the
    old model's reading.
    """
    parts = [asset.hash, gemini.provider]
    if gemini.mock:
        sidecar = Path(asset.storage_uri + ".analysis.json")
        parts.append(file_hash(sidecar) if sidecar.exists() else "no-sidecar")
    else:
        parts.append(config.GEMINI_VIDEO_MODEL)
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def analyze_asset(project_id: str, asset: Asset) -> list[Segment]:
    """Analyze one asset, reusing an earlier reading of the same input."""
    cache_dir = config.DATA_DIR / "_analysis_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{_cache_key(asset)}.{gemini.provider}.json"

    if cache_file.exists():
        raw = json.loads(cache_file.read_text(encoding="utf-8"))
    else:
        analysis = gemini.analyze_video(asset.storage_uri)
        raw = json.loads(analysis.model_dump_json())
        cache_file.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    segments = [
        Segment(
            asset_id=asset.id,
            start_seconds=s["start_seconds"],
            end_seconds=s["end_seconds"],
            speaker=s.get("speaker", ""),
            transcript=s.get("transcript", ""),
            visual_summary=s.get("visual_summary", ""),
            shot_type=s.get("shot_type", "other"),
            usability_score=s.get("usability_score", 0.5),
        )
        for s in raw["segments"]
    ]
    store.put_many(project_id, "segments", segments)
    asset.analysis_status = "analyzed"
    store.put(project_id, "assets", asset)
    return segments
