"""Research Agent — verifies claims through the Parallel egress gate."""
from __future__ import annotations

from ..clients.parallel_client import EgressBlocked, parallel
from ..models.schemas import Claim, EvidenceStatus, ResearchResult, Segment, now_iso
from ..storage import store


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
            r.supports_claim = _judge_support(claim, r)
            r.confidence = 0.8 if r.supports_claim else 0.3

        supporting = [r for r in results if r.supports_claim]
        if len(supporting) >= 2:
            claim.verification_status = EvidenceStatus.MULTIPLE_SOURCES_CONFIRMED
        elif len(supporting) == 1:
            claim.verification_status = (
                EvidenceStatus.PRIMARY_SOURCE_CONFIRMED
                if supporting[0].source_type in ("official", "government")
                else EvidenceStatus.UNVERIFIED
            )
        elif results:
            claim.verification_status = EvidenceStatus.CONFLICTING
        claim.last_checked_at = now_iso()
        store.put(project_id, "claims", claim)
        all_results.extend(results)

    store.put_many(project_id, "research_results", all_results)
    return all_results


def _judge_support(claim: Claim, result: ResearchResult) -> bool:
    """Cheap deterministic overlap check; Phase 2 upgrades this to a Gemini
    comparison of claim value vs excerpt value."""
    import re

    def numbers(text: str) -> set[str]:
        return {n.replace(",", "") for n in re.findall(r"[\d,]+", text) if n.strip(",")}

    claim_numbers = numbers(claim.claim_text)
    excerpt_numbers = numbers(result.excerpt)
    if claim_numbers:
        return bool(claim_numbers & excerpt_numbers)
    return bool(result.excerpt)
