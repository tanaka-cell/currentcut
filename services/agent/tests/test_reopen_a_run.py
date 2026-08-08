"""The promise is that you hand the footage over and go. So you have to be able
to come back.

Until now the only way to see a night's work was to sit and watch it finish.
Close the tab and the run was gone — the endpoints still held every deliverable,
but nothing in the page would show them again. For a product whose entire pitch
is "rest after the shoot", that was the one journey it did not support.
"""
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "app" / "static" / "index.html"


@pytest.fixture(scope="module")
def page_source() -> str:
    return STATIC.read_text(encoding="utf-8")


def test_the_page_reads_a_project_from_the_url(page_source):
    assert "URLSearchParams(location.search).get('project')" in page_source


def test_it_loads_that_project_rather_than_the_bundled_sample(page_source):
    """A reopened run must show the director's own night, not the demo sample —
    the two look alike on screen and only one is theirs."""
    reopen = page_source.split("Come back to a run")[1][:900]
    assert "loadResults(liveSrc(wanted))" in reopen
    assert "SAMPLE_SRC" not in reopen


def test_a_bad_id_does_not_leave_the_page_pointing_at_it(page_source):
    """projectId drives the caption-sheet download and the template upload. If a
    mistyped id stayed set, the next thing the visitor clicked would 404."""
    reopen = page_source.split("Come back to a run")[1][:900]
    assert "projectId = null" in reopen


def test_the_deliverable_links_are_built_from_the_project_id(page_source):
    """Reopening is only useful if what it reopens is downloadable."""
    for path in ("telop-manuscript.xlsx", "telops.csv", "rough_cut.mp4"):
        assert path in page_source
