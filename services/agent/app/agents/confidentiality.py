"""Confidentiality Agent — labels every segment; fails closed.

Two layers, by design (DECISIONS.md D-006):
1. Gemini proposes a label per segment (real mode).
2. A deterministic rule layer ALWAYS runs and can only make labels stricter.
   Code, not prompts, is what blocks egress downstream.
"""
from __future__ import annotations

import re

from pydantic import BaseModel

from .. import progress
from ..clients.gemini_client import gemini
from ..models.schemas import (
    Confidentiality, ProposedRelease, RESTRICTED_LABELS, Segment, new_id,
)
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

# Nobody says "off the record" on cue. People ask in the words that come to
# them — 「放送はしないでほしいんだけど」「ここだけの話で」「今のはナシで」— and a
# rule that only knows the formal marker hears none of it.
#
# These raise a hold and an alert, not a verdict: the director is shown where
# the tool thinks the restricted part begins and settles it themselves (see
# propose_release). Because the cost of a false positive is one review click and
# the cost of a miss is broadcasting something a person asked you not to, this
# list is deliberately broad. Anything phrased in a way not listed here still
# has to get past the Gemini layer, which can only make a label stricter.
_OFF_RECORD_PATTERNS = [
    # Japanese — the explicit marker, and the ordinary ways of asking
    r"オフレコ",
    r"ここだけの話",
    r"内緒(?:に|で)",
    r"他言(?:は)?しないで",
    r"放送[^。]{0,8}(?:しないで|やめて|控えて|使わないで|流さないで|載せないで|カットして)",
    r"(?:オンエア|オンエアー|番組|テレビ)[^。]{0,8}(?:しないで|使わないで|流さないで|出さないで)",
    r"(?:今|いま)の(?:は|話は)?(?:ナシ|なし|無し|オフ)",
    r"(?:今|いま)の(?:は|話は)?[^。]{0,6}(?:カット|使わないで|忘れて)",
    r"記事に[^。]{0,6}しないで",
    r"表に(?:は)?出さないで",
    r"カメラ(?:を|は)?[^。]{0,4}(?:止めて|切って)",
    r"マイク(?:を|は)?[^。]{0,4}(?:切って|止めて)",
    # English — the marker, and the ordinary ways of asking
    r"off\s*the\s*record",
    r"between\s+(?:you\s+and\s+me|us|ourselves)",
    r"(?:don'?t|do\s+not|please\s+don'?t)\s+(?:use|air|broadcast|print|quote|publish|report)\s+(?:that|this|it)",
    r"(?:keep|leave)\s+(?:that|this|it)\s+(?:out|off)\b",
    r"not\s+for\s+(?:broadcast|air|publication|the\s+record|attribution)",
    r"(?:strike|scratch)\s+(?:that|this)\b",
    r"(?:cut|kill)\s+(?:that|this)\s+(?:bit|part|line)?",
    r"(?:turn|switch)\s+(?:the\s+)?(?:camera|mic|microphone)\s+off",
    r"can\s+we\s+(?:go\s+)?off\s+(?:the\s+)?record",
    r"this\s+(?:stays|is)\s+between\s+us",
]
_CONFIDENTIAL_PATTERNS = [
    r"未発表", r"まだ発表(?:して)?(?:いない|ない|前)", r"発表前", r"公表前", r"社外秘",
    r"内密に", r"リリース前", r"解禁前", r"(?:まだ)?公表(?:して)?(?:いない|ない)",
    r"unannounced", r"not\s+(?:yet\s+)?announced", r"before\s+(?:the\s+)?announcement",
    r"under\s+embargo", r"embargoed", r"not\s+public\s+yet", r"hasn'?t\s+been\s+announced",
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
- OFF_THE_RECORD: the speaker asks, in any words, for this not to be used or
  broadcast. They will rarely say "off the record": listen for "please don't use
  that", "keep this between us", "can you cut that bit", "not for broadcast",
  「放送はしないでほしい」「ここだけの話」「今のはナシで」. A request phrased
  politely, or trailing off, is still a request.
- PERSONAL_DATA: PII spoken or visible (phone, address, plate, customer data).
- NEEDS_HUMAN_REVIEW: genuinely ambiguous cases only — do not use it as a
  default for ordinary on-camera statements.
Speaker: {speaker}
Transcript: {transcript}
Visuals: {visual}
Return JSON with label and a one-sentence reason."""


# A sentence end, in either convention.
_SENTENCE = re.compile(r"(?<=[。？！])\s*|(?<=[.?!])\s+")
# Below this, a "sentence" is an artefact — "U.S." split off from "Department of
# Labor" — so it is glued back onto the one before it.
_MIN_SENTENCE_CHARS = 12


def _sentences(text: str) -> list[str]:
    pieces: list[str] = []
    for raw in _SENTENCE.split(text):
        piece = raw.strip()
        if not piece:
            continue
        if pieces and len(pieces[-1]) < _MIN_SENTENCE_CHARS:
            pieces[-1] = f"{pieces[-1]} {piece}"
        else:
            pieces.append(piece)
    return pieces


def propose_release(segment: Segment) -> list[ProposedRelease]:
    """Where the off-record part of a segment probably starts and ends.

    A PROPOSAL. Nothing here changes what may leave the building — the segment
    stays restricted until a person says otherwise.

    The reason is that the tool cannot know the boundary. An off-record remark
    is a span of *subject matter*, and the marker is not reliably at its edge:
      「オフレコですが、来月2号店を出します。まだ発表前なんです。」
    — the second sentence carries no marker and is plainly still off the record,
    and an automatic split would have put it in the script. The reverse happens
    too: 「……という話でして。今のはオフレコで。」 marks the sentence *after* the
    material it covers.

    So this returns the tool's reading, per sentence, for a director to confirm
    or drag — and holds everything until they do. Timings within a segment are
    unknown, so they are apportioned by character count and flagged as estimates.
    """
    sentences = _sentences(segment.transcript)
    if len(sentences) < 2:
        return []
    labels = [_rule_label(Segment(asset_id=segment.asset_id, transcript=s))[0]
              for s in sentences]
    if len(set(labels)) < 2:
        return []  # uniformly clean or uniformly restricted; nothing to decide

    span = max(segment.end_seconds - segment.start_seconds, 0.0)
    total = sum(len(s) for s in sentences) or 1
    out: list[ProposedRelease] = []
    cursor = segment.start_seconds
    for sentence, label in zip(sentences, labels):
        share = span * len(sentence) / total
        out.append(ProposedRelease(
            text=sentence,
            start_seconds=round(cursor, 2),
            end_seconds=round(cursor + share, 2),
            proposed_label=label,
            timing_is_estimated=True,
        ))
        cursor += share
    return out


def confirm_release(project_id: str, segment: Segment, release_indexes: list[int],
                    confirmed_by: str) -> list[Segment]:
    """Act on a director's decision about where the off-record part sits.

    This is the only path by which held material becomes usable, and it needs a
    name attached: releasing someone's off-record remark is a person's call to
    make and a person's call to answer for.

    The segment is replaced by one piece per sentence. The pieces the director
    named are released at the label the rules give them on their own; every
    other piece keeps the original restriction.
    """
    proposal = segment.release_proposal
    if not proposal:
        raise ValueError("segment has no release proposal to confirm")
    chosen = set(release_indexes)
    if not chosen <= set(range(len(proposal))):
        raise ValueError("release_indexes out of range")

    pieces: list[Segment] = []
    for i, part in enumerate(proposal):
        if i in chosen:
            label, reason = _rule_label(
                Segment(asset_id=segment.asset_id, transcript=part.text))
            reason = f"released by {confirmed_by}; {reason}"
        else:
            label = segment.confidentiality
            reason = f"held: {segment.confidentiality_reason}"
        pieces.append(segment.model_copy(update={
            "id": new_id("seg"),
            "start_seconds": part.start_seconds,
            "end_seconds": part.end_seconds,
            "transcript": part.text,
            "confidentiality": label,
            "confidentiality_reason": reason,
            "allow_script_use": label in (Confidentiality.PUBLIC,
                                          Confidentiality.EDITORIAL_ONLY),
            "allow_external_search": label == Confidentiality.PUBLIC,
            "release_proposal": [],
            "release_confirmed_by": confirmed_by,
        }))

    kept = [s for s in store.list(project_id, "segments", Segment)
            if s.id != segment.id]
    store.clear(project_id, "segments")
    store.put_many(project_id, "segments", kept + pieces)
    return pieces


def _snippet(seg: Segment) -> str:
    text = seg.transcript.strip() or seg.visual_summary.strip() or "(no speech)"
    return text if len(text) <= 60 else text[:57] + "…"


def classify_segments(project_id: str, segments: list[Segment]) -> list[Segment]:
    for seg in segments:
        progress.emit(project_id, "confidentiality", "running",
                       f"{seg.speaker or 'segment'}: “{_snippet(seg)}”")
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
        # Only PUBLIC leaves the building. EDITORIAL_ONLY was briefly allowed to
        # make verification fire, but the real cause was over-labeling by the
        # LLM (since fixed in the prompt). Fail closed is the product's claim;
        # loosening it to make a demo work is the wrong trade.
        seg.allow_external_search = final_label == Confidentiality.PUBLIC
        assert not (seg.confidentiality in RESTRICTED_LABELS and seg.allow_external_search)

        # A restricted segment that is only partly restricted is the expensive
        # case: the whole of it is held, and the usable answers inside it are
        # held with it. Say so, and show where the boundary probably falls, so
        # the director can settle it in one look instead of losing the material.
        seg.release_proposal = (propose_release(seg)
                                if final_label in RESTRICTED_LABELS else [])

        if final_label in RESTRICTED_LABELS:
            progress.emit(project_id, "confidentiality", "blocked",
                           f"{seg.speaker or 'segment'}: held back — {final_label.value} ({final_reason})")
        else:
            progress.emit(project_id, "confidentiality", "done",
                           f"{seg.speaker or 'segment'}: labelled {final_label.value}")

    store.put_many(project_id, "segments", segments)
    return segments
