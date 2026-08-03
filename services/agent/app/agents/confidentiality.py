"""Confidentiality Agent — labels every segment; fails closed.

Two layers, by design (DECISIONS.md D-006):
1. Gemini proposes a label per segment (real mode).
2. A deterministic rule layer ALWAYS runs and can only make labels stricter.
   Code, not prompts, is what blocks egress downstream.
"""
from __future__ import annotations

import re

from pydantic import BaseModel

from ..clients.gemini_client import gemini
from ..models.schemas import Confidentiality, Segment, RESTRICTED_LABELS
from ..storage import store

# Ordered strictest-last so max() over this ranking picks the safer label.
_SEVERITY = [
    Confidentiality.PUBLIC,
    Confidentiality.EDITORIAL_ONLY,
    Confidentiality.NEEDS_HUMAN_REVIEW,
    Confidentiality.PERSONAL_DATA,
    Confidentiality.CONFIDENTIAL,
    Confidentiality.OFF_THE_RECORD,
]

_OFF_RECORD_PATTERNS = [
    r"オフレコ", r"off\s*the\s*record", r"ここだけの話", r"放送(?:では|に)は?使わないで",
    r"カメラ(?:を|は)止めて",
]
_CONFIDENTIAL_PATTERNS = [
    r"未発表", r"まだ発表(?:して)?(?:いない|ない|前)", r"発表前", r"公表前", r"社外秘",
    r"内密に", r"リリース前", r"unannounced", r"not\s+announced",
]
_PERSONAL_DATA_PATTERNS = [
    r"\b0\d{1,4}-\d{1,4}-\d{3,4}\b",          # JP phone
    r"[\w.+-]+@[\w-]+\.[\w.]+",               # email
    r"〒?\d{3}-?\d{4}",                        # postal code
]


def _rule_label(segment: Segment) -> tuple[Confidentiality, str]:
    text = segment.transcript + " " + segment.visual_summary
    for pat in _OFF_RECORD_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return Confidentiality.OFF_THE_RECORD, f"matched off-record pattern: {pat}"
    for pat in _CONFIDENTIAL_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return Confidentiality.CONFIDENTIAL, f"matched unpublished-info pattern: {pat}"
    for pat in _PERSONAL_DATA_PATTERNS:
        if re.search(pat, text):
            return Confidentiality.PERSONAL_DATA, "matched personal-data pattern"
    if not segment.transcript.strip():
        return Confidentiality.PUBLIC, "no speech; visual-only b-roll"
    return Confidentiality.PUBLIC, "no restricted pattern matched"


class _LlmLabel(BaseModel):
    label: Confidentiality
    reason: str


_LLM_PROMPT = """You are the confidentiality officer of a TV newsroom.
Classify this footage segment from an on-camera shoot. Labels:
- PUBLIC: already-public or clearly publication-intended info. A spokesperson
  stating their company's current store count, prices, or product features
  on camera for broadcast is PUBLIC.
- EDITORIAL_ONLY: fine for the production team, but the verbatim wording
  should not be sent outside (e.g. loose phrasing, internal color).
- CONFIDENTIAL: likely unpublished business information (future plans,
  unreleased products, pre-announcement numbers).
- OFF_THE_RECORD: the speaker asks not to broadcast/use it.
- PERSONAL_DATA: PII spoken or visible (phone, address, plate, customer data).
- NEEDS_HUMAN_REVIEW: genuinely ambiguous cases only — do not use it as a
  default for ordinary on-camera statements.
Speaker: {speaker}
Transcript: {transcript}
Visuals: {visual}
Return JSON with label and a one-sentence reason."""


def classify_segments(project_id: str, segments: list[Segment]) -> list[Segment]:
    for seg in segments:
        rule_label, rule_reason = _rule_label(seg)
        final_label, final_reason = rule_label, rule_reason

        if not gemini.mock and seg.transcript.strip():
            try:
                llm = gemini.structured(
                    _LLM_PROMPT.format(
                        speaker=seg.speaker or "unknown",
                        transcript=seg.transcript,
                        visual=seg.visual_summary,
                    ),
                    _LlmLabel,
                )
                # Rules can only tighten, never loosen: take the stricter of the two.
                if _SEVERITY.index(llm.label) > _SEVERITY.index(rule_label):
                    final_label, final_reason = llm.label, f"gemini: {llm.reason}"
            except Exception as exc:  # LLM failure must not unblock anything
                if rule_label == Confidentiality.PUBLIC:
                    final_label = Confidentiality.NEEDS_HUMAN_REVIEW
                    final_reason = f"llm classification failed ({exc}); failing closed"

        seg.confidentiality = final_label
        seg.confidentiality_reason = final_reason
        seg.allow_script_use = final_label in (Confidentiality.PUBLIC, Confidentiality.EDITORIAL_ONLY)
        # EDITORIAL_ONLY: verbatim text never leaves, but keyword-only safe
        # queries may (the egress gate enforces the no-raw-transcript rule).
        seg.allow_external_search = final_label in (Confidentiality.PUBLIC, Confidentiality.EDITORIAL_ONLY)
        assert not (seg.confidentiality in RESTRICTED_LABELS and seg.allow_external_search)

    store.put_many(project_id, "segments", segments)
    return segments
