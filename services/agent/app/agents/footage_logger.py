"""Footage Logger Agent — understands each asset via Gemini video analysis."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from .. import config
from ..clients.gemini_client import VIDEO_PROMPT_STRICT, gemini
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


# 。？！ end a sentence on their own — Japanese puts no space after them. A full
# stop only ends one when something follows it that is not more number: "$7.25
# an hour" is one sentence, not two.
_SENTENCE_END = re.compile(r"[。？！]|[.?!](?:\s|$)")


def _sentences_in(transcript: str) -> int:
    return len(_SENTENCE_END.findall(transcript.strip()))


def coarsest_segment(raw: dict) -> int:
    """How many sentences of speech the largest single segment swallowed.

    One is fine. More means the model returned several utterances under one
    timecode, and downstream that is not cosmetic: clearance is granted per
    segment, so a whole interview in one segment is cleared or held as a block.
    On one run that turned a five-answer interview into nothing, because the
    last sentence was off the record.
    """
    return max((_sentences_in(s.get("transcript", "")) for s in raw.get("segments", [])),
               default=0)


def analyze_asset(project_id: str, asset: Asset) -> list[Segment]:
    """Analyze one asset, reusing an earlier reading of the same input.

    A reading that lumps several sentences into one segment is rejected and
    asked for again, once. Gemini returns per-utterance segments most of the
    time and a single blob occasionally; accepting whichever arrives is what
    made the demo's output swing between four sourced claims and almost none.
    """
    cache_dir = config.DATA_DIR / "_analysis_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{_cache_key(asset)}.{gemini.provider}.json"

    if cache_file.exists():
        raw = json.loads(cache_file.read_text(encoding="utf-8"))
    else:
        raw = json.loads(gemini.analyze_video(asset.storage_uri).model_dump_json())
        if not gemini.mock and coarsest_segment(raw) > 1:
            try:
                retry = json.loads(gemini.analyze_video(
                    asset.storage_uri, prompt=VIDEO_PROMPT_STRICT).model_dump_json())
                # Keep whichever reading is finer. A retry that comes back just
                # as coarse is not an improvement to prefer blindly.
                if coarsest_segment(retry) < coarsest_segment(raw):
                    raw = retry
            except Exception:
                pass  # the coarse reading is still a reading; carry on with it
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
