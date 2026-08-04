"""Footage Logger Agent — understands each asset via Gemini video analysis."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from .. import config, progress
from ..clients.gemini_client import VIDEO_PROMPT_STRICT, gemini
from ..fanout import fan_out
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


def _keyframe_times(path: Path) -> list[float]:
    """Where a stream copy can cut this file without re-encoding.

    Cheap enough to do on the real thing: a 29-minute file lists its 240
    keyframes in under two seconds, because the index is read rather than the
    video decoded.
    """
    out = subprocess.run(
        [config.FFPROBE, "-v", "error", "-select_streams", "v", "-skip_frame", "nokey",
         "-show_entries", "frame=pts_time", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=False,
    )
    times = []
    for row in out.stdout.splitlines():
        row = row.strip().rstrip(",")
        try:
            times.append(float(row))
        except ValueError:
            continue
    return sorted(times)


def plan_chunks(path: Path, duration: float, target_seconds: float) -> list[tuple[float, float]]:
    """Split points for a long take, always landing on a keyframe.

    Cutting anywhere else means either re-encoding the whole shoot or handing
    the model a piece whose first frame is not where we think it is — and the
    timecode we report is the one a director trusts to find the moment again.
    Chosen this way, a chunk's first frame is byte-identical to the source at
    that timestamp.

    Returns [] when the file is short enough to read whole, or when it has too
    few keyframes to divide — a file that cannot be cut cleanly is better read
    in one piece than cut wrongly.
    """
    if duration <= target_seconds:
        return []
    keys = _keyframe_times(path)
    if len(keys) < 2:
        return []

    bounds = [keys[0]]
    for t in keys[1:]:
        if t - bounds[-1] >= target_seconds:
            bounds.append(t)
    # The remainder after the last boundary is the final piece. If it is only a
    # sliver, it joins the piece before it instead of becoming a chunk of its own.
    if len(bounds) > 1 and duration - bounds[-1] < target_seconds / 4:
        bounds.pop()
    pieces = [(bounds[i], bounds[i + 1] if i + 1 < len(bounds) else duration)
              for i in range(len(bounds))]
    # A plan of one piece is the whole file with extra steps: it would copy the
    # take out of itself before reading it. Say "no split" instead — the first
    # version of this returned exactly that for any take just over the
    # threshold, and a twelve-minute take was silently never divided.
    return pieces if len(pieces) > 1 else []


def _extract_chunk(src: Path, start: float, end: float, dest: Path) -> Path:
    subprocess.run(
        [config.FFMPEG, "-y", "-loglevel", "error", "-ss", f"{start:.6f}",
         "-to", f"{end:.6f}", "-i", str(src), "-c", "copy",
         "-avoid_negative_ts", "make_zero", str(dest)],
        check=True, capture_output=True,
    )
    return dest


def within_length(raw: dict, duration: float, *, label: str = "") -> dict:
    """Drop readings that fall outside the footage they claim to describe.

    Asked to log twelve minutes, the model returned segments running to
    nineteen — timecodes for footage that does not exist. Downstream nothing
    questions a timecode: the cut seeks to it, the caption sheet prints it, and
    a director is sent to a point on the tape that is past the end of it.

    So the file's own duration is the authority. An end that overshoots is
    trimmed back; a segment that begins past the end is not trimmed to nothing
    but dropped, and the count of dropped ones is recorded rather than passed
    over in silence.
    """
    kept, dropped = [], 0
    for seg in raw.get("segments", []):
        start = float(seg.get("start_seconds", 0) or 0)
        end = float(seg.get("end_seconds", 0) or 0)
        if start >= duration or start < 0:
            dropped += 1
            continue
        seg["start_seconds"] = start
        seg["end_seconds"] = min(end, duration) if end > start else min(start + 1.0, duration)
        kept.append(seg)
    if dropped:
        print(f"[footage_logger] {label or 'take'}: dropped {dropped} segment(s) "
              f"timed past the end of {duration:.1f}s of footage")
    return {"segments": kept, "segments_dropped_out_of_range": dropped}


def _read_video(path: Path, cache_key: str) -> dict:
    """One reading of one file, cached, with the too-coarse retry."""
    cache_dir = config.DATA_DIR / "_analysis_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{cache_key}.{gemini.provider}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    raw = json.loads(gemini.analyze_video(path).model_dump_json())
    if not gemini.mock and coarsest_segment(raw) > 1:
        try:
            retry = json.loads(gemini.analyze_video(
                path, prompt=VIDEO_PROMPT_STRICT).model_dump_json())
            # Keep whichever reading is finer. A retry that comes back just
            # as coarse is not an improvement to prefer blindly.
            if coarsest_segment(retry) < coarsest_segment(raw):
                raw = retry
        except Exception:
            pass  # the coarse reading is still a reading; carry on with it
    cache_file.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return raw


def _analyze_in_chunks(project_id: str, asset: Asset,
                       chunks: list[tuple[float, float]]) -> dict:
    """Read a long take in pieces, concurrently, and put the clock back.

    Each piece is cut out only while it is being read and deleted immediately
    after: on Cloud Run the filesystem is memory, so keeping every piece of a
    three-hour take alongside the take itself would double the largest thing we
    hold. Peak cost is the pieces in flight, which is what the lane count is for.
    """
    src = Path(asset.storage_uri)
    work_dir = config.OUTPUT_DIR / project_id / "_chunks"
    work_dir.mkdir(parents=True, exist_ok=True)
    total = len(chunks)

    def read_one(indexed: tuple[int, tuple[float, float]]) -> list[dict]:
        i, (start, end) = indexed
        dest = work_dir / f"{asset.id}_{i:04d}{src.suffix}"
        progress.emit(project_id, "footage_logger", "running",
                      f"{asset.filename} — reading {_clock(start)}–{_clock(end)}"
                      f" ({i + 1}/{total})")
        try:
            _extract_chunk(src, start, end, dest)
            key = hashlib.sha256(
                f"{_cache_key(asset)}|{start:.3f}|{end:.3f}".encode()).hexdigest()[:16]
            raw = within_length(_read_video(dest, key), end - start,
                                label=f"{asset.filename} {_clock(start)}–{_clock(end)}")
        finally:
            dest.unlink(missing_ok=True)
        # Timecodes come back relative to the piece; the director needs them
        # relative to the tape.
        for seg in raw.get("segments", []):
            seg["start_seconds"] = seg.get("start_seconds", 0) + start
            seg["end_seconds"] = seg.get("end_seconds", 0) + start
        return raw.get("segments", [])

    parts = fan_out(list(enumerate(chunks)), read_one)
    merged: list[dict] = []
    for segs in parts:
        merged.extend(segs)
    merged.sort(key=lambda s: s.get("start_seconds", 0))
    return {"segments": merged}


def _clock(seconds: float) -> str:
    m, s = divmod(int(max(0, seconds)), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def analyze_asset(project_id: str, asset: Asset) -> list[Segment]:
    """Analyze one asset, reusing an earlier reading of the same input.

    A reading that lumps several sentences into one segment is rejected and
    asked for again, once. Gemini returns per-utterance segments most of the
    time and a single blob occasionally; accepting whichever arrives is what
    made the demo's output swing between four sourced claims and almost none.

    A take longer than the chunk size is read in pieces. Mock mode never
    splits: its answer comes from a sidecar written for the whole file, so a
    piece of it has no ground truth to be read against.
    """
    chunks = ([] if gemini.mock else
              plan_chunks(Path(asset.storage_uri), asset.duration_seconds,
                          config.ANALYSIS_CHUNK_MINUTES * 60))
    if chunks:
        raw = _analyze_in_chunks(project_id, asset, chunks)
    else:
        raw = within_length(_read_video(Path(asset.storage_uri), _cache_key(asset)),
                            asset.duration_seconds, label=asset.filename)

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
