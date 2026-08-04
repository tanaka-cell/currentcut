"""An English-language shoot must come out as an English deliverable.

CurrentCut was built against Japanese broadcast practice, and that practice hid
inside things that looked neutral — a thirteen-character caption line, a note to
the director written in Japanese, a 出典 column. The contest judges run the demo
in English, so every one of those has to follow the footage instead of being
assumed.
"""


# ---- detection -------------------------------------------------------------

def test_language_follows_the_footage():
    from app.lang import EN, JA, detect

    assert detect("We have eighty stores across the country") == EN
    assert detect("現在、全国に80店舗あります") == JA
    assert detect("Our 店舗 count") == JA, "any kana or han makes it a Japanese shoot"
    assert detect("") == EN


# ---- what the director reads ----------------------------------------------

def test_notes_are_written_in_the_language_of_the_shoot(overnight_run_en):
    """A note is for the person holding the order sheet. On an English shoot
    that person does not read 自店の数字."""
    from app.models.schemas import Claim, TelopEntry
    from app.storage import store
    from app.lang import detect, EN

    project_id, _ = overnight_run_en
    notes = [c.volatility_note for c in store.list(project_id, "claims", Claim)
             if c.volatility_note]
    cautions = [e.caution for e in store.list(project_id, "telops", TelopEntry)
                if e.caution]
    assert notes or cautions, "the shoot contains unverifiable figures; some note must appear"
    for text in notes + cautions:
        assert detect(text) == EN, f"Japanese text on an English shoot: {text}"


def test_captions_use_the_english_line_length(overnight_run_en):
    """Thirteen full-width characters is a Japanese telop. An English lower
    third runs to about thirty, and wrapping it at thirteen would produce a
    sheet no operator would accept."""
    from app.lang import CAPTION_LIMITS, EN
    from app.models.schemas import TelopEntry
    from app.storage import store

    project_id, _ = overnight_run_en
    entries = store.list(project_id, "telops", TelopEntry)
    assert entries
    limit = CAPTION_LIMITS[EN]["max_chars"]
    longest = max(len(line) for e in entries for line in e.text_lines)
    assert longest > CAPTION_LIMITS["ja"]["max_chars"], (
        "at least one English caption should exceed the Japanese limit — "
        "otherwise this test would pass under the old wrapping too")
    for e in entries:
        for line in e.text_lines:
            assert len(line) <= limit or e.caution, (
                f"over-long line with no caution: {line}")


def test_english_captions_do_not_use_full_width_separators(overnight_run_en):
    """The full-width space is how Japanese telops separate phrases. In English
    it is an invisible character that breaks the operator's find-and-replace."""
    from app.models.schemas import TelopEntry
    from app.storage import store

    project_id, _ = overnight_run_en
    for e in store.list(project_id, "telops", TelopEntry):
        joined = "".join(e.text_lines)
        assert "　" not in joined, f"full-width space in an English caption: {joined}"


# ---- the guarantees still hold in English ---------------------------------

def test_off_record_still_never_leaves_on_an_english_shoot(overnight_run_en):
    """The confidentiality rules carry English patterns as well as Japanese
    ones; this is the check that they actually fire."""
    from app.models.schemas import Confidentiality, EgressLog, ScriptLine, Segment
    from app.storage import store

    project_id, _ = overnight_run_en
    segments = store.list(project_id, "segments", Segment)
    off = [s for s in segments if "off the record" in s.transcript.lower()]
    assert off, "the English shoot must contain an off-record remark"
    for seg in off:
        assert seg.confidentiality == Confidentiality.OFF_THE_RECORD
        assert seg.allow_external_search is False
        assert seg.allow_script_use is False

    off_ids = {s.id for s in off}
    sent = [e for e in store.list(project_id, "egress_log", EgressLog)
            if e.segment_id in off_ids and e.status in ("sent", "completed")]
    assert not sent, "off-record content must never reach the search API"

    for line in store.list(project_id, "script_lines", ScriptLine):
        assert line.segment_id not in off_ids
        assert "Brooklyn" not in (line.audio_text + line.caption_text)


def test_the_script_carries_the_spoken_english(overnight_run_en):
    from app.models.schemas import ScriptLine
    from app.storage import store

    project_id, _ = overnight_run_en
    spoken = [l.audio_text for l in store.list(project_id, "script_lines", ScriptLine)
              if l.audio_text.strip()]
    assert spoken, "an interview shoot must produce spoken lines"
    assert any("eighty stores" in s for s in spoken)


# ---- the egress gate must measure a quotation, not a language -------------

def test_an_honest_english_keyword_query_is_not_a_transcript_leak():
    """The gate rejected any 12-character run of the transcript. In Japanese
    that is a clause; in English "federal minim" is 13 characters, so every
    honest keyword query about what the speaker just said was refused and three
    US public-record claims went unchecked — with the log reporting a leak that
    had not happened."""
    from app.lang import quotes_transcript

    said = ("We pay the federal minimum wage here, seven dollars and twenty-five "
            "cents an hour. It has not changed since two thousand nine.")
    assert not quotes_transcript("federal minimum wage 7.25 dollar", said)
    assert not quotes_transcript("US Department of Labor federal minimum wage", said)


def test_a_quoted_english_sentence_is_still_a_leak():
    """Loosening the unit must not loosen the rule."""
    from app.lang import quotes_transcript

    said = ("We pay the federal minimum wage here, seven dollars and twenty-five "
            "cents an hour.")
    assert quotes_transcript("we pay the federal minimum wage here", said)
    assert quotes_transcript(
        "why do they pay the federal minimum wage here seven dollars", said)


def test_the_japanese_gate_is_unchanged():
    from app.lang import quotes_transcript

    said = "コンビニエンスストアは、いま全国におよそ五万六千店あります。"
    assert quotes_transcript("いま全国におよそ五万六千店", said)
    assert not quotes_transcript("コンビニ 店舗数 全国 5万6千", said)


def test_a_short_utterance_cannot_be_leaked_by_a_keyword():
    """Nothing under the span length can trip the rule on its own."""
    from app.lang import quotes_transcript

    assert not quotes_transcript("coffee prices 2026", "It is hot.")
    assert not quotes_transcript("コーヒー 価格", "暑いね")


# ---- the cache must not serve one shoot's reading for another -------------

def test_identical_media_with_different_ground_truth_does_not_collide(workdir):
    """The analysis cache was keyed on the media hash alone. In mock mode the
    reading comes from the sidecar, so two clips with identical video and
    different sidecars shared one entry — and the English shoot came back with
    the Japanese shoot's transcripts, silently, in a passing test suite."""
    import json
    import subprocess

    from app.agents import footage_logger
    from app.models.schemas import Asset

    d = workdir / "collide"
    d.mkdir(exist_ok=True)
    made = []
    for name, transcript in (("a", "We have eighty stores"), ("b", "現在、全国に80店舗")):
        mp4 = d / f"{name}.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-f", "lavfi", "-i", "color=c=0x224466:s=320x180:d=2:r=30",
             "-c:v", "libx264", "-preset", "veryfast", str(mp4)], check=True)
        mp4.with_suffix(".mp4.analysis.json").write_text(json.dumps({"segments": [
            {"start_seconds": 0, "end_seconds": 2, "speaker": "x",
             "transcript": transcript, "visual_summary": "v",
             "shot_type": "interview", "usability_score": 0.9}]}), encoding="utf-8")
        made.append(mp4)

    a, b = (footage_logger.register_asset("prj_collide", m) for m in made)
    assert a.hash == b.hash, "the two clips must be byte-identical for this to test anything"
    assert footage_logger._cache_key(a) != footage_logger._cache_key(b)

    seg_a = footage_logger.analyze_asset("prj_collide", a)
    seg_b = footage_logger.analyze_asset("prj_collide", b)
    assert seg_a[0].transcript == "We have eighty stores"
    assert seg_b[0].transcript == "現在、全国に80店舗"


# ---- an abbreviation is not a sentence end --------------------------------

def test_an_abbreviation_is_not_mistaken_for_a_sentence_end():
    """Sentence boundaries feed the release proposal (test_release_boundary.py),
    so a stray split inside "U.S. Department of Labor" would offer the director
    a boundary that is not one."""
    from app.agents.confidentiality import _sentences

    got = _sentences("The U.S. Department of Labor sets it. "
                     "Off the record, we are moving.")
    assert len(got) == 2, got
    assert "Department of Labor" in got[0]


# ---- public authorities outside Japan -------------------------------------

def test_government_domains_are_recognised_beyond_japan():
    """A US shoot cites dol.gov and census.gov; a UK one cites gov.uk. Without
    these the citation rule silently credits nobody on any shoot but a Japanese
    one, because only .go.jp counted as a public authority."""
    from app.clients.parallel_client import ParallelClient as P

    for url in ("https://www.dol.gov/agencies/whd/minimum-wage",
                "https://www.census.gov/programs-surveys/cbp.html",
                "https://www.sba.gov/advocacy",
                "https://www.gov.uk/vat-rates",
                "https://ec.europa.eu/eurostat",
                "https://www.stat.go.jp/data"):
        assert P._source_type(url) == "government", url

    for url in ("https://www.nikkei.com/article/x",
                "https://www.bengo4.com/c_1/n_1/",
                "https://www.prnewswire.com/news-releases/x",
                "https://stripe.com/guides/tax",
                "https://en.wikipedia.org/wiki/Coffee"):
        assert P._source_type(url) != "government", url
