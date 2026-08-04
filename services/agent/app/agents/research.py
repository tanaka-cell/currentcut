"""Research Agent — verifies claims through the Parallel egress gate.

Support is decided by the evidence comparator (entity + attribute + value),
never by numeric overlap. A source that merely contains the same digits is
not evidence.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .. import config, lang
from ..clients.parallel_client import EgressBlocked, parallel
from ..models.schemas import Claim, EvidenceStatus, ResearchResult, Segment, now_iso
from ..storage import store
from . import evidence


def research_claims(
    project_id: str,
    claims: list[Claim],
    segments: list[Segment],
    after_date: str | None = None,
) -> list[ResearchResult]:
    seg_by_id = {s.id: s for s in segments}
    language = lang.of_segments(segments)
    all_results: list[ResearchResult] = []

    for claim in claims:
        segment = seg_by_id.get(claim.segment_id)
        if segment is None:
            continue
        try:
            results = parallel.search_for_claim(project_id, claim, segment, after_date=after_date)
        except EgressBlocked:
            # Logged by the gate; the claim simply stays unverified.
            claim.verification_status = EvidenceStatus.UNVERIFIED
            claim.last_checked_at = now_iso()
            store.put(project_id, "claims", claim)
            continue

        judgments = evidence.judge_all(claim, results)
        # An outage is not a finding: if the comparator never reached a verdict,
        # the claim is reported as unchecked rather than as "no support found".
        claim.verification_error = (
            judgments[0].reason if judgments and all(map(evidence.did_not_run, judgments)) else "")
        for r, judgment in zip(results, judgments):
            r.supports_claim = evidence.supports(judgment)
            r.entity_match = judgment.entity_match
            r.attribute_match = judgment.attribute_match
            r.source_value = judgment.source_value
            r.dated_qualifier = judgment.dated_qualifier
            r.value_as_of_year = judgment.value_as_of_year
            r.contradicts_claim = judgment.contradicts_claim
            r.judgment_reason = judgment.reason
            # The model's opinion is recorded, never acted on. Asked whether a
            # source is primary it said yes for 7andi's own IR page (right), and
            # also for nikkei.com and bengo4.com (wrong) — and bengo4 was then
            # printed on air as the source for a national statistic. What may be
            # credited is decided from the URL, by code, in _source_type.
            r.model_calls_it_primary = judgment.source_is_primary
            r.confidence = 0.85 if r.supports_claim else 0.1

        supporting = [r for r in results if r.supports_claim]
        # A 2014 store count genuinely matches "about 56,000" — and says nothing
        # about air day. It stays on the record as a source, but it cannot be
        # what makes the claim confirmed, or the sourced first cut is sourced to
        # a figure a decade out of date.
        current = [r for r in supporting if not _is_stale(r)]
        stale = [r for r in supporting if _is_stale(r)]
        primary = [r for r in current if r.source_type in ("official", "government")]

        if len(current) >= 2:
            claim.verification_status = EvidenceStatus.MULTIPLE_SOURCES_CONFIRMED
        elif primary:
            claim.verification_status = EvidenceStatus.PRIMARY_SOURCE_CONFIRMED
        elif current:
            # A single non-primary source is not enough to call a fact confirmed.
            claim.verification_status = EvidenceStatus.UNVERIFIED
        elif _conflicting(claim, results):
            claim.verification_status = EvidenceStatus.CONFLICTING
        else:
            claim.verification_status = EvidenceStatus.UNVERIFIED

        # Volatility flag (director-facing): only raise it when a source states
        # an actual expiry or scheduled change, not merely because prices move.
        qualifiers = [r.dated_qualifier for r in results if r.dated_qualifier]
        if not current and stale:
            years = sorted({r.value_as_of_year for r in stale if r.value_as_of_year})
            claim.volatility_note = lang.stale_evidence(language, years[0])
            claim.recheck_before_lock = True
        elif qualifiers:
            claim.volatility_note = qualifiers[0]
            claim.recheck_before_lock = True
        elif claim.volatility == "high" and claim.verification_status in (
                EvidenceStatus.PRIMARY_SOURCE_CONFIRMED, EvidenceStatus.MULTIPLE_SOURCES_CONFIRMED):
            claim.recheck_before_lock = True

        claim.last_checked_at = now_iso()
        store.put(project_id, "claims", claim)
        all_results.extend(results)

    store.put_many(project_id, "research_results", all_results)
    return all_results


def _is_stale(result: ResearchResult) -> bool:
    """A source is stale when it states which year its figure describes and that
    year is well behind us. A source that gives no as-of year is not assumed
    stale — absence of a date is not evidence of age, and a rule still in force
    reports no year at all (a rate introduced in 2019 is the current rate, not a
    2019 figure; see the comparator's value_as_of_year instruction)."""
    if not result.value_as_of_year:
        return False
    return datetime.now(timezone.utc).year - result.value_as_of_year > config.STALE_EVIDENCE_YEARS


def _conflicting(claim: Claim, results: list[ResearchResult]) -> bool:
    """A conflict is a source that makes the claim FALSE.

    This used to be inferred from "matched the subject and attribute but did not
    support" — which is the fallacy that absence of support is contradiction. It
    put 「Do not use this figure as spoken」 on "the federal minimum wage has not
    changed since 2009", because the Department of Labor's page states the
    history as "1938 - 2009" and that is not the string 2009. Telling a director
    to drop a true line is as damaging as letting a false one through, so the
    comparator is now asked the question directly.
    """
    return any(r.contradicts_claim and r.entity_match and r.attribute_match
               for r in results)
