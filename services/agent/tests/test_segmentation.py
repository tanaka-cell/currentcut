"""How the footage is cut up decides how much of it survives.

Clearance is granted per segment and a claim inherits its segment's clearance,
so a whole interview returned under one timecode is cleared or held as a block.
On one run Gemini returned a 39-second interview as a single segment, its last
sentence was off the record, and a five-answer interview produced nothing.

Across three English runs the demo gave 0, 2 and 4 sourced claims, and this was
the largest cause. A judge presses the button once.
"""


def _analysis(*transcripts):
    """A reading that fits inside the clip it describes.

    One second per segment: the clips these are read against are a couple of
    seconds long, and five-second segments put the second utterance of a
    two-second clip at 5–10s — a timecode for footage that does not exist.
    The logger drops those now, so the fixture has to be physically possible.
    """
    return {"segments": [
        {"start_seconds": i, "end_seconds": i + 1, "speaker": "Owner",
         "transcript": t, "visual_summary": "v", "shot_type": "interview",
         "usability_score": 0.9}
        for i, t in enumerate(transcripts)]}


# ---- recognising a reading that cannot be used ----------------------------

def test_a_segment_holding_several_sentences_is_coarse():
    from app.agents.footage_logger import coarsest_segment

    assert coarsest_segment(_analysis(
        "We pay the federal minimum wage here. "
        "We do two hundred cups a day. "
        "Off the record, we are opening next month.")) == 3


def test_one_sentence_per_segment_is_what_we_want():
    from app.agents.footage_logger import coarsest_segment

    assert coarsest_segment(_analysis(
        "We pay the federal minimum wage here.",
        "Off the record, we are opening next month.")) == 1


def test_silent_footage_is_not_coarse():
    from app.agents.footage_logger import coarsest_segment

    assert coarsest_segment(_analysis("", "")) == 0


def test_a_decimal_point_is_not_a_sentence_end():
    from app.agents.footage_logger import coarsest_segment

    assert coarsest_segment(_analysis("We pay $7.25 an hour.")) == 1


def test_japanese_sentences_are_counted_too():
    from app.agents.footage_logger import coarsest_segment

    assert coarsest_segment(_analysis(
        "うちは一日およそ百杯です。この十年で三割ほど減りました。")) == 2


# ---- asking again, once ---------------------------------------------------

def _asset(tmp_path, seconds: float):
    """A clip unlike any other test's.

    The analysis cache is keyed on the media, and correctly so — identical
    footage is the same footage. Tests that build the same colour bars for the
    same duration therefore share one cache entry, and the second one silently
    reads the first one's answer instead of exercising anything. Vary the media.
    """
    import subprocess

    from app.agents import footage_logger

    mp4 = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", f"color=c=0x224466:s=320x180:d={seconds}:r=30",
         "-c:v", "libx264", "-preset", "veryfast", str(mp4)], check=True)
    return footage_logger.register_asset("prj_seg", mp4)


def test_a_coarse_reading_is_asked_for_again(tmp_path, monkeypatch, workdir):
    from app.agents import footage_logger
    from app.clients.gemini_client import VIDEO_PROMPT_STRICT, VideoAnalysis

    asset = _asset(tmp_path, 2.0)
    calls = []

    def _analyze(path, prompt=""):
        calls.append(prompt)
        if len(calls) == 1:
            return VideoAnalysis.model_validate(_analysis(
                "We pay the federal minimum wage here. Off the record, we are moving."))
        return VideoAnalysis.model_validate(_analysis(
            "We pay the federal minimum wage here.",
            "Off the record, we are moving."))

    monkeypatch.setattr(footage_logger.gemini, "mock", False)
    monkeypatch.setattr(footage_logger.gemini, "analyze_video", _analyze)

    segments = footage_logger.analyze_asset("prj_seg", asset)

    assert len(calls) == 2, "a coarse reading must be challenged, not accepted"
    assert calls[1] == VIDEO_PROMPT_STRICT
    assert len(segments) == 2
    assert all("Off the record" not in s.transcript
               for s in segments if "minimum wage" in s.transcript)


def test_a_fine_reading_is_not_asked_for_twice(tmp_path, monkeypatch, workdir):
    """The retry costs a video analysis — the most expensive call in the run."""
    from app.agents import footage_logger
    from app.clients.gemini_client import VideoAnalysis

    asset = _asset(tmp_path, 2.5)
    calls = []

    def _analyze(path, prompt=""):
        calls.append(prompt)
        return VideoAnalysis.model_validate(_analysis(
            "We pay the federal minimum wage here.",
            "Off the record, we are moving."))

    monkeypatch.setattr(footage_logger.gemini, "mock", False)
    monkeypatch.setattr(footage_logger.gemini, "analyze_video", _analyze)

    footage_logger.analyze_asset("prj_seg", asset)
    assert len(calls) == 1


def test_a_retry_that_is_no_better_is_not_preferred(tmp_path, monkeypatch, workdir):
    """Second is not the same as better. Keep whichever reading is finer."""
    from app.agents import footage_logger
    from app.clients.gemini_client import VideoAnalysis

    asset = _asset(tmp_path, 3.0)
    readings = [
        _analysis("One. Two.", "Three."),          # coarsest = 2
        _analysis("One. Two. Three."),             # coarsest = 3 — worse
    ]

    def _analyze(path, prompt=""):
        return VideoAnalysis.model_validate(readings.pop(0))

    monkeypatch.setattr(footage_logger.gemini, "mock", False)
    monkeypatch.setattr(footage_logger.gemini, "analyze_video", _analyze)

    segments = footage_logger.analyze_asset("prj_seg", asset)
    assert len(segments) == 2, "the first, finer reading should have been kept"


def test_a_failed_retry_leaves_the_first_reading_standing(tmp_path, monkeypatch, workdir):
    """A coarse reading is still a reading; an API error must not lose the clip."""
    from app.agents import footage_logger
    from app.clients.gemini_client import VideoAnalysis

    asset = _asset(tmp_path, 3.5)
    calls = []

    def _analyze(path, prompt=""):
        calls.append(prompt)
        if len(calls) == 1:
            return VideoAnalysis.model_validate(_analysis("One. Two."))
        raise RuntimeError("503")

    monkeypatch.setattr(footage_logger.gemini, "mock", False)
    monkeypatch.setattr(footage_logger.gemini, "analyze_video", _analyze)

    segments = footage_logger.analyze_asset("prj_seg", asset)
    assert len(segments) == 1 and "One. Two." in segments[0].transcript
