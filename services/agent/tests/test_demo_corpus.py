"""Recording a demo must not publish other people's names.

The corpus exists so a public video can show the pipeline working without
putting real companies, headlines and URLs on screen. These pin the two things
that make it trustworthy rather than merely quiet: it goes through the same
rules as a live search, and no run using it can be mistaken for a live one.
"""
import json

import pytest

from app import config
from app.clients.parallel_client import ParallelClient


def _corpus_files():
    return sorted(config.corpus_dir().glob("*.json"))


def test_every_invented_host_is_a_reserved_name():
    """RFC 2606 reserves .example precisely so it can never resolve. A demo
    page on a name somebody could register is a demo page that could one day
    point at a real site."""
    assert _corpus_files(), "no corpus shipped"
    for path in _corpus_files():
        for page in json.loads(path.read_text(encoding="utf-8"))["pages"]:
            host = page["url"].split("/")[2]
            assert host.endswith(".example"), f"{path.name}: {host} is registrable"


def test_the_corpus_never_declares_its_own_standing():
    """What may be credited is decided from the URL, by code. If an entry could
    name itself a public authority, the demo would be showing a rule that does
    not exist outside it."""
    for path in _corpus_files():
        raw = json.loads(path.read_text(encoding="utf-8"))
        for page in raw["pages"]:
            assert "source_type" not in page
            assert set(page) <= {"match", "url", "title", "excerpt", "published_at"}


def test_an_invented_authority_is_classified_by_the_same_rule():
    assert ParallelClient._source_type(
        "https://www.labourstandards.gov.example/wages/minimum-wage") == "government"
    assert ParallelClient._source_type(
        "https://www.retailtradecouncil.example/research/store-count-2026") == "web"


def test_the_corpus_still_leaves_something_uncreditable():
    """The demo is worth recording only if it can still reach 'checked, but
    nobody to credit'. A corpus where every subject has an authority behind it
    would quietly delete the most honest thing the product does."""
    for path in _corpus_files():
        pages = json.loads(path.read_text(encoding="utf-8"))["pages"]
        kinds = {ParallelClient._source_type(p["url"]) for p in pages}
        assert "web" in kinds, f"{path.name}: every page is creditable"
        assert "government" in kinds, f"{path.name}: nothing is creditable"


def test_a_corpus_run_is_labelled_as_one(monkeypatch):
    """The trace and the Egress Log both read `provider`, so this one string is
    what stops a recording being presented as a live search."""
    monkeypatch.setattr(config, "SEARCH_CORPUS", "en")
    assert ParallelClient().provider == "demo-corpus"


def test_without_the_setting_nothing_changes(monkeypatch):
    monkeypatch.setattr(config, "SEARCH_CORPUS", "")
    assert ParallelClient().provider in ("parallel", "mock")


def test_a_subject_the_corpus_does_not_cover_returns_nothing(monkeypatch):
    """Silence is the honest answer. Returning a filler page would teach a
    viewer that everything gets confirmed."""
    monkeypatch.setattr(config, "SEARCH_CORPUS", "en")
    client = ParallelClient()
    assert client._corpus_search(["how long this shop has traded"]).pages == []


def test_a_covered_subject_returns_its_pages_once(monkeypatch):
    monkeypatch.setattr(config, "SEARCH_CORPUS", "en")
    pages = ParallelClient()._corpus_search(["federal minimum wage", "minimum wage rate"]).pages
    assert pages, "the corpus should answer the demo's own claims"
    urls = [p.url for p in pages]
    assert len(urls) == len(set(urls)), "one page must not arrive twice per claim"
    assert any(".gov.example" in u for u in urls)


@pytest.mark.parametrize("name", ["en", "ja"])
def test_both_shoots_have_a_corpus(name):
    assert (config.corpus_dir() / f"{name}.json").is_file()
