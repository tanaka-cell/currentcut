"""Story Editor + Scriptwriter Agent (Phase 1: combined).

Builds source-linked ScriptLines from airable segments only. Hard rules
enforced in code: restricted segments never enter the script; every factual
line carries a segment_id, claim_ids, and an evidence status.
"""
from __future__ import annotations

from .. import lang
from ..models.schemas import (
    Claim, Confidentiality, EvidenceStatus, Project, ResearchResult, ScriptLine, Segment,
)
from ..storage import store
from . import evidence, house_style

_SHOT_ORDER = {"exterior": 0, "broll": 1, "interview": 2, "reaction": 3, "other": 4}
# Programmes that open on a reaction rather than an establishing shot.
_REACTION_FIRST_ORDER = {"reaction": 0, "interview": 1, "exterior": 2, "broll": 3, "other": 4}


def _spoken(seg: Segment) -> str:
    """The words this segment contributes to the script.

    Keyed off whether anyone actually speaks, not off the shot-type guess. Shot
    type is a classifier's opinion about framing; when it lands on "other" —
    which it does on anything it has not seen before — gating the words on it
    silently produces a script with no dialogue in it at all. On-screen text
    goes to `visual_summary`, so a transcript means speech.
    """
    return seg.transcript if seg.transcript.strip() else ""


def _write_to_corner_format(project: Project, style, airable: list[Segment],
                            claims: list[Claim], research: list[ResearchResult]) -> list[ScriptLine]:
    """Fill the corner's running order, block by block, from this shoot.

    A block with nothing to put in it is the useful output, not a failure: it
    tells the director what this corner normally has at that point and what they
    are missing, while there is still time to shoot it.
    """
    claims_by_segment: dict[str, list[Claim]] = {}
    for c in claims:
        claims_by_segment.setdefault(c.segment_id, []).append(c)
    research_by_claim: dict[str, list[ResearchResult]] = {}
    for r in research:
        research_by_claim.setdefault(r.claim_id, []).append(r)

    remaining = sorted(airable, key=lambda s: -s.usability_score)
    lines: list[ScriptLine] = []
    cursor = 0.0

    for block in sorted(style.blocks, key=lambda b: b.order):
        want = block.typical_seconds or 20
        match = next((s for s in remaining if s.shot_type == block.shot_type), None)
        if match is None:
            # Nothing on this shoot fits the slot. Hold the place and say so.
            lines.append(ScriptLine(
                project_id=project.id, order=len(lines),
                start_seconds=round(cursor, 2), end_seconds=round(cursor + want, 2),
                visual_instruction=f"［{block.role}］{block.purpose or block.notes}",
                evidence_status=EvidenceStatus.EDITORIAL_LANGUAGE,
                editorial_note=f"素材なし　このコーナーは通常ここに{_SHOT_JA.get(block.shot_type, block.shot_type)}"
                               f"を約{want}秒　追撮かナレーションで埋める",
            ))
            cursor += want
            continue

        remaining.remove(match)
        duration = min(match.end_seconds - match.start_seconds, float(want))
        seg_claims = claims_by_segment.get(match.id, [])
        featured = _featured_claim(seg_claims)
        status = _line_evidence(match, featured)
        note = _note(status, featured, research_by_claim)
        short_by = want - duration
        if short_by > 3:
            gap = f"{block.role}は通常{want}秒　この素材は{duration:.0f}秒　{short_by:.0f}秒不足"
            note = f"{note}／{gap}" if note else gap

        lines.append(ScriptLine(
            project_id=project.id, order=len(lines),
            start_seconds=round(cursor, 2), end_seconds=round(cursor + duration, 2),
            visual_instruction=f"［{block.role}］{match.visual_summary or match.shot_type}",
            audio_text=_spoken(match),
            caption_text=_caption_for(match, featured, research_by_claim),
            asset_id=match.asset_id, segment_id=match.id,
            source_in_seconds=match.start_seconds,
            source_out_seconds=match.start_seconds + duration,
            claim_ids=[c.id for c in seg_claims],
            evidence_status=status, confidentiality=match.confidentiality,
            editorial_note=note,
        ))
        cursor += duration

    store.clear(project.id, "script_lines")
    store.put_many(project.id, "script_lines", lines)
    return lines


_SHOT_JA = {"interview": "インタビュー", "reaction": "リアクション",
            "broll": "Bロール", "exterior": "外観", "other": "その他"}


def _shot_order_for(style) -> dict[str, int]:
    """Honour the opening device the programme actually uses."""
    if style is None:
        return _SHOT_ORDER
    opening = " ".join(style.structure[:2])
    if any(word in opening for word in ("反応", "リアクション", "声から", "コメントから")):
        return _REACTION_FIRST_ORDER
    return _SHOT_ORDER


def write_script(
    project: Project,
    segments: list[Segment],
    claims: list[Claim],
    research: list[ResearchResult],
) -> list[ScriptLine]:
    airable = [s for s in segments if s.allow_script_use and s.confidentiality
               not in (Confidentiality.CONFIDENTIAL, Confidentiality.OFF_THE_RECORD,
                       Confidentiality.PERSONAL_DATA, Confidentiality.NEEDS_HUMAN_REVIEW)]

    style = house_style.load(project.id)
    if style and style.blocks:
        # The corner has a shape of its own, learned from past editions. Build
        # to that shape and say which slots this shoot cannot fill.
        return _write_to_corner_format(project, style, airable, claims, research)

    # Otherwise the default factual-feature arc: establish → interviews → reactions.
    order = _shot_order_for(style)
    airable.sort(key=lambda s: (order.get(s.shot_type, 4), -s.usability_score))

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
        # One claim carries the line: the caption, the evidence status and the
        # note must all describe the same claim, or the line contradicts itself
        # (a caption citing a source under a status saying nothing backs it).
        featured = _featured_claim(seg_claims)
        status = _line_evidence(seg, featured)
        caption = _caption_for(seg, featured, research_by_claim)

        lines.append(ScriptLine(
            project_id=project.id,
            order=len(lines),
            start_seconds=round(cursor, 2),
            end_seconds=round(cursor + seg_duration, 2),
            visual_instruction=seg.visual_summary or seg.shot_type,
            audio_text=_spoken(seg),
            caption_text=caption,
            asset_id=seg.asset_id,
            segment_id=seg.id,
            source_in_seconds=seg.start_seconds,
            source_out_seconds=seg.start_seconds + seg_duration,
            claim_ids=[c.id for c in seg_claims],
            evidence_status=status,
            confidentiality=seg.confidentiality,
            editorial_note=_note(status, featured, research_by_claim),
        ))
        cursor += seg_duration

    store.clear(project.id, "script_lines")
    store.put_many(project.id, "script_lines", lines)
    return lines


# Which claim a line leads with, when a segment contains several. A director
# needs the one that most changes what they do: a contradiction first, then an
# unbacked number, then a confirmed fact worth captioning.
_CLAIM_PRIORITY = {
    EvidenceStatus.CONFLICTING: 0,
    EvidenceStatus.UNVERIFIED: 1,
    EvidenceStatus.MULTIPLE_SOURCES_CONFIRMED: 2,
    EvidenceStatus.PRIMARY_SOURCE_CONFIRMED: 3,
}


def _featured_claim(seg_claims: list[Claim]) -> Claim | None:
    if not seg_claims:
        return None
    return sorted(seg_claims,
                  key=lambda c: _CLAIM_PRIORITY.get(c.verification_status, 4))[0]


def _note(status: EvidenceStatus, claim: Claim | None,
          research_by_claim: dict[str, list[ResearchResult]]) -> str:
    """What the director needs to decide about this line, in plain words."""
    if claim is None:
        return ""
    if status == EvidenceStatus.CONFLICTING:
        others = [r for r in research_by_claim.get(claim.id, [])
                  if r.source_value and not r.supports_claim
                  and r.entity_match and r.attribute_match]
        others.sort(key=lambda r: 0 if r.source_type in ("official", "government") else 1)
        if others:
            found = others[0]
            return (f"Sources give a different figure: {found.source_value} "
                    f"({found.source_domain}). The line as spoken may be out of date.")
        return "Sources disagree with the line as spoken."
    if status == EvidenceStatus.UNVERIFIED:
        if claim.volatility_note:
            return claim.volatility_note
        return "No public source backs this. Attribute it to the speaker or drop the number."
    notes = []
    if evidence.citable_source(research_by_claim.get(claim.id, []),
                               claim.claim_text) is None:
        # Confirmed, but by nobody worth naming on air. Say so here rather than
        # let the line look fully cleared because its status reads CONFIRMED.
        backers = evidence.supporting_domains(research_by_claim.get(claim.id, []))
        notes.append("Checked, but no primary source to credit"
                     + (f" (backed by {', '.join(backers)})" if backers else "")
                     + ". Find the official release before crediting a source.")
    if claim.volatility_note:
        notes.append(f"{claim.volatility_note} — confirm before locking.")
    return " ".join(notes)


def _line_evidence(seg: Segment, claim: Claim | None) -> EvidenceStatus:
    if claim is None:
        # No factual claim: the footage itself is the source.
        return EvidenceStatus.FOOTAGE_CONFIRMED if seg.transcript else EvidenceStatus.EDITORIAL_LANGUAGE
    return claim.verification_status


def _caption_for(seg: Segment, claim: Claim | None,
                 research_by_claim: dict[str, list[ResearchResult]]) -> str:
    if claim is not None and claim.verification_status in (
            EvidenceStatus.PRIMARY_SOURCE_CONFIRMED,
            EvidenceStatus.MULTIPLE_SOURCES_CONFIRMED):
        # Only a primary source may be named on screen. Citing results[0]
        # regardless of support is how an anime fan site ended up printed as the
        # source for a product price; citing any supporting source is how a
        # payments vendor ended up printed under the national tax rates.
        citable = evidence.citable_source(research_by_claim.get(claim.id, []),
                                          claim.claim_text)
        if citable:
            return lang.cited(lang.detect(claim.claim_text),
                              claim.on_screen, citable.source_domain)
        # Checked, but with nobody worth naming. The figure still belongs on
        # screen; the attribution does not.
        return claim.on_screen
    # No speaker fallback: Gemini's speaker field is a description of what it
    # saw ("Man in apron"), and printing a description where a name super
    # belongs reads as a mistake, not a caption. The spoken line itself is
    # burned into the preview as a temp subtitle by the rough cut instead.
    return ""
