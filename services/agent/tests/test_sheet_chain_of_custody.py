"""A caption order sheet is executed row by row, by someone who was not there.

Found by an outside reviewer reading the workbook the demo produced: the data
telop for 「Nearly all convenience stores sell coffee」 carried "do not use this
figure as spoken", while the quote-follow carrying the same sentence sat one row
below marked "as recorded" with no note at all. An edit house working down that
sheet would have put the disputed figure on screen — the exact outcome the
column exists to prevent.

These pin the chain from research judgment to the row an operator types.
"""
import pytest

from app import lang
from app.agents import telop
from app.agents.telop_sheet import _checked_cell
from app.models.schemas import (
    Claim, EvidenceStatus, ResearchResult, ScriptLine, Segment, TelopEntry,
)


def _line(text: str, claim_ids: list[str]) -> ScriptLine:
    return ScriptLine(project_id="p", order=0, start_seconds=0, end_seconds=4,
                      audio_text=text, claim_ids=claim_ids, segment_id="seg1")


def _segment() -> Segment:
    return Segment(id="seg1", project_id="p", asset_id="a", start_seconds=0,
                   end_seconds=4, transcript="", shot_type="interview",
                   speaker="Shop Owner")


def _claim(status: EvidenceStatus, text: str) -> Claim:
    return Claim(id="clm1", project_id="p", segment_id="seg1", claim_text=text,
                 display_text=text, verification_status=status)


def _entries(status: EvidenceStatus, spoken: str, results=None):
    claim = _claim(status, spoken)
    return telop._entries_for_line(
        "p", _line(spoken, [claim.id]), _segment(), {claim.id: claim},
        {claim.id: results or []}, named=set(), language=lang.EN)


def test_the_quote_of_a_disputed_figure_is_warned_too():
    out = _entries(EvidenceStatus.CONFLICTING, "Nearly all of them sell coffee.")
    quotes = [e for e in out if e.telop_type == "comment"]
    assert quotes, "the spoken line produced no quote-follow"
    assert "⚠" in quotes[0].caution
    assert "do not caption it as fact" in quotes[0].caution.lower()


def test_an_undisputed_quote_carries_no_warning():
    """The warning has to mean something. If every quote-follow carried it,
    an operator would stop reading the column."""
    out = _entries(EvidenceStatus.MULTIPLE_SOURCES_CONFIRMED,
                   "We pay the federal minimum wage here.")
    quotes = [e for e in out if e.telop_type == "comment"]
    assert quotes and quotes[0].caution == ""


def test_the_checked_against_cell_names_what_was_checked():
    entry = TelopEntry(project_id="p", evidence_status=EvidenceStatus.MULTIPLE_SOURCES_CONFIRMED,
                       checked_against=["labour.gov.example", "wagewatch.example"])
    cell = _checked_cell(entry, {"MULTIPLE_SOURCES_CONFIRMED": "multiple sources"})
    assert "multiple sources" in cell
    assert "labour.gov.example" in cell and "wagewatch.example" in cell


def test_a_verdict_with_nothing_behind_it_stays_a_verdict_alone():
    entry = TelopEntry(project_id="p", evidence_status=EvidenceStatus.FOOTAGE_CONFIRMED)
    assert _checked_cell(entry, {"FOOTAGE_CONFIRMED": "as recorded"}) == "as recorded"


@pytest.mark.parametrize("text", ["Mhm.", "mhm", "Yeah.", "yeah", "Um,", "うん", "はい"])
def test_backchannel_is_not_ordered_as_a_caption(text):
    out = telop._entries_for_line(
        "p", _line(text, []), _segment(), {}, {}, named={"Shop Owner"}, language=lang.EN)
    assert not [e for e in out if e.telop_type == "comment"], f"{text!r} was ordered"


@pytest.mark.parametrize("text", [
    "Yeah, we opened in 1978.",       # begins like a backchannel, is not one
    "Right now it is $7.25.",
    "はい、父が始めた店です",
])
def test_a_line_that_says_something_is_kept(text):
    out = telop._entries_for_line(
        "p", _line(text, []), _segment(), {}, {}, named={"Shop Owner"}, language=lang.EN)
    assert [e for e in out if e.telop_type == "comment"], f"{text!r} was dropped"


def test_notes_are_joined_in_the_language_of_the_sheet():
    """An English sheet was printing 「／」 between two English sentences."""
    assert lang.join_notes(lang.EN, "first", "second") == "first · second"
    assert lang.join_notes(lang.JA, "一つ目", "二つ目") == "一つ目／二つ目"
    assert lang.join_notes(lang.EN, "", "only") == "only"


def test_the_sheet_instruction_sends_the_reader_to_every_warning():
    """The quote-follow warning lives in 備考, so an instruction that names only
    the 裏付け column would walk the reader straight past it."""
    for language in (lang.JA, lang.EN):
        instruction = lang.sheet(lang.SHEET_WARNING, language)
        assert "⚠" in instruction
        # It also has to fit the header cell it is printed in; the first
        # version ran past the merge and printed "...confirm the figure before".
        assert len(instruction) <= 80, instruction
