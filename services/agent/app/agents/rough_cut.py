"""Rough Cut Agent — ScriptLines → EDL JSON + FFmpeg preview MP4 + SRT.

Deliberately a *rough* cut: hard cuts, burned-in temp captions, source audio.
Restricted segments are excluded upstream (scriptwriter) and re-checked here.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .. import config
from ..models.schemas import Asset, Confidentiality, ScriptLine
from ..storage import store

_RESTRICTED = (Confidentiality.CONFIDENTIAL, Confidentiality.OFF_THE_RECORD,
               Confidentiality.PERSONAL_DATA, Confidentiality.NEEDS_HUMAN_REVIEW)


def render_rough_cut(project_id: str, lines: list[ScriptLine], assets: list[Asset],
                     out_dir: Path | None = None) -> dict:
    out_dir = Path(out_dir) if out_dir else (config.OUTPUT_DIR / project_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    assets_by_id = {a.id: a for a in assets}

    # Defense in depth: refuse restricted lines even if upstream let one through.
    safe_lines = [l for l in lines if l.confidentiality not in _RESTRICTED]

    clip_paths: list[Path] = []
    edl = []
    for line in safe_lines:
        asset = assets_by_id.get(line.asset_id)
        if asset is None:
            continue
        clip = out_dir / f"clip_{line.order:03d}.mp4"
        _cut_clip(Path(asset.storage_uri), line, clip)
        clip_paths.append(clip)
        edl.append({
            "order": line.order,
            "script_line_id": line.id,
            "asset_id": line.asset_id,
            "asset_file": asset.filename,
            "in_seconds": line.source_in_seconds,
            "out_seconds": line.source_out_seconds,
            "caption": line.caption_text,
            "evidence_status": line.evidence_status.value,
        })

    if not clip_paths:
        raise RuntimeError("No airable script lines to render")

    mp4_path = out_dir / "rough_cut.mp4"
    _concat(clip_paths, mp4_path)
    srt_path = out_dir / "rough_cut.srt"
    srt_path.write_text(_srt(safe_lines), encoding="utf-8")
    edl_path = out_dir / "edl.json"
    edl_path.write_text(json.dumps(edl, ensure_ascii=False, indent=1), encoding="utf-8")

    for clip in clip_paths:
        clip.unlink(missing_ok=True)

    result = {
        "mp4": str(mp4_path), "srt": str(srt_path), "edl": str(edl_path),
        "duration_seconds": round(sum(l.end_seconds - l.start_seconds for l in safe_lines), 1),
        "lines_used": len(safe_lines),
        "lines_excluded_confidential": len(lines) - len(safe_lines),
    }
    (out_dir / "rough_cut_meta.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


def _ff_escape(text: str) -> str:
    """Escape a string for use inside a drawtext option value."""
    return (text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
            .replace(",", "\\,").replace("%", "\\%"))


def _drawtext_caption(text: str) -> str:
    if not text:
        return ""
    font = Path(config.FONT_FILE)
    fontopt = f"fontfile='{_ff_escape(font.as_posix())}':" if font.exists() else ""
    return (
        f",drawtext={fontopt}text='{_ff_escape(text)}':fontsize=36:fontcolor=white:borderw=2:"
        f"bordercolor=black:x=(w-text_w)/2:y=h-90"
    )


def _cut_clip(src: Path, line: ScriptLine, dst: Path) -> None:
    duration = line.source_out_seconds - line.source_in_seconds
    vf = "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=30" \
         + _drawtext_caption(line.caption_text)
    subprocess.run(
        [config.FFMPEG, "-y", "-loglevel", "error",
         "-ss", f"{line.source_in_seconds:.3f}", "-t", f"{duration:.3f}", "-i", str(src),
         "-vf", vf,
         "-af", "aresample=48000",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-c:a", "aac", "-ar", "48000", "-ac", "2",
         str(dst)],
        check=True,
    )


def _concat(clips: list[Path], dst: Path) -> None:
    list_file = dst.with_suffix(".txt")
    list_file.write_text(
        "\n".join(f"file '{c.as_posix()}'" for c in clips), encoding="utf-8")
    subprocess.run(
        [config.FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(list_file), "-c", "copy", str(dst)],
        check=True,
    )
    list_file.unlink(missing_ok=True)


def _ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _srt(lines: list[ScriptLine]) -> str:
    blocks = []
    n = 1
    for line in lines:
        text = line.caption_text or line.audio_text
        if not text:
            continue
        blocks.append(f"{n}\n{_ts(line.start_seconds)} --> {_ts(line.end_seconds)}\n{text}\n")
        n += 1
    return "\n".join(blocks)
