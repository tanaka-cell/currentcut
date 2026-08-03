"""Research Agent — verifies claims through the Parallel egress gate.

Support is decided by the evidence comparator (entity + attribute + value),
never by numeric overlap. A source that merely contains the same digits is
not evidence.
"""
from __future__ import annotations

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

        for r in results:
            judgment = evidence.judge(claim, r)
            r.supports_claim = evidence.supports(judgment)
            r.source_value = judgment.source_value
            r.dated_qualifier = judgment.dated_qualifier
            r.judgment_reason = judgment.reason
            if judgment.source_is_primary and r.source_type == "web":
                r.source_type = "official"
            r.confidence = 0.85 if r.supports_claim else 0.1

        supporting = [r for r in results if r.supports_claim]
        primary = [r for r in supporting if r.source_type in ("official", "government")]

        if len(supporting) >= 2:
            claim.verification_status = EvidenceStatus.MULTIPLE_SOURCES_CONFIRMED
        elif primary:
            claim.verification_status = EvidenceStatus.PRIMARY_SOURCE_CONFIRMED
        elif supporting:
            # A single non-primary source is not enough to call a fact confirmed.
            claim.verification_status = EvidenceStatus.UNVERIFIED
        elif _conflicting(claim, results):
            claim.verification_status = EvidenceStatus.CONFLICTING
        else:
            claim.verification_status = EvidenceStatus.UNVERIFIED

        # Volatility flag (director-facing): only raise it when a source states
        # an actual expiry or scheduled change, not merely because prices move.
        qualifiers = [r.dated_qualifier for r in results if r.dated_qualifier]
        if qualifiers:
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


def _conflicting(claim: Claim, results: list[ResearchResult]) -> bool:
    """Sources that discuss the same thing but state a different value."""
    values = {r.source_value for r in results
              if r.source_value and not r.supports_claim}
    return len(values) > 0
