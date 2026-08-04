"""What may be checked, what may be sent, and what an outage may look like.

These pin the three failures that made the demo produce a first cut with no
sourced line at all: a statutory rate treated as the speaker's private figure,
a search that never retrieved the page stating the number, and a transient API
error that read exactly like "nothing supports this claim".
"""
import pytest


# ---- verifiability decides what is searched --------------------------------

def _extract_with_labels(monkeypatch, labelled):
    """Run the extractor over one public segment with the labels the model gave."""
    from app.agents import claims as claims_agent
    from app.models.schemas import Confidentiality, Segment

    segment = Segment(asset_id="ast_x", allow_external_search=True,
                      confidentiality=Confidentiality.PUBLIC,
                      transcript="うちも、お持ち帰りは八パーセントの消費税をいただいています。"
                                 "うちは一日およそ百杯。この商店街も店が減りましたね。")
    monkeypatch.setattr(claims_agent.gemini, "mock", False)
    monkeypatch.setattr(claims_agent.gemini, "structured", lambda *a, **kw: claims_agent._LlmClaims(
        claims=[claims_agent._LlmClaim(
            claim_text=text, claim_subject="", claim_type="stat",
            verifiability=label, safe_search_query=f"q {text}",
            publisher_search_query=f"publisher {text}") for text, label in labelled]))
    return claims_agent.extract_claims("prj_test", [segment])


def test_only_public_record_claims_are_searched(monkeypatch):
    """A statutory rate spoken in the first person ("we charge 8% on takeaway")
    is the national reduced rate, not the shop's private figure. Filing it under
    the speaker's own numbers is what removed the one claim with a government
    source behind it — and the other two kinds must still reach the telop sheet."""
    from app.models.schemas import Verifiability

    claims = _extract_with_labels(monkeypatch, [
        ("消費税の軽減税率は8%", "public_record"),
        ("青葉珈琲店は一日およそ百杯", "own_business"),
        ("この商店街の店が減った", "unidentified_subject"),
    ])

    by_kind = {c.verifiability: c for c in claims}
    assert len(claims) == 3, "unverifiable claims still belong on the telop sheet"

    public = by_kind[Verifiability.PUBLIC_RECORD]
    assert public.allow_external_search is True
    assert public.safe_search_query and public.extra_search_queries

    for kind in (Verifiability.OWN_BUSINESS, Verifiability.UNIDENTIFIED_SUBJECT):
        claim = by_kind[kind]
        assert claim.allow_external_search is False
        assert claim.safe_search_query is None
        assert claim.extra_search_queries == [], "a blocked claim leaks nothing"
        assert "話者の発言として表記" in claim.volatility_note


def test_unknown_verifiability_falls_back_to_unsearchable():
    from app.agents import claims as claims_agent
    from app.models.schemas import Verifiability

    assert claims_agent._verifiability("something-else") is Verifiability.UNIDENTIFIED_SUBJECT
    assert claims_agent._verifiability("") is Verifiability.UNIDENTIFIED_SUBJECT


def test_the_two_unverifiable_kinds_are_told_apart(monkeypatch):
    """"Nobody publishes our takings" and "you never said which street" are
    different problems, and the caption the director writes differs."""
    from app.models.schemas import Verifiability

    claims = _extract_with_labels(monkeypatch, [
        ("青葉珈琲店は一日およそ百杯", "own_business"),
        ("この商店街の店が減った", "unidentified_subject"),
    ])
    notes = {c.verifiability: c.volatility_note for c in claims}
    assert "自店の数字" in notes[Verifiability.OWN_BUSINESS]
    assert "対象が特定できない" in notes[Verifiability.UNIDENTIFIED_SUBJECT]


# ---- every outbound query passes the gate, including the new one -----------

def test_publisher_query_is_gated_too(monkeypatch):
    """The publisher-targeted query is a second thing leaving the building. It
    must clear the same gate, or the firewall has a hole beside the door."""
    from app.clients import parallel_client
    from app.clients.parallel_client import EgressBlocked, parallel
    from app.models.schemas import Claim, Confidentiality, Segment

    segment = Segment(asset_id="ast_x", transcript="来月から二号店を出す話が進んでいます",
                      confidentiality=Confidentiality.PUBLIC, allow_external_search=True)
    claim = Claim(segment_id=segment.id, claim_text="c", allow_external_search=True,
                  safe_search_query="コンビニ 店舗数 全国",
                  # smuggles a run of the transcript out
                  extra_search_queries=["来月から二号店を出す話が進んでいます"])

    monkeypatch.setattr(parallel_client.parallel, "mock", True)
    with pytest.raises(EgressBlocked):
        parallel.search_for_claim("prj_test", claim, segment)


def test_search_objective_is_built_from_queries_not_the_claim(monkeypatch):
    """The objective is outbound text too. Building it from the claim would send
    the transcript out through a field nobody was watching."""
    from app.clients.parallel_client import parallel

    sent = {}

    class _FakeSDK:
        def search(self, **kwargs):
            sent.update(kwargs)
            return type("R", (), {"results": []})()

    monkeypatch.setattr(type(parallel), "_sdk_client", _FakeSDK())
    monkeypatch.setattr(parallel, "mock", False)

    from app.models.schemas import Claim, Confidentiality, Segment
    segment = Segment(asset_id="ast_x", transcript="いま全国におよそ五万六千店あります",
                      confidentiality=Confidentiality.PUBLIC, allow_external_search=True)
    claim = Claim(segment_id=segment.id,
                  claim_text="コンビニエンスストアは全国におよそ五万六千店あります",
                  allow_external_search=True,
                  safe_search_query="コンビニ 店舗数 全国",
                  extra_search_queries=["日本フランチャイズチェーン協会 統計調査"])
    parallel.calls_this_run = 0
    parallel.search_for_claim("prj_test", claim, segment)

    assert sent["search_queries"] == ["コンビニ 店舗数 全国", "日本フランチャイズチェーン協会 統計調査"]
    assert "五万六千店" not in sent["objective"]
    assert "あります" not in sent["objective"]
    # Without a text budget the API returns snippets too short to hold the figure.
    assert sent["max_chars_total"] > 0


# ---- an outage is not a finding --------------------------------------------

def test_failed_verification_is_reported_as_unchecked_not_unsupported(monkeypatch):
    from app.agents import evidence
    from app.models.schemas import Claim, ResearchResult

    monkeypatch.setattr(evidence.gemini, "mock", False)
    monkeypatch.setattr(evidence, "_JUDGE_BACKOFF_SECONDS", 0)

    calls = {"n": 0}

    def _boom(*a, **kw):
        calls["n"] += 1
        raise RuntimeError("503 Service Unavailable")

    monkeypatch.setattr(evidence.gemini, "structured", _boom)

    claim = Claim(segment_id="seg_x", claim_text="c")
    results = [ResearchResult(claim_id=claim.id, source_url="https://example.go.jp/a")]
    judgments = evidence.judge_all(claim, results)

    assert calls["n"] == evidence._JUDGE_ATTEMPTS, "a transient failure must be retried"
    assert not evidence.supports(judgments[0]), "an outage must never become support"
    assert evidence.did_not_run(judgments[0])
    assert "503" in judgments[0].reason


def test_a_reply_that_lands_on_no_source_is_retried(monkeypatch):
    """A 200 carrying verdicts that fit nowhere is the same outage in different
    clothes. Accepting it once cost a claim its evidence in a live run."""
    from app.agents import evidence
    from app.models.schemas import Claim, ResearchResult

    monkeypatch.setattr(evidence.gemini, "mock", False)
    monkeypatch.setattr(evidence, "_JUDGE_BACKOFF_SECONDS", 0)

    calls = {"n": 0}

    def _useless_then_good(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return evidence._BatchJudgments(judgments=[])  # lands on nothing
        return evidence._BatchJudgments(judgments=[_verdict(), _verdict()])

    monkeypatch.setattr(evidence.gemini, "structured", _useless_then_good)

    claim = Claim(segment_id="seg_x", claim_text="c")
    results = [ResearchResult(claim_id=claim.id, source_url=f"https://e.go.jp/{i}")
               for i in range(2)]
    judgments = evidence.judge_all(claim, results)

    assert calls["n"] == 2, "an unusable reply must be retried, not accepted"
    assert all(map(evidence.supports, judgments))


def test_research_records_the_outage_on_the_claim(monkeypatch):
    from app.agents import evidence, research
    from app.clients import parallel_client
    from app.models.schemas import Claim, Confidentiality, ResearchResult, Segment

    segment = Segment(asset_id="ast_x", transcript="全国におよそ五万六千店あります",
                      confidentiality=Confidentiality.PUBLIC, allow_external_search=True)
    claim = Claim(segment_id=segment.id, claim_text="コンビニは全国に約5万6千店",
                  allow_external_search=True, safe_search_query="コンビニ 店舗数")

    monkeypatch.setattr(parallel_client.parallel, "mock", True)
    monkeypatch.setattr(
        evidence, "judge_all",
        lambda c, rs: [evidence._failed_judgment("RuntimeError: 503") for _ in rs])
    monkeypatch.setattr(
        research.parallel, "search_for_claim",
        lambda *a, **kw: [ResearchResult(claim_id=claim.id, source_url="https://x.go.jp/a")])

    research.research_claims("prj_test", [claim], [segment])
    assert claim.verification_error, "the director must see that the check did not run"
    assert "503" in claim.verification_error


def test_partial_verification_is_not_treated_as_an_outage(monkeypatch):
    """One source failing to judge must not mark the whole claim unchecked."""
    from app.agents import evidence, research
    from app.clients import parallel_client
    from app.models.schemas import Claim, Confidentiality, ResearchResult, Segment

    segment = Segment(asset_id="ast_x", transcript="全国におよそ五万六千店あります",
                      confidentiality=Confidentiality.PUBLIC, allow_external_search=True)
    claim = Claim(segment_id=segment.id, claim_text="コンビニは全国に約5万6千店",
                  allow_external_search=True, safe_search_query="コンビニ 店舗数")
    results = [ResearchResult(claim_id=claim.id, source_url="https://a.go.jp/a"),
               ResearchResult(claim_id=claim.id, source_url="https://b.go.jp/b")]

    monkeypatch.setattr(parallel_client.parallel, "mock", True)
    monkeypatch.setattr(evidence, "judge_all", lambda c, rs: [
        evidence.EvidenceJudgment(entity_match=True, attribute_match=True,
                                  value_match=True, source_is_primary=True,
                                  source_value="5万5979店", reason="ok"),
        evidence._failed_judgment("RuntimeError: 503"),
    ])
    monkeypatch.setattr(research.parallel, "search_for_claim", lambda *a, **kw: results)

    research.research_claims("prj_test", [claim], [segment])
    assert claim.verification_error == ""
    assert claim.verification_status.value.endswith("CONFIRMED")


# ---- a matching figure from years ago is not confirmation ------------------

def _research_with(monkeypatch, judgments, results):
    from app.agents import evidence, research
    from app.clients import parallel_client
    from app.models.schemas import Claim, Confidentiality, Segment

    segment = Segment(asset_id="ast_x", transcript="いま全国におよそ五万六千店あります",
                      confidentiality=Confidentiality.PUBLIC, allow_external_search=True)
    claim = Claim(segment_id=segment.id, claim_text="コンビニは全国に約5万6千店",
                  claim_type="store_count", allow_external_search=True,
                  safe_search_query="コンビニ 店舗数")
    for r in results:
        r.claim_id = claim.id
    monkeypatch.setattr(parallel_client.parallel, "mock", True)
    monkeypatch.setattr(evidence, "judge_all", lambda c, rs: judgments)
    monkeypatch.setattr(research.parallel, "search_for_claim", lambda *a, **kw: results)
    research.research_claims("prj_test", [claim], [segment])
    return claim


def _match(year, primary=True):
    from app.agents.evidence import EvidenceJudgment
    return EvidenceJudgment(entity_match=True, attribute_match=True, value_match=True,
                            source_is_primary=primary, source_value="55,774",
                            value_as_of_year=year, reason="ok")


def test_a_decade_old_figure_does_not_confirm_a_present_tense_claim(monkeypatch):
    """"There are about 56,000 of them now" is not settled by a 2014 count that
    happens to round the same way. The source is real, the match is real, and it
    still must not put CONFIRMED on screen."""
    from app.models.schemas import ResearchResult

    claim = _research_with(
        monkeypatch, [_match(2014), _match(2014)],
        [ResearchResult(claim_id="", source_url="https://www.jil.go.jp/a"),
         ResearchResult(claim_id="", source_url="https://www.jil.go.jp/b")])

    assert not claim.verification_status.value.endswith("CONFIRMED")
    assert "2014年の数値" in claim.volatility_note
    assert claim.recheck_before_lock is True


def test_a_recent_figure_still_confirms(monkeypatch):
    from datetime import datetime, timezone

    from app.models.schemas import ResearchResult

    this_year = datetime.now(timezone.utc).year
    claim = _research_with(
        monkeypatch, [_match(this_year)],
        [ResearchResult(claim_id="", source_url="https://www.stat.go.jp/a")])
    assert claim.verification_status.value.endswith("CONFIRMED")


def test_a_source_with_no_stated_year_is_not_assumed_stale(monkeypatch):
    """Absence of a date is not evidence of age."""
    from app.models.schemas import ResearchResult

    claim = _research_with(
        monkeypatch, [_match(0)],
        [ResearchResult(claim_id="", source_url="https://www.stat.go.jp/a")])
    assert claim.verification_status.value.endswith("CONFIRMED")


# ---- batching must not blur the sources together ---------------------------

def _verdict(index=-1, supports=True):
    from app.agents.evidence import _BatchJudgment
    return _BatchJudgment(source_index=index, entity_match=supports,
                          attribute_match=supports, value_match=supports, reason="v")


def test_verdicts_without_an_index_still_reach_their_sources():
    """The model routinely omits source_index. Keying on it discarded every
    verdict in the batch, and a full set of live sources came back reading as
    "nothing supports this" — the exact symptom this work started from."""
    from app.agents.evidence import _align, supports

    aligned = _align([_verdict(), _verdict(), _verdict()], 3)
    assert all(map(supports, aligned))


def test_a_source_the_model_skipped_is_not_support():
    """Judging ten sources in one call is a speed fix, not licence to let one
    verdict stand in for another. An unjudged source stays unjudged."""
    from app.agents.evidence import _align, did_not_run, supports

    aligned = _align([_verdict(index=0)], 3)
    assert len(aligned) == 3
    assert supports(aligned[0])
    assert did_not_run(aligned[1]) and did_not_run(aligned[2])


def test_an_unlabelled_short_list_is_never_guessed_into_place():
    """Three sources, two unlabelled verdicts: which two is unknowable, and
    attaching one to the wrong source puts the wrong citation on screen."""
    from app.agents.evidence import _align, did_not_run

    aligned = _align([_verdict(), _verdict()], 3)
    assert all(map(did_not_run, aligned))
