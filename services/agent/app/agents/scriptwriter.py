"""Story Editor + Scriptwriter Agent (Phase 1: combined).

Builds source-linked ScriptLines from airable segments only. Hard rules
enforced in code: restricted segments never enter the script; every factual
line carries a segment_id, claim_ids, and an evidence status.
"""
from __future__ import annotations

from ..models.schemas import (
    Claim, Confidentiality, EvidenceStatus, Project, ResearchResult, ScriptLine, Segment,
)
from ..storage import store

_SHOT_ORDER = {"exterior": 0, "broll": 1, "interview": 2, "reaction": 3, "other": 4}


def write_script(
    project: Project,
    segments: list[Segment],
    claims: list[Claim],
    research: list[ResearchResult],
) -> list[ScriptLine]:
    airable = [s for s in segments if s.allow_script_use and s.confidentiality
               not in (Confidentiality.CONFIDENTIAL, Confidentiality.OFF_THE_RECORD,
                       Confidentiality.PERSONAL_DATA, Confidentiality.NEEDS_HUMAN_REVIEW)]
    # Simple factual-feature arc: establish (exterior/broll) → interviews → reactions.
    airable.sort(key=lambda s: (_SHOT_ORDER.get(s.shot_type, 4), -s.usability_score))

    claims_by_segment: dict[str, list[Claim]] = {}
    for c in claims:
        claims_by_segment.setdefault(c.segment_id, []).append(c)
    research_by_claim: dict[str, list[ResearchResult]] = {}
    for r in research:
        research_by_claim.setdefault(r.claim_id, []).append(r)

    lines: list[ScriptLine] = []
    cursor = 0.0
    budget = project.target_duration_seconds

    for seg in airable:
        seg_duration = min(seg.end_seconds - seg.start_seconds, 15.0)
        if cursor + seg_duration > budget:
            break
        seg_claims = claims_by_segment.get(seg.id, [])
        evidence = _line_evidence(seg, seg_claims)
        caption = _caption_for(seg, seg_claims, research_by_claim)

        lines.append(ScriptLine(
            project_id=project.id,
            order=len(lines),
            start_seconds=round(cursor, 2),
            end_seconds=round(cursor + seg_duration, 2),
            visual_instruction=seg.visual_summary or seg.shot_type,
            audio_text=seg.transcript if seg.shot_type in ("interview", "reaction") else "",
            caption_text=caption,
            asset_id=seg.asset_id,
            segment_id=seg.id,
            source_in_seconds=seg.start_seconds,
            source_out_seconds=seg.start_seconds + seg_duration,
            claim_ids=[c.id for c in seg_claims],
            evidence_status=evidence,
            confidentiality=seg.confidentiality,
            editorial_note="" if evidence != EvidenceStatus.UNVERIFIED or not seg_claims
            else "Verify before air: claim(s) unconfirmed",
        ))
        cursor += seg_duration

    store.clear(project.id, "script_lines")
    store.put_many(project.id, "script_lines", lines)
    return lines


def _line_evidence(seg: Segment, seg_claims: list[Claim]) -> EvidenceStatus:
    if not seg_claims:
        # No factual claim: the footage itself is the source.
        return EvidenceStatus.FOOTAGE_CONFIRMED if seg.transcript else EvidenceStatus.EDITORIAL_LANGUAGE
    statuses = {c.verification_status for c in seg_claims}
    if EvidenceStatus.CONFLICTING in statuses:
        return EvidenceStatus.CONFLICTING
    if EvidenceStatus.UNVERIFIED in statuses:
        return EvidenceStatus.UNVERIFIED
    if EvidenceStatus.MULTIPLE_SOURCES_CONFIRMED in statuses:
        return EvidenceStatus.MULTIPLE_SOURCES_CONFIRMED
    return EvidenceStatus.PRIMARY_SOURCE_CONFIRMED


def _caption_for(seg: Segment, seg_claims: list[Claim],
                 research_by_claim: dict[str, list[ResearchResult]]) -> str:
    for c in seg_claims:
        if c.verification_status in (EvidenceStatus.PRIMARY_SOURCE_CONFIRMED,
                                     EvidenceStatus.MULTIPLE_SOURCES_CONFIRMED):
            sources = research_by_claim.get(c.id, [])
            src = f"（出典: {sources[0].source_domain}）" if sources else ""
            return f"{c.claim_text}{src}"
    if seg.speaker and seg.shot_type == "interview":
        return seg.speaker
    return ""
