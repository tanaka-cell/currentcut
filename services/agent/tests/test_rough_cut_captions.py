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
    # The claim is shortened; the source — the caption's whole point — is not.
    assert got.endswith("(Source: advocacy.sba.gov)")
    assert "…" in got


def test_a_long_caption_without_a_source_is_tail_trimmed():
    from app.agents.rough_cut import CAPTION_CHARS, _fit_caption

    long = "A" * 100
    got = _fit_caption(long)
    assert len(got) <= CAPTION_CHARS
    assert got.endswith("…")


def test_a_short_caption_is_left_exactly_as_it_is():
    from app.agents.rough_cut import _fit_caption

    assert _fit_caption("Federal minimum wage $7.25 (Source: dol.gov)") == \
        "Federal minimum wage $7.25 (Source: dol.gov)"


def test_spoken_english_wraps_at_words_to_two_lines():
    from app.agents.rough_cut import SUBTITLE_MAX_LINES, _wrap_subtitle

    spoken = ("Small businesses employ almost half of the private workforce in "
              "this country, and that is a number people underestimate every "
              "single time they talk about the economy on television.")
    got = _wrap_subtitle(spoken)
    lines = got.split("\n")
    assert len(lines) <= SUBTITLE_MAX_LINES
    assert got.endswith("…")
    assert all(not l.startswith(" ") for l in lines)  # wrapped at spaces


def test_spoken_japanese_wraps_by_characters():
    from app.agents.rough_cut import _wrap_subtitle

    spoken = "うちも持ち帰りは8%で、店内で召し上がりのお客様は10%をいただいています。それが今の決まりですから。"
    got = _wrap_subtitle(spoken)
    lines = got.split("\n")
    assert len(lines) == 2
    assert all(len(l) <= 28 for l in lines)


def test_a_short_spoken_line_stays_on_one_line():
    from app.agents.rough_cut import _wrap_subtitle

    assert _wrap_subtitle("We opened in 1978.") == "We opened in 1978."


def test_japanese_wrap_never_splits_a_figure():
    """"10" at the end of one line and "%" at the start of the next reads as
    ten — the same rule the telop sheet enforces applies to the subtitle."""
    from app.agents.rough_cut import _breaks_a_figure, _wrap_subtitle

    got = _wrap_subtitle(
        "うちも持ち帰りは8%で、店内で召し上がりのお客様は10%をいただいています。それが今の決まりですから。")
    lines = got.split("\n")
    for a, b in zip(lines, lines[1:]):
        assert not _breaks_a_figure(a[-1], b[0]), f"figure split across {a!r} / {b!r}"
    assert "10%" in got.replace("\n", "")  # the figure survived intact


def test_speaker_description_is_not_burned_in_as_a_caption():
    """Gemini's speaker field is a description ("Man in apron"), and a
    description where a name super belongs reads as a mistake. The spoken line
    is the subtitle now; the caption slot is for checked figures only."""
    from app.agents.scriptwriter import _caption_for
    from app.models.schemas import Segment

    seg = Segment(asset_id="a", speaker="Man in apron", shot_type="interview",
                  transcript="We do about 200 cups a day.")
    assert _caption_for(seg, None, {}) == ""


def test_a_trimmed_claim_stops_at_a_word():
    """Mid-word looks like a rendering fault, not an ellipsis. Seen on the
    landing page's own hero frame: "the federal minimum wage hasn't change…"."""
    from app.agents.rough_cut import _fit_caption

    got = _fit_caption("The federal minimum wage hasn't changed since 2009. "
                       "(Source: labour.gov.example)")
    assert got == "The federal minimum wage hasn't… (Source: labour.gov.example)"
    claim = got.split("…")[0]
    assert not claim.endswith(" ")
    assert claim.split()[-1] == "hasn't", "the last word must be a whole word"


def test_the_source_still_survives_whole():
    from app.agents.rough_cut import _fit_caption

    got = _fit_caption("Small businesses employ almost half of the private "
                       "workforce in this country. (Source: smallbiz.gov.example)")
    assert got.endswith("(Source: smallbiz.gov.example)")


def test_a_script_without_spaces_still_trims():
    """Japanese has no word boundaries; a straight cut is how it reads."""
    from app.agents.rough_cut import CAPTION_CHARS, _fit_caption

    long_ja = "日本のお持ち帰り商品に対する消費税は8%であり店内飲食では10%が適用される" * 3
    got = _fit_caption(long_ja + "（出典: www.nta.go.jp）")
    assert got.endswith("（出典: www.nta.go.jp）")
    assert len(got) <= CAPTION_CHARS + 2


def test_a_boundary_that_would_gut_the_line_is_ignored():
    """One very long token should not collapse the caption to nothing."""
    from app.agents.rough_cut import _fit_caption

    got = _fit_caption("Supercalifragilisticexpialidociousness abounds here "
                       "and everywhere always (Source: x.example)")
    claim = got.split("…")[0]
    assert len(claim) > 20, f"trimmed to {claim!r}"


def test_a_trimmed_caption_does_not_stop_on_a_dangling_word():
    """The hero frame of the landing page read "…is $7.25 an…", stopping on the
    article and leaving the reader waiting for "hour". Stopping on the figure
    is what the line was for."""
    from app.agents.rough_cut import _fit_caption

    got = _fit_caption("The federal minimum wage is $7.25 an hour. "
                       "(Source: labour.gov.example)")
    assert got == "The federal minimum wage is $7.25… (Source: labour.gov.example)"


def test_the_source_still_survives_the_trim_whole():
    """The reason for trimming from the middle in the first place."""
    from app.agents.rough_cut import _fit_caption

    got = _fit_caption("Small businesses employ almost half of the private "
                       "workforce in this country. (Source: smallbiz.gov.example)")
    assert got.endswith("(Source: smallbiz.gov.example)")
    assert "…" in got


def test_trimming_never_eats_the_whole_claim():
    """A line of nothing but dangling words must not collapse to an ellipsis."""
    from app.agents.rough_cut import _clip

    assert _clip("the value of the share of the total", 30).strip("… ")


def test_a_caption_that_fits_is_left_alone():
    from app.agents.rough_cut import _fit_caption

    short = "There are more than 150,000 convenience stores in this country now."
    assert _fit_caption(short) == short
