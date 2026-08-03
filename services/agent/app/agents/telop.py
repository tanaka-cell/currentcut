"""Telop Agent — drafts the caption text the station's telop operator will type.

A 5–15 minute feature is usually finished at the broadcaster on the station's
own telop system. What the director actually hands over is a telop order sheet:
timecode, type, and the exact characters to set. Writing that sheet by hand is
one of the jobs that eats the night after a shoot.

CurrentCut can draft it because it already holds what the sheet needs:
the speaker for a name super, the timecode from the footage, and — the part
that is normally a separate chore — the source attribution for any number,
because the claim was checked against a page in the first place.

Japanese broadcast telop conventions applied here (all configurable):
  - no 。 or 、 — separate phrases with a full-width space instead
  - roughly 13 full-width characters per line, two lines at most
  - a figure shown on screen carries its source in the same telop
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ..clients.gemini_client import gemini
from . import house_style
from ..models.schemas import (
    Claim, EvidenceStatus, ResearchResult, ScriptLine, Segment, TelopEntry,
)
from ..storage import store

MAX_CHARS_PER_LINE = 13
MAX_LINES = 2

# Only these statuses may appear as an on-screen assertion of fact.
_AIRABLE_AS_FACT = (EvidenceStatus.PRIMARY_SOURCE_CONFIRMED,
                    EvidenceStatus.MULTIPLE_SOURCES_CONFIRMED)


class _Condensed(BaseModel):
    lines: list[str] = Field(description="Telop lines, no punctuation, <=13 full-width chars each")


_CONDENSE_PROMPT = """You write on-screen telop text for Japanese factual television.
Condense the material below into at most {max_lines} lines of at most
{max_chars} full-width characters each.

Rules:
- Never use 。 or 、. Separate phrases with a full-width space instead.
- Keep numbers and proper nouns exactly as given; never invent or round them.
- Drop filler and honorific padding; keep it readable at a glance.
- If it cannot be said within the limit, shorten the wording, not the facts.

{house_style}
Type of telop: {telop_type}
Material: {material}
Return JSON."""


def draft_telops(project_id: str, lines: list[ScriptLine], segments: list[Segment],
                 claims: list[Claim], research: list[ResearchResult]) -> list[TelopEntry]:
    seg_by_id = {s.id: s for s in segments}
    claim_by_id = {c.id: c for c in claims}
    research_by_claim: dict[str, list[ResearchResult]] = {}
    for r in research:
        research_by_claim.setdefault(r.claim_id, []).append(r)

    # The programme's own conventions, learned from scripts it has already
    # aired, if the director has supplied any.
    style = house_style.load(project_id)
    style_block = house_style.as_prompt_block(style)
    credit_format = (style.source_credit_format if style else "") or "出典 ◯◯"

    entries: list[TelopEntry] = []
    named: set[str] = set()  # a speaker is supered once, not on every line
    for line in sorted(lines, key=lambda l: l.order):
        seg = seg_by_id.get(line.segment_id)
        if seg is None:
            continue
        for entry in _entries_for_line(project_id, line, seg, claim_by_id,
                                       research_by_claim, named, style_block,
                                       credit_format):
            entry.order = len(entries) + 1
            # Nothing is silently truncated, so an over-long line is surfaced
            # for the director to shorten rather than hidden.
            longest = max((len(l) for l in entry.text_lines), default=0)
            if longest > MAX_CHARS_PER_LINE:
                note = f"{longest}字　1行{MAX_CHARS_PER_LINE}字に収まらない　要short"
                entry.caution = f"{entry.caution}／{note}" if entry.caution else note
            entries.append(entry)

    store.clear(project_id, "telops")
    store.put_many(project_id, "telops", entries)
    return entries


def _entries_for_line(project_id: str, line: ScriptLine, seg: Segment,
                      claim_by_id: dict[str, Claim],
                      research_by_claim: dict[str, list[ResearchResult]],
                      named: set[str], style_block: str = "",
                      credit_format: str = "出典 ◯◯") -> list[TelopEntry]:
    out: list[TelopEntry] = []

    # Name super: on the speaker's first appearance only. Re-supering someone on
    # every one of their lines is not how a feature is cut.
    if seg.shot_type in ("interview", "reaction") and seg.speaker and seg.speaker not in named:
        named.add(seg.speaker)
        out.append(TelopEntry(
            project_id=project_id, script_line_id=line.id,
            in_seconds=line.start_seconds, out_seconds=min(line.start_seconds + 5, line.end_seconds),
            telop_type="name",
            text_lines=_fit(seg.speaker),
            evidence_status=EvidenceStatus.FOOTAGE_CONFIRMED,
            caution="屋号・肩書の表記を本人に確認",
        ))

    # Place super for establishing shots.
    if seg.shot_type == "exterior" and seg.visual_summary:
        out.append(TelopEntry(
            project_id=project_id, script_line_id=line.id,
            in_seconds=line.start_seconds, out_seconds=min(line.start_seconds + 4, line.end_seconds),
            telop_type="place",
            text_lines=_fit(_condense(seg.visual_summary, "place super", style_block)),
            evidence_status=EvidenceStatus.FOOTAGE_CONFIRMED,
        ))

    # Data telop: a figure on screen, carrying the source it was checked against.
    for claim_id in line.claim_ids:
        claim = claim_by_id.get(claim_id)
        if claim is None:
            continue
        supporting = [r for r in research_by_claim.get(claim_id, []) if r.supports_claim]
        supporting.sort(key=lambda r: 0 if r.source_type in ("official", "government") else 1)

        if claim.verification_status in _AIRABLE_AS_FACT and supporting:
            out.append(TelopEntry(
                project_id=project_id, script_line_id=line.id,
                in_seconds=line.start_seconds, out_seconds=line.end_seconds,
                telop_type="data",
                text_lines=_fit(_condense(claim.claim_text, "data telop", style_block)),
                source_note=credit_format.replace("◯◯", supporting[0].source_domain),
                evidence_status=claim.verification_status,
                caution=claim.volatility_note,
            ))
        elif claim.verification_status == EvidenceStatus.CONFLICTING:
            out.append(TelopEntry(
                project_id=project_id, script_line_id=line.id,
                in_seconds=line.start_seconds, out_seconds=line.end_seconds,
                telop_type="data",
                text_lines=_fit(_condense(claim.claim_text, "data telop", style_block)),
                evidence_status=claim.verification_status,
                caution="⚠この数字のまま出さない　公開情報と食い違い　要確認",
            ))
        else:
            out.append(TelopEntry(
                project_id=project_id, script_line_id=line.id,
                in_seconds=line.start_seconds, out_seconds=line.end_seconds,
                telop_type="data",
                text_lines=_fit(_condense(claim.claim_text, "data telop", style_block)),
                evidence_status=claim.verification_status,
                caution=claim.volatility_note
                or "裏付けなし　話者の発言として出すか　数字を外す",
            ))

    # Comment follow: the quoted line itself.
    if line.audio_text.strip():
        out.append(TelopEntry(
            project_id=project_id, script_line_id=line.id,
            in_seconds=line.start_seconds, out_seconds=line.end_seconds,
            telop_type="comment",
            text_lines=_fit(_condense(line.audio_text, "comment follow", style_block)),
            evidence_status=EvidenceStatus.FOOTAGE_CONFIRMED,
        ))
    return out


def _condense(material: str, telop_type: str, style_block: str = "") -> str:
    if gemini.mock or not material.strip():
        return _strip_punctuation(material)
    try:
        result = gemini.structured(
            _CONDENSE_PROMPT.format(max_lines=MAX_LINES, max_chars=MAX_CHARS_PER_LINE,
                                    telop_type=telop_type, material=material,
                                    house_style=style_block),
            _Condensed,
        )
        if result.lines:
            return "\n".join(result.lines)
    except Exception:
        pass
    return _strip_punctuation(material)


def _strip_punctuation(text: str) -> str:
    """Telops do not carry 。 or 、; phrases are separated by a full-width space."""
    return re.sub(r"[、。]+", "　", text).strip("　 ")


# A telop must never break inside a figure: "5万600" / "0店" on two lines is a
# different number to the viewer. Numbers, their unit and their counter stay
# together, and so do latin words and percentages.
_UNBREAKABLE = re.compile(r"[0-9０-９][0-9０-９,，.．]*\s*(?:[万億兆]?[0-9０-９,，]*)?"
                          r"[%％円店人年月日杯割件台個名分秒時]?|[A-Za-z][A-Za-z0-9'’.-]*")


def _tokens(text: str) -> list[str]:
    """Split into pieces that may each sit on one line, keeping figures whole."""
    out, index = [], 0
    for match in _UNBREAKABLE.finditer(text):
        if match.start() > index:
            out.extend(list(text[index:match.start()]))
        out.append(match.group())
        index = match.end()
    out.extend(list(text[index:]))
    return [t for t in out if t != ""]


def _wrap(text: str) -> list[str]:
    """Break at phrase boundaries first. We separate phrases with a full-width
    space, so those are the natural break points; breaking mid-phrase is a last
    resort for a phrase that is itself too long."""
    phrases = [p for p in re.split(r"[　 ]+", text) if p]
    lines: list[str] = []
    current = ""
    for phrase in phrases:
        candidate = f"{current}　{phrase}" if current else phrase
        if len(candidate) <= MAX_CHARS_PER_LINE:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        if len(phrase) <= MAX_CHARS_PER_LINE:
            current = phrase
        else:
            chunks, chunk = [], ""
            for token in _tokens(phrase):
                if chunk and len(chunk) + len(token) > MAX_CHARS_PER_LINE:
                    chunks.append(chunk)
                    chunk = token
                else:
                    chunk += token
            if chunk:
                chunks.append(chunk)
            lines.extend(chunks[:-1])
            current = chunks[-1] if chunks else ""
    if current:
        lines.append(current)
    return lines or [""]


def _fit(text: str) -> list[str]:
    """Wrap to the line limit. Never drop characters — an over-long telop is a
    decision for the director, so the overflow stays visible in the last line."""
    text = _strip_punctuation(text)
    if "\n" in text:
        candidate = [l.strip() for l in text.split("\n") if l.strip()]
    else:
        candidate = _wrap(text)
    if len(candidate) <= MAX_LINES:
        return candidate
    head = candidate[:MAX_LINES - 1]
    return head + ["　".join(candidate[MAX_LINES - 1:])]
