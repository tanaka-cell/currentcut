"""What has to hold when a night's rushes arrive instead of nine short clips.

App modules are imported inside the tests, not at the top: config reads its
paths from the environment at import time, and the workdir fixture sets that
environment. Importing here would freeze the data directory to the repository's
own before any test could redirect it — which is how a real run's analysis
cache ends up answering a unit test.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest


# ---------- running many calls at once ----------

def test_fan_out_keeps_input_order():
    from app.fanout import fan_out
    assert fan_out([3, 1, 2], lambda n: n * 10) == [30, 10, 20]


def test_fan_out_actually_overlaps():
    """Six half-second calls must not take three seconds."""
    from app.fanout import fan_out
    started = time.monotonic()
    fan_out(range(6), lambda _: time.sleep(0.5), workers=6)
    assert time.monotonic() - started < 1.5


def test_fan_out_reports_progress_as_each_lands():
    from app.fanout import fan_out
    seen = []
    fan_out([0.4, 0.01], lambda d: (time.sleep(d), d)[1],
            workers=2, on_result=lambda item, _: seen.append(item))
    assert seen == [0.01, 0.4]  # completion order, not submission order


def test_fan_out_raises_the_first_failure():
    from app.fanout import fan_out

    def explode(n):
        if n in (1, 2):
            raise ValueError(f"item {n}")
        return n

    with pytest.raises(ValueError, match="item 1"):
        fan_out([0, 1, 2, 3], explode)


def test_fan_out_empty_is_not_an_error():
    from app.fanout import fan_out
    assert fan_out([], lambda x: x) == []


def test_fan_out_single_lane_still_runs_everything():
    from app.fanout import fan_out
    assert fan_out([1, 2, 3], lambda n: n + 1, workers=1) == [2, 3, 4]


# ---------- splitting a long take ----------

@pytest.fixture
def long_take(tmp_path, workdir) -> Path:
    """A take long enough to need splitting, built from the demo footage."""
    from app import config

    src = sorted((config.DEMO_ASSETS_DIR / "en").glob("*.mp4"))
    if not src:
        pytest.skip("demo footage not present")
    listing = tmp_path / "list.txt"
    listing.write_text(
        "".join(f"file '{p.as_posix()}'\n" for p in src * 12), encoding="utf-8")
    dest = tmp_path / "long_take.mp4"
    subprocess.run(
        [config.FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(listing), "-c", "copy", str(dest)],
        check=True, capture_output=True)
    return dest


def test_short_take_is_not_split(long_take):
    from app.agents import footage_logger

    duration = footage_logger.probe_duration(long_take)
    assert footage_logger.plan_chunks(long_take, duration, duration + 1) == []


def test_long_take_is_split_into_covering_pieces(long_take):
    from app.agents import footage_logger

    duration = footage_logger.probe_duration(long_take)
    chunks = footage_logger.plan_chunks(long_take, duration, 120)
    assert len(chunks) > 1
    # Contiguous, in order, and covering the whole take: a gap is footage that
    # silently never gets watched.
    assert chunks[0][0] == pytest.approx(0, abs=0.5)
    assert chunks[-1][1] == pytest.approx(duration, abs=0.5)
    for (_, end), (next_start, _) in zip(chunks, chunks[1:]):
        assert next_start == pytest.approx(end, abs=0.001)


def test_chunk_starts_exactly_where_it_claims(long_take, tmp_path):
    """The timecode we report is the one a director uses to find the moment.

    A stream copy can only cut on a keyframe, so a boundary chosen anywhere
    else silently shifts every timecode in that piece.
    """
    from app import config
    from app.agents import footage_logger

    duration = footage_logger.probe_duration(long_take)
    chunks = footage_logger.plan_chunks(long_take, duration, 120)
    start, end = chunks[1]

    piece = footage_logger._extract_chunk(long_take, start, end, tmp_path / "p.mp4")

    from_piece = tmp_path / "a.jpg"
    from_source = tmp_path / "b.jpg"
    subprocess.run([config.FFMPEG, "-y", "-loglevel", "error", "-i", str(piece),
                    "-frames:v", "1", "-q:v", "2", str(from_piece)],
                   check=True, capture_output=True)
    subprocess.run([config.FFMPEG, "-y", "-loglevel", "error", "-ss", f"{start:.6f}",
                    "-i", str(long_take), "-frames:v", "1", "-q:v", "2", str(from_source)],
                   check=True, capture_output=True)
    assert from_piece.read_bytes() == from_source.read_bytes()


def test_a_plan_is_never_a_single_piece(long_take):
    """The bug this exists for: a take just over the threshold produced one
    piece covering the whole file — a copy of the take, made to read the take."""
    from app.agents import footage_logger

    duration = footage_logger.probe_duration(long_take)
    for target in range(30, int(duration) + 60, 30):
        chunks = footage_logger.plan_chunks(long_take, duration, target)
        assert len(chunks) != 1, f"target={target}s planned a pointless single piece"
        if chunks:
            assert chunks[-1][1] == pytest.approx(duration, abs=0.5)


def test_a_take_just_over_the_threshold_is_split_or_left_whole(long_take):
    from app.agents import footage_logger

    duration = footage_logger.probe_duration(long_take)
    chunks = footage_logger.plan_chunks(long_take, duration, duration * 0.8)
    # Either two real pieces, or read whole — never one piece pretending.
    assert len(chunks) in (0, 2)


# ---------- readings that describe footage that is not there ----------

def _reading(*spans):
    return {"segments": [{"start_seconds": a, "end_seconds": b, "transcript": "x"}
                         for a, b in spans]}


def test_a_segment_past_the_end_of_the_footage_is_dropped():
    from app.agents.footage_logger import within_length

    out = within_length(_reading((0, 5), (700, 705), (1140, 1145)), 720.0)
    assert [s["start_seconds"] for s in out["segments"]] == [0, 700]
    assert out["segments_dropped_out_of_range"] == 1


def test_an_end_that_overshoots_is_trimmed_to_the_footage():
    from app.agents.footage_logger import within_length

    out = within_length(_reading((700, 900)), 720.0)
    assert out["segments"][0]["end_seconds"] == 720.0


def test_a_reading_entirely_inside_the_footage_is_untouched():
    from app.agents.footage_logger import within_length

    out = within_length(_reading((0, 5), (5, 10)), 720.0)
    assert out["segments_dropped_out_of_range"] == 0
    assert [s["end_seconds"] for s in out["segments"]] == [5, 10]


def test_a_take_with_no_keyframes_to_cut_on_is_read_whole(tmp_path, workdir):
    from app import config
    from app.agents import footage_logger

    still = tmp_path / "still.mp4"
    subprocess.run(
        [config.FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "color=c=black:s=320x240:d=30", "-c:v", "libx264",
         "-g", "10000", "-pix_fmt", "yuv420p", str(still)],
        check=True, capture_output=True)
    assert footage_logger.plan_chunks(still, 30.0, 5) == []
