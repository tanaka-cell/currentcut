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
        _cut_clip(Path(asset.storage_uri), line, clip, index=line.order)
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
    """Escape a path for use inside a drawtext option value."""
    return (text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
            .replace(",", "\\,").replace("%", "\\%"))


# The burned-in caption is a preview aid; the caption sheet is the deliverable.
# One line that fits the frame is the useful amount of it.
CAPTION_CHARS = 68

# The temp subtitle carries the spoken line, so it may wrap — but only so far.
SUBTITLE_MAX_LINES = 2
_SUB_WIDTH_SPACED = 54   # word-wrapped scripts (English)
_SUB_WIDTH_CJK = 27      # character-wrapped scripts; CJK glyphs are twice as wide


def _fit_caption(text: str) -> str:
    """Trim a data caption to one line — from the middle, never the end.

    The caption's payoff is its tail: "(Source: advocacy.sba.gov)". A plain
    tail-trim once rendered "…(So…" on screen, which cut the one thing this
    product adds. So when the text carries a bracketed source, the claim is
    shortened and the source survives whole.
    """
    text = " ".join(text.split())
    if len(text) <= CAPTION_CHARS:
        return text
    cut = max(text.rfind("("), text.rfind("（"))
    if cut > 0:
        suffix = text[cut:]
        room = CAPTION_CHARS - len(suffix) - 2
        if room >= 12:  # enough claim left to still mean something
            return text[:room].rstrip() + "… " + suffix
    return text[:CAPTION_CHARS - 1].rstrip() + "…"


def _is_cjk(text: str) -> bool:
    return any("　" <= ch <= "鿿" or "＀" <= ch <= "￯" for ch in text)


# A figure split across lines becomes a different figure: "10" / "%" reads as
# ten, "5万6" / "000店" reads as three numbers. Same rule the telop sheet
# enforces, applied to the burned subtitle.
_NUM = set("0123456789０１２３４５６７８９.,%％万億兆")
_TRAIL = set("店円人年歳件本社台か国")  # counters that belong to their figure


def _breaks_a_figure(before: str, after: str) -> bool:
    return before in _NUM and (after in _NUM or after in _TRAIL)


def _wrap_cjk(text: str, width: int) -> list[str]:
    """Character-wrap, backing the break off any figure it would split."""
    lines: list[str] = []
    while text:
        if len(text) <= width:
            lines.append(text)
            break
        cut = width
        while cut > width - 8 and _breaks_a_figure(text[cut - 1], text[cut]):
            cut -= 1
        lines.append(text[:cut])
        text = text[cut:]
    return lines


def _wrap_subtitle(text: str) -> str:
    """The spoken line, wrapped to at most two on-screen lines.

    English wraps at spaces; Japanese has none, so it wraps by character count.
    Anything past two lines is cut with an ellipsis — a preview subtitle that
    fills the frame stops being a subtitle.
    """
    text = " ".join(text.split())
    if not text:
        return ""
    if _is_cjk(text):
        lines = _wrap_cjk(text, _SUB_WIDTH_CJK)
    else:
        import textwrap
        lines = textwrap.wrap(text, width=_SUB_WIDTH_SPACED)
    if len(lines) > SUBTITLE_MAX_LINES:
        lines = lines[:SUBTITLE_MAX_LINES]
        lines[-1] = lines[-1].rstrip() + "…"
    return "\n".join(lines)


def _drawtext(text: str, out_dir: Path, name: str, *,
              fontsize: int, color: str, y: str) -> str:
    """One drawtext filter whose text comes from a file, never from the
    filter string.

    Escaping it inline is a losing game: an apostrophe closes the quoted value
    and no amount of backslashes reopens it, so "small businesses' share" failed
    the render outright and took the whole run with it. Japanese captions never
    hit this — Japanese has no apostrophes — so it surfaced the first time the
    demo ran in English.
    """
    if not text.strip():
        return ""
    font = Path(config.FONT_FILE)
    fontopt = f"fontfile='{_ff_escape(font.as_posix())}':" if font.exists() else ""
    text_file = out_dir / f"{name}.txt"
    # newline="\n" matters on Windows: text mode turns \n into \r\n, and
    # drawtext renders the carriage return as an extra empty line, doubling
    # the spacing between subtitle lines.
    text_file.write_text(text, encoding="utf-8", newline="\n")
    return (
        # expansion=none: drawtext treats % as a template marker ("Stray %"
        # warnings, and the glyph vanishes), and a tax-rate caption is exactly
        # the text that contains one. Nothing here needs templating.
        f",drawtext={fontopt}textfile='{_ff_escape(text_file.as_posix())}':"
        f"expansion=none:fontsize={fontsize}:fontcolor={color}:borderw=2:"
        f"bordercolor=black:x=(w-text_w)/2:y={y}:line_spacing=8"
    )


def _cut_clip(src: Path, line: ScriptLine, dst: Path, index: int = 0) -> None:
    duration = line.source_out_seconds - line.source_in_seconds
    # Two layers, two jobs. Bottom, white: the spoken line, so the preview is
    # watchable with the sound off. Above it, gold: the checked figure with its
    # source — the one moment this product exists for, made visible.
    vf = ("scale=1280:720:force_original_aspect_ratio=decrease,"
          "pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=30"
          + _drawtext(_wrap_subtitle(line.audio_text), dst.parent,
                      f"sub_{index:03d}", fontsize=30, color="white",
                      y="h-th-28")
          + _drawtext(_fit_caption(line.caption_text), dst.parent,
                      f"caption_{index:03d}", fontsize=32, color="0xFFD24A",
                      y="h-th-136"))
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
