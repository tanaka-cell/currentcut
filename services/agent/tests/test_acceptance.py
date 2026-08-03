"""Acceptance tests 1-3 (+5 partial) from the master brief, in mock mode."""
import json
from pathlib import Path


# ---- Test 1: off-record protection -----------------------------------------

def test_off_record_is_labeled_and_blocked(overnight_run):
    from app.models.schemas import Claim, Confidentiality, EgressLog, Segment
    from app.storage import store

    project_id, _ = overnight_run
    segments = store.list(project_id, "segments", Segment)
    off = [s for s in segments if "オフレコ" in s.transcript]
    assert off, "off-record segment must exist"
    for seg in off:
        assert seg.confidentiality == Confidentiality.OFF_THE_RECORD
        assert seg.allow_external_search is False
        assert seg.allow_script_use is False

    # No egress: nothing from the off-record segment was ever sent.
    off_ids = {s.id for s in off}
    egress = store.list(project_id, "egress_log", EgressLog)
    sent = [e for e in egress if e.segment_id in off_ids and e.status in ("sent", "completed")]
    assert not sent, "off-record content must never reach Parallel"
    # And claims from it are not searchable.
    for c in store.list(project_id, "claims", Claim):
        if c.segment_id in off_ids:
            assert c.allow_external_search is False
            assert c.safe_search_query is None


def test_off_record_not_in_script_or_cut(overnight_run):
    from app.models.schemas import ScriptLine, Segment
    from app.storage import store

    project_id, report = overnight_run
    segments = {s.id: s for s in store.list(project_id, "segments", Segment)}
    for line in store.list(project_id, "script_lines", ScriptLine):
        seg = segments.get(line.segment_id)
        assert seg is not None
        assert "オフレコ" not in line.audio_text
        assert "銀座" not in (line.audio_text + line.caption_text)

    edl = json.loads(Path(report["rough_cut"]["edl"]).read_text(encoding="utf-8"))
    off_ids = {s.id for s in segments.values() if "オフレコ" in s.transcript}
    lines_by_id = {l.id: l for l in store.list(project_id, "script_lines", ScriptLine)}
    for entry in edl:
        line = lines_by_id[entry["script_line_id"]]
        assert line.segment_id not in off_ids, "off-record segment leaked into the cut"
        assert "銀座" not in entry["caption"]


# ---- Test 2: public claim is verified through Parallel ----------------------

def test_public_claim_searched_with_sources(overnight_run):
    from app.models.schemas import Claim, EgressLog, ResearchResult, ScriptLine
    from app.storage import store

    project_id, _ = overnight_run
    claims = store.list(project_id, "claims", Claim)
    store_claims = [c for c in claims if c.claim_type == "store_count"]
    assert store_claims, "80店舗 must be extracted as a claim"
    claim = store_claims[0]
    assert claim.safe_search_query, "safe query must be generated"
    # The safe query must be keywords, not the spoken sentence.
    assert "あります" not in claim.safe_search_query
    assert "現在、全国に" not in claim.safe_search_query
    assert len(claim.safe_search_query) <= 60
    assert claim.verification_status.value.endswith("CONFIRMED")

    egress = store.list(project_id, "egress_log", EgressLog)
    assert any(e.claim_id == claim.id and e.status == "completed" for e in egress)
    assert all(e.raw_transcript_sent is False for e in egress)

    sources = [r for r in store.list(project_id, "research_results", ResearchResult)
               if r.claim_id == claim.id]
    assert sources, "sources must be saved"

    linked = [l for l in store.list(project_id, "script_lines", ScriptLine)
              if claim.id in l.claim_ids]
    assert linked, "script line must link to the claim"


def test_egress_log_is_append_only(overnight_run):
    """The attempt record must survive its own outcome record."""
    from app.models.schemas import EgressLog
    from app.storage import store

    project_id, _ = overnight_run
    egress = store.list(project_id, "egress_log", EgressLog)
    sent = [e for e in egress if e.status == "sent"]
    outcomes = [e for e in egress if e.phase == "outcome"]
    assert sent, "the pre-send record must not be overwritten by the outcome"
    assert outcomes, "an outcome record must be written"
    for outcome in outcomes:
        assert outcome.attempt_id, "outcome must link back to its attempt"
        assert any(e.id == outcome.attempt_id for e in egress)
    assert len({e.id for e in egress}) == len(egress), "ids must be unique"


def test_captions_only_cite_supporting_sources(overnight_run):
    """A source judged not to support the claim must never be printed as 出典."""
    from app.models.schemas import Claim, ResearchResult, ScriptLine
    from app.storage import store

    project_id, _ = overnight_run
    results = store.list(project_id, "research_results", ResearchResult)
    claims = {c.id: c for c in store.list(project_id, "claims", Claim)}
    non_supporting_domains = {r.source_domain for r in results if not r.supports_claim}
    supporting_domains = {r.source_domain for r in results if r.supports_claim}
    only_bad = non_supporting_domains - supporting_domains

    for line in store.list(project_id, "script_lines", ScriptLine):
        if "出典" not in line.caption_text:
            continue
        for domain in only_bad:
            assert domain not in line.caption_text, (
                f"cited {domain}, which was judged not to support the claim")
        # and the cited claim must really be confirmed
        cited = [claims[cid] for cid in line.claim_ids if cid in claims]
        assert any(c.verification_status.value.endswith("CONFIRMED") for c in cited)


# ---- Test 3: every factual line is grounded ---------------------------------

def test_script_lines_are_grounded(overnight_run):
    from app.models.schemas import EvidenceStatus, ScriptLine
    from app.storage import store

    project_id, _ = overnight_run
    for line in store.list(project_id, "script_lines", ScriptLine):
        grounded = bool(line.segment_id) or bool(line.claim_ids) \
            or line.evidence_status == EvidenceStatus.EDITORIAL_LANGUAGE
        assert grounded, f"ungrounded assertion in line {line.id}"


# ---- Test 5 (partial): rough cut artifacts ----------------------------------

def test_rough_cut_artifacts(overnight_run):
    project_id, report = overnight_run
    cut = report["rough_cut"]
    assert Path(cut["mp4"]).exists() and Path(cut["mp4"]).stat().st_size > 0
    assert Path(cut["srt"]).exists()
    edl = json.loads(Path(cut["edl"]).read_text(encoding="utf-8"))
    assert edl == sorted(edl, key=lambda e: e["order"])
    assert cut["lines_used"] == len(edl)
