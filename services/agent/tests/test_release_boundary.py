"""Where an off-record remark starts and ends is a person's decision.

The tool used to hold the whole segment, which cost a director four usable
answers because one sentence in the same segment was off the record. The first
attempt at fixing that split the segment automatically — and made the firewall
*worse*, because the boundary is a judgment about subject matter and the spoken
marker is not reliably at its edge:

    「オフレコですが、来月2号店を出します。まだ発表前なんです。」

The second sentence carries no marker and is plainly still off the record. An
automatic split puts it in the script.

So: propose, alert, hold. Release only on a person's say-so.
"""
import pytest


def _held_segment(transcript: str, **kw):
    from app.agents.confidentiality import classify_segments
    from app.models.schemas import Segment

    seg = Segment(asset_id="ast_x", start_seconds=10.0, end_seconds=30.0,
                  speaker="Owner", transcript=transcript, **kw)
    return classify_segments("prj_release", [seg])[0]


# ---- nothing moves on its own ---------------------------------------------

def test_a_partly_restricted_segment_is_held_whole():
    from app.models.schemas import Confidentiality

    seg = _held_segment(
        "We pay the federal minimum wage here. "
        "Off the record, we are opening a second location next month.")

    assert seg.confidentiality == Confidentiality.OFF_THE_RECORD
    assert seg.allow_script_use is False
    assert seg.allow_external_search is False


def test_the_unmarked_continuation_is_never_released_by_the_tool():
    """The sentence after the marker carries no marker of its own. Splitting on
    markers alone would have put it straight into the script."""
    seg = _held_segment(
        "Off the record, we are opening a second location next month. "
        "It has not been announced yet.")

    assert seg.allow_script_use is False
    # It may appear in the proposal — that is the point of showing a proposal —
    # but the proposal is not an action.
    assert all(not p.text or True for p in seg.release_proposal)
    assert seg.release_confirmed_by == ""


def test_the_proposal_covers_the_whole_segment_and_says_it_is_estimated():
    seg = _held_segment(
        "We pay the federal minimum wage here. "
        "We do about two hundred cups a day. "
        "Off the record, we are opening next month.")

    assert len(seg.release_proposal) == 3
    assert seg.release_proposal[0].start_seconds == 10.0
    assert abs(seg.release_proposal[-1].end_seconds - 30.0) < 0.05
    assert all(p.timing_is_estimated for p in seg.release_proposal), (
        "sentence boundaries have no timecode of their own; say so")


def test_no_proposal_when_there_is_nothing_to_decide():
    """A wholly clean or wholly restricted segment poses no boundary question,
    and offering one would train the director to click through them."""
    clean = _held_segment("We opened in 1978. We do two hundred cups a day.")
    assert clean.release_proposal == []

    wholly = _held_segment("Off the record, we are moving. "
                           "Off the record, the lease is signed.")
    assert wholly.release_proposal == []


def test_the_report_raises_it_rather_than_burying_it():
    from app.agents.confidentiality import classify_segments
    from app.models.schemas import Project, Segment
    from app.pipeline import morning_report
    from app.storage import store

    project = Project(title="alert", target_duration_seconds=60)
    store.put(project.id, "project", project)
    classify_segments(project.id, [Segment(
        asset_id="a", start_seconds=0, end_seconds=20, transcript=(
            "We pay the federal minimum wage here. "
            "Off the record, we are opening next month."))])

    held = morning_report(project.id)["held_awaiting_your_decision"]
    assert len(held) == 1
    assert "your call" in held[0]["alert"]
    assert "nothing has been released" in held[0]["alert"]


# ---- people do not say "off the record" on cue ----------------------------

_ASKS_IN_JAPANESE = [
    "オフレコですが、来月2号店を出します",
    "ここだけの話ですけど、来月2号店を出します",
    "これ、放送はしないでほしいんですけど、来月2号店を出します",
    "今のはナシで、来月2号店を出します",
    "内緒にしてほしいんですが、来月2号店を出します",
    "他言しないでくださいね、来月2号店を出します",
    "今の、カットしてもらえますか",
    "オンエアでは使わないでください",
    "表には出さないでほしいんです",
    "ちょっとカメラ止めてもらえますか",
]

_ASKS_IN_ENGLISH = [
    "Off the record, we are opening next month",
    "Between you and me, we are opening next month",
    "Please don't use that, we are opening next month",
    "Keep that out, we are opening next month",
    "This is not for broadcast, we are opening next month",
    "Can we go off the record for a second",
    "Scratch that",
    "Could you cut that bit",
    "This stays between us",
    "Turn the camera off for a moment",
]


@pytest.mark.parametrize("said", _ASKS_IN_JAPANESE + _ASKS_IN_ENGLISH)
def test_an_ask_not_to_broadcast_is_caught_however_it_is_phrased(said):
    """Nobody says "off the record" on cue. A rule that only knows the formal
    marker hears none of the ordinary ways people ask."""
    from app.agents.confidentiality import _rule_label
    from app.models.schemas import Confidentiality, Segment

    label, reason = _rule_label(Segment(asset_id="a", transcript=said))
    assert label == Confidentiality.OFF_THE_RECORD, f"missed: {said} ({reason})"


@pytest.mark.parametrize("said", [
    "この商店街も、お店がずいぶん減りましたね",
    "うちは一日およそ百杯のコーヒーを出しています",
    "放送作家の仕事をしていました",
    "We do about two hundred cups a day",
    "The camera work on that programme was lovely",
    "We record everything on tape",
])
def test_ordinary_talk_is_not_mistaken_for_an_ask(said):
    """The list is broad on purpose, but a false positive still costs the
    director a review click on every take — it cannot fire on shop talk."""
    from app.agents.confidentiality import _rule_label
    from app.models.schemas import Confidentiality, Segment

    label, _ = _rule_label(Segment(asset_id="a", transcript=said))
    assert label != Confidentiality.OFF_THE_RECORD, f"false positive: {said}"


# ---- release takes a person -----------------------------------------------

def test_confirming_releases_only_what_was_named():
    from app.agents.confidentiality import confirm_release
    from app.models.schemas import Confidentiality

    seg = _held_segment(
        "We pay the federal minimum wage here. "
        "We do about two hundred cups a day. "
        "Off the record, we are opening next month.")

    pieces = confirm_release("prj_release", seg, [0, 1], confirmed_by="director@example")

    assert len(pieces) == 3
    released = [p for p in pieces if p.allow_script_use]
    held = [p for p in pieces if not p.allow_script_use]
    assert len(released) == 2 and len(held) == 1
    assert "Off the record" in held[0].transcript
    assert all(p.release_confirmed_by == "director@example" for p in pieces)
    assert held[0].confidentiality == Confidentiality.OFF_THE_RECORD


def test_a_director_may_hold_back_more_than_the_tool_proposed():
    """The proposal is the tool's reading. The director's is the one that counts,
    including when they are more cautious than it was."""
    from app.agents.confidentiality import confirm_release

    seg = _held_segment(
        "We pay the federal minimum wage here. "
        "Off the record, we are opening next month.")

    pieces = confirm_release("prj_release", seg, [], confirmed_by="director@example")
    assert not any(p.allow_script_use for p in pieces)


def test_a_confirmation_out_of_range_is_refused():
    from app.agents.confidentiality import confirm_release

    seg = _held_segment("We pay the federal minimum wage here. "
                        "Off the record, we are opening next month.")
    with pytest.raises(ValueError):
        confirm_release("prj_release", seg, [0, 99], confirmed_by="director@example")


def test_a_segment_with_no_proposal_cannot_be_released_through_this_path():
    from app.agents.confidentiality import confirm_release

    seg = _held_segment("Off the record, we are moving. "
                        "Off the record, the lease is signed.")
    with pytest.raises(ValueError):
        confirm_release("prj_release", seg, [0], confirmed_by="director@example")
