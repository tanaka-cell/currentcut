"""A caption must not be able to break the render.

The first English run died here: ffmpeg's drawtext takes its text inside a
single-quoted filter value, and "small businesses' share of the workforce"
closes that quote. No escaping reopens it. Japanese captions never hit it —
Japanese has no apostrophes — so it surfaced the moment the demo ran in English,
and it took the whole run down, not just the caption.
"""
import subprocess

import pytest

AWKWARD = [
    "small businesses' share of the private workforce",
    'He said "we are opening next month" on camera',
    "Rate: 8% — takeaway, 10% eat-in",
    r"C:\Users\path\like\this",
    "50%% of the time, it works every time",
    "コンビニは全国に約5万6000店（出典: www.stat.go.jp）",
    "Apostrophes, colons: commas, and 'quotes' all at once",
]


@pytest.mark.parametrize("caption", AWKWARD)
def test_ffmpeg_renders_the_caption(caption, tmp_path):
    from app.agents.rough_cut import _cut_clip
    from app.models.schemas import ScriptLine

    src = tmp_path / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=c=0x224466:s=320x180:d=2:r=30",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-shortest",
         str(src)], check=True)

    line = ScriptLine(project_id="p", order=0, source_in_seconds=0,
                      source_out_seconds=1.5, caption_text=caption)
    dst = tmp_path / "out.mp4"
    _cut_clip(src, line, dst, index=0)
    assert dst.exists() and dst.stat().st_size > 0


def test_a_long_caption_is_trimmed_to_fit_the_frame():
    """The burned-in caption is a preview aid; the caption sheet is the
    deliverable. A 200-character claim rendered on one line runs off the frame
    and reads as a broken tool."""
    from app.agents.rough_cut import CAPTION_CHARS, _fit_caption

    long = ("Small businesses' share of private workforce employment in the US: "
            "small businesses employ almost half of the private workforce in "
            "this country. (Source: advocacy.sba.gov)")
    got = _fit_caption(long)
    assert len(got) <= CAPTION_CHARS
    assert got.endswith("…")


def test_a_short_caption_is_left_exactly_as_it_is():
    from app.agents.rough_cut import _fit_caption

    assert _fit_caption("Federal minimum wage $7.25 (Source: dol.gov)") == \
        "Federal minimum wage $7.25 (Source: dol.gov)"
