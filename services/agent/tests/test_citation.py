"""Who may be named on screen as the source of a figure.

Supporting a claim and being fit to credit on air are different bars. A payments
company's explainer of the consumption-tax rates genuinely supports "eat-in is
10%", and a production run duly printed 出典 stripe.com under that figure — which
tells a viewer the broadcaster got its tax rates from a payments vendor. These
pin the stricter rule: only the body that publishes the number, or none at all.
"""


def _result(url, source_type, supports=True, claim_id="clm_x"):
    from app.models.schemas import ResearchResult
    return ResearchResult(claim_id=claim_id, source_url=url,
                          source_domain=url.split("/")[2],
                          source_type=source_type, supports_claim=supports)


# ---- the rule itself -------------------------------------------------------

def test_a_supporting_secondary_source_is_not_citable():
    from app.agents.evidence import citable_source

    assert citable_source([_result("https://stripe.com/jp/guides/tax", "web")]) is None


def test_a_primary_source_is_citable():
    from app.agents.evidence import citable_source

    got = citable_source([
        _result("https://stripe.com/jp/guides/tax", "web"),
        _result("https://www.nta.go.jp/taxes/shiraberu/keigen.htm", "government"),
    ])
    assert got is not None and got.source_domain == "www.nta.go.jp"


def test_a_primary_source_that_does_not_support_is_not_citable():
    """Being official is not enough — it has to back the claim."""
    from app.agents.evidence import citable_source

    assert citable_source([
        _result("https://www.nta.go.jp/a", "government", supports=False),
    ]) is None


def test_the_same_evidence_always_yields_the_same_credit():
    """The 出典 on a re-run sheet must not depend on retrieval order."""
    from app.agents.evidence import citable_source

    results = [_result("https://www.mof.go.jp/b", "government"),
               _result("https://www.nta.go.jp/a", "government"),
               _result("https://example.com/ir/x", "official")]
    first = citable_source(results).source_url
    assert citable_source(list(reversed(results))).source_url == first


# ---- which authority, once several may be credited -------------------------
#
# All of these were creditable already. The question these pin is *which* name
# reaches the screen when more than one public body backs the same figure. The
# first two are the sample that shipped on the landing page: www.dol.gov was in
# the supporting evidence both times and lost on the alphabet.

_FEDERAL = "The federal minimum wage of $7.25 an hour has not changed since 2009."


def test_a_state_office_is_not_credited_for_a_federal_figure():
    """dol.georgia.gov under the federal minimum wage names a body that does
    not set it. It reached the shipped sample; www.dol.gov was right there."""
    from app.agents.evidence import citable_source

    got = citable_source([
        _result("https://dol.georgia.gov/minimum-wage", "government"),
        _result("https://www.dol.gov/agencies/whd/minimum-wage", "government"),
    ], _FEDERAL)
    assert got.source_domain == "www.dol.gov"


def test_an_application_host_loses_to_the_published_estate():
    """Right authority, wrong address: webapps.dol.gov also reached the sample."""
    from app.agents.evidence import citable_source

    got = citable_source([
        _result("https://webapps.dol.gov/elaws/faq", "government"),
        _result("https://www.dol.gov/agencies/whd/minimum-wage", "government"),
    ], _FEDERAL)
    assert got.source_domain == "www.dol.gov"


def test_a_state_office_is_still_credited_when_it_is_the_only_one():
    """Ranking below the union is not the same as being unfit to name. If the
    state page is the only public body that backed it, it is the source."""
    from app.agents.evidence import citable_source

    got = citable_source([
        _result("https://dol.georgia.gov/minimum-wage", "government"),
        _result("https://www.cbpp.org/wages", "web"),
    ], _FEDERAL)
    assert got.source_domain == "dol.georgia.gov"


def test_a_state_office_is_the_right_source_for_that_state():
    """The demotion is about scope, not about states being second class."""
    from app.agents.evidence import citable_source

    got = citable_source([
        _result("https://www.dol.gov/agencies/whd/state/minimum-wage", "government"),
        _result("https://dol.georgia.gov/minimum-wage", "government"),
    ], "Georgia's own minimum wage is still $5.15 an hour.")
    assert got.source_domain == "dol.georgia.gov"


def test_naming_a_state_does_not_make_it_the_authority_on_a_federal_figure():
    """A claim can mention both. "federal" decides who sets the number."""
    from app.agents.evidence import citable_source

    got = citable_source([
        _result("https://dol.georgia.gov/minimum-wage", "government"),
        _result("https://www.dol.gov/agencies/whd/minimum-wage", "government"),
    ], "Georgia has no state minimum of its own, so the federal $7.25 applies.")
    assert got.source_domain == "www.dol.gov"


def test_a_local_japanese_authority_loses_to_the_national_one():
    """Japan puts the level in the suffix: .go.jp is national, .lg.jp is not."""
    from app.agents.evidence import citable_source

    got = citable_source([
        _result("https://www.city.yokohama.lg.jp/zeikin", "government"),
        _result("https://www.nta.go.jp/taxes/keigen.htm", "government"),
    ], "持ち帰りの消費税は全国どこでも8%です。")
    assert got.source_domain == "www.nta.go.jp"


def test_a_local_japanese_authority_wins_for_its_own_place():
    from app.agents.evidence import citable_source

    got = citable_source([
        _result("https://www.nta.go.jp/taxes/keigen.htm", "government"),
        _result("https://www.city.yokohama.lg.jp/hoikuen", "government"),
    ], "横浜市の待機児童は今年度ゼロになりました。")
    assert got.source_domain == "www.city.yokohama.lg.jp"


def test_scope_never_decides_whether_a_source_is_creditable_at_all():
    """A company blog does not become citable by naming the right place."""
    from app.agents.evidence import citable_source

    assert citable_source([_result("https://stripe.com/guides/tax", "web")],
                          "Georgia's minimum wage is $5.15.") is None


def test_the_credit_still_does_not_depend_on_retrieval_order():
    """The new ordering has more terms; it must stay a total order."""
    from app.agents.evidence import citable_source

    results = [_result("https://dol.georgia.gov/a", "government"),
               _result("https://webapps.dol.gov/b", "government"),
               _result("https://www.dol.gov/c", "government"),
               _result("https://example.com/ir/x", "official")]
    first = citable_source(results, _FEDERAL).source_url
    assert citable_source(list(reversed(results)), _FEDERAL).source_url == first
    assert first == "https://www.dol.gov/c"


def test_supporting_domains_reports_who_did_back_it():
    """A director told "no primary source" still needs somewhere to start."""
    from app.agents.evidence import supporting_domains

    got = supporting_domains([
        _result("https://stripe.com/a", "web"),
        _result("https://stripe.com/b", "web"),           # deduplicated
        _result("https://biz.moneyforward.com/c", "web"),
        _result("https://unrelated.example/d", "web", supports=False),
    ])
    assert got == ["stripe.com", "biz.moneyforward.com"]


# ---- the model may not talk its way into being credited --------------------

def test_the_model_cannot_promote_a_source_into_being_creditable(monkeypatch):
    """Asked whether a source is primary, the comparator said yes for 7andi's
    own IR page (right) and for nikkei.com and bengo4.com (wrong). bengo4 was
    then printed on air as the source for a national store count. The opinion is
    recorded; what may be credited is decided from the URL, by code."""
    from app.agents import evidence, research
    from app.clients import parallel_client
    from app.models.schemas import Claim, Confidentiality, ResearchResult, Segment

    seg = Segment(asset_id="ast_x", transcript="全国におよそ五万六千店あります",
                  confidentiality=Confidentiality.PUBLIC, allow_external_search=True)
    claim = Claim(segment_id=seg.id, claim_text="コンビニは全国に約5万6千店",
                  allow_external_search=True, safe_search_query="コンビニ 店舗数")
    results = [ResearchResult(claim_id=claim.id, source_url="https://www.bengo4.com/c_1/n_1/",
                              source_domain="www.bengo4.com", source_type="web")]

    monkeypatch.setattr(parallel_client.parallel, "mock", True)
    monkeypatch.setattr(research.parallel, "search_for_claim", lambda *a, **kw: results)
    monkeypatch.setattr(evidence, "judge_all", lambda c, rs: [
        evidence.EvidenceJudgment(entity_match=True, attribute_match=True,
                                  value_match=True, source_is_primary=True,
                                  source_value="5万5838店", reason="ok")])

    research.research_claims("prj_test", [claim], [seg])

    assert results[0].source_type == "web", "the model must not rewrite the classification"
    assert results[0].model_calls_it_primary is True, "but its opinion is kept on the record"
    assert evidence.citable_source(results) is None


def test_a_first_party_ir_page_is_creditable_from_its_url_alone():
    """The one the model got right is still credited — without needing it to."""
    from app.agents.evidence import citable_source
    from app.clients.parallel_client import ParallelClient

    url = "https://www.7andi.com/ir/library/co_financial/2026/convenience.html"
    assert ParallelClient._source_type(url) == "official"
    assert citable_source([_result(url, "official")]).source_domain == "www.7andi.com"


# ---- how it reaches the sheet and the cut ----------------------------------

def _telops_for(monkeypatch, results):
    from app.agents import telop
    from app.models.schemas import (
        Claim, EvidenceStatus, ScriptLine, Segment,
    )

    seg = Segment(asset_id="ast_x", speaker="店主", shot_type="interview",
                  transcript="店内でお召し上がりは10パーセントの消費税です",
                  start_seconds=0, end_seconds=6)
    claim = Claim(segment_id=seg.id, claim_text="店内飲食の消費税率は10%",
                  claim_type="stat",
                  verification_status=EvidenceStatus.MULTIPLE_SOURCES_CONFIRMED)
    for r in results:
        r.claim_id = claim.id
    line = ScriptLine(project_id="prj_test", order=0, start_seconds=0, end_seconds=6,
                      segment_id=seg.id, asset_id=seg.asset_id,
                      audio_text=seg.transcript, claim_ids=[claim.id],
                      evidence_status=claim.verification_status)
    # Condensing calls Gemini; the citation is what is under test, not the wording.
    monkeypatch.setattr(telop, "_condense", lambda text, kind, style, language: text)
    entries = telop.draft_telops("prj_test", [line], [seg], [claim], results)
    return [e for e in entries if e.telop_type == "data"]


def test_a_figure_with_only_secondary_backing_carries_no_credit(monkeypatch):
    data = _telops_for(monkeypatch, [_result("https://stripe.com/jp/guides/tax", "web")])
    assert len(data) == 1
    entry = data[0]
    assert entry.source_note == "", "a payments vendor must not be printed as 出典"
    assert "一次情報なし" in entry.caution
    assert "stripe.com" in entry.caution, "say who did back it, so it can be chased"


def test_a_figure_with_primary_backing_carries_its_credit(monkeypatch):
    data = _telops_for(monkeypatch, [
        _result("https://stripe.com/jp/guides/tax", "web"),
        _result("https://www.nta.go.jp/taxes/keigen.htm", "government"),
    ])
    assert "www.nta.go.jp" in data[0].source_note
    assert "stripe.com" not in data[0].source_note


def test_the_burned_in_caption_follows_the_same_rule():
    """The rough cut caption is the one that ends up in the picture."""
    from app.agents.scriptwriter import _caption_for
    from app.models.schemas import Claim, EvidenceStatus, Segment

    seg = Segment(asset_id="ast_x", speaker="店主", shot_type="interview")
    claim = Claim(segment_id=seg.id, claim_text="店内飲食の消費税率は10%",
                  verification_status=EvidenceStatus.MULTIPLE_SOURCES_CONFIRMED)

    secondary = {claim.id: [_result("https://stripe.com/a", "web", claim_id=claim.id)]}
    assert _caption_for(seg, claim, secondary) == "店内飲食の消費税率は10%"

    primary = {claim.id: [_result("https://www.nta.go.jp/a", "government", claim_id=claim.id)]}
    assert "（出典: www.nta.go.jp）" in _caption_for(seg, claim, primary)


def test_the_script_line_says_the_credit_is_missing():
    """CONFIRMED with no citable source must not read as fully cleared."""
    from app.agents.scriptwriter import _note
    from app.models.schemas import Claim, EvidenceStatus

    claim = Claim(segment_id="seg_x", claim_text="店内飲食の消費税率は10%",
                  verification_status=EvidenceStatus.MULTIPLE_SOURCES_CONFIRMED)
    note = _note(EvidenceStatus.MULTIPLE_SOURCES_CONFIRMED, claim,
                 {claim.id: [_result("https://stripe.com/a", "web", claim_id=claim.id)]})
    assert "no primary source" in note.lower()
    assert "stripe.com" in note


# ---- a caption must not say the subject twice ------------------------------

def test_a_subject_already_in_the_claim_is_not_prefixed_again():
    """An exact substring test said no to "small businesses in this country"
    inside "Small businesses in this country employ almost half…" — one capital
    letter — and the caption went out saying it twice."""
    from app.agents.claims import _with_subject

    said = "Small businesses in this country employ almost half of the private workforce."
    assert _with_subject(said, "small businesses in this country") == said
    assert _with_subject("持ち帰りの消費税率は8%です", "持ち帰りの消費税率") == "持ち帰りの消費税率は8%です"
    assert _with_subject("The rate is 8%", "the reduced tax rate") == "the reduced tax rate: The rate is 8%"


# ---- what gets verified vs what gets read ----------------------------------

def test_the_subject_prefix_never_reaches_the_screen():
    """A caption went out reading "small businesses' employment share of the
    private workforce in this country: Small businesses employ almost half of
    the private workforce in this country." The prefix is there so the claim
    verifies against the right pages, which is not a reason to read it aloud."""
    from app.models.schemas import Claim

    claim = Claim(
        segment_id="seg_1",
        claim_text="small businesses' employment share of the private workforce"
                   " in this country: Small businesses employ almost half of the"
                   " private workforce in this country.",
        display_text="Small businesses employ almost half of the private"
                     " workforce in this country.",
    )
    assert claim.on_screen.startswith("Small businesses employ")
    assert ":" not in claim.on_screen


def test_a_claim_stored_before_the_split_still_reads():
    from app.models.schemas import Claim

    claim = Claim(segment_id="seg_1", claim_text="The rate is 8%.")
    assert claim.on_screen == "The rate is 8%."


def test_the_prefix_is_still_what_gets_verified():
    """Dropping it from the search is the bug it was added to fix: a claim with
    no subject verifies against any page carrying the same number."""
    from app.agents.claims import _with_subject

    verified = _with_subject("It employs almost half of them.", "small businesses")
    assert verified.startswith("small businesses:")
