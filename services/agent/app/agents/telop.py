"""Telop Agent — drafts the caption text the station's telop operator will type.

A 5–15 minute feature is usually finished at the broadcaster on the station's
own telop system. What the director actually hands over is a telop order sheet:
timecode, type, and the exact characters to set. Writing that sheet by hand is
one of the jobs that eats the night after a shoot.

CurrentCut can draft it because it already holds what the sheet needs:
the speaker for a name super, the timecode from the footage, and — the part
that is normally a separate chore — the source attribution for any number,
because the claim was checked against a page in the first place.

Caption conventions are not universal, and the ones this was built against are
Japanese: thirteen full-width characters to a line, no 。 or 、, a 出典 column.
An English-language lower third counts differently and reads differently. Every
convention that differs lives in `app/lang.py`, keyed by the language of the
shoot; what stays the same everywhere is that a figure on screen carries the
source it was checked against, or says why it cannot.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from .. import lang
from ..clients.gemini_client import gemini
from . import evidence, house_style
from ..models.schemas import (
    Claim, EvidenceStatus, ResearchResult, ScriptLine, Segment, TelopEntry,
)
from ..storage import store

# Only these statuses may appear as an on-screen assertion of fact.
_AIRABLE_AS_FACT = (EvidenceStatus.PRIMARY_SOURCE_CONFIRMED,
                    EvidenceStatus.MULTIPLE_SOURCES_CONFIRMED)


class _Condensed(BaseModel):
    lines: list[str] = Field(description="Caption lines, within the stated character limit")


_CONDENSE_PROMPT = """You write on-screen caption text for {audience}.
Condense the material below into at most {max_lines} lines of at most
{max_chars} characters each.

Rules:
{caption_rules}
- Keep numbers and proper nouns exactly as given; never invent or round them.
- Drop filler and honorific padding; keep it readable at a glance.
- If it cannot be said within the limit, shorten the wording, not the facts.
- Write in the same language as the material.

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
    # The shoot decides the conventions. A thirteen-character line and a 出典
    # column are Japanese broadcast practice, not universal ones.
    language = lang.of_segments(segments)
    max_chars = lang.CAPTION_LIMITS[language]["max_chars"]
    credit_format = ((style.source_credit_format if style else "")
                     or lang.CREDIT_FORMAT[language])

    entries: list[TelopEntry] = []
    named: set[str] = set()  # a speaker is supered once, not on every line
    for line in sorted(lines, key=lambda l: l.order):
        seg = seg_by_id.get(line.segment_id)
        if seg is None:
            continue
        for entry in _entries_for_line(project_id, line, seg, claim_by_id,
                                       research_by_claim, named, style_block,
                                       credit_format, language):
            entry.order = len(entries) + 1
            # Nothing is silently truncated, so an over-long line is surfaced
            # for the director to shorten rather than hidden.
            longest = max((len(l) for l in entry.text_lines), default=0)
            if longest > max_chars:
                note = lang.too_long(language, longest, max_chars)
                entry.caution = lang.join_notes(language, entry.caution, note)
            entries.append(entry)

    # Numbers exist only once everything is ordered, so the cross-reference is
    # written here rather than where the rows are made.
    order_of = {e.id: e.order for e in entries}
    for entry in entries:
        number = order_of.get(entry.same_statement_as)
        if number:
            entry.caution = lang.join_notes(
                language, entry.caution, lang.same_statement_as(language, number))

    store.clear(project_id, "telops")
    store.put_many(project_id, "telops", entries)
    return entries


def _entries_for_line(project_id: str, line: ScriptLine, seg: Segment,
                      claim_by_id: dict[str, Claim],
                      research_by_claim: dict[str, list[ResearchResult]],
                      named: set[str], style_block: str = "",
                      credit_format: str = "出典 ◯◯",
                      language: str = lang.JA) -> list[TelopEntry]:
    out: list[TelopEntry] = []

    # Name super: on the speaker's first appearance only. Re-supering someone on
    # every one of their lines is not how a feature is cut.
    if seg.shot_type in ("interview", "reaction") and seg.speaker and seg.speaker not in named:
        named.add(seg.speaker)
        out.append(TelopEntry(
            project_id=project_id, script_line_id=line.id,
            in_seconds=line.start_seconds, out_seconds=min(line.start_seconds + 5, line.end_seconds),
            telop_type="name",
            text_lines=_fit(seg.speaker, language),
            evidence_status=EvidenceStatus.FOOTAGE_CONFIRMED,
            caution=lang.name_super_check(language),
        ))

    # Place super for establishing shots.
    if seg.shot_type == "exterior" and seg.visual_summary:
        out.append(TelopEntry(
            project_id=project_id, script_line_id=line.id,
            in_seconds=line.start_seconds, out_seconds=min(line.start_seconds + 4, line.end_seconds),
            telop_type="place",
            text_lines=_fit(_condense(seg.visual_summary, "place super", style_block, language),
                            language),
            evidence_status=EvidenceStatus.FOOTAGE_CONFIRMED,
        ))

    # Data telop: a figure on screen, carrying the source it was checked against.
    disputed = False
    flagged: TelopEntry | None = None   # a data telop on this line that is not airable as fact
    for claim_id in line.claim_ids:
        claim = claim_by_id.get(claim_id)
        if claim is None:
            continue
        results = research_by_claim.get(claim_id, [])
        citable = evidence.citable_source(results, claim.claim_text)
        # What the figure was actually checked against — not the same as the
        # single source credited on air. A 裏付け column that says only
        # "multiple sources" gives the edit house nothing it can audit.
        checked = evidence.supporting_domains(results, limit=3)

        if claim.verification_status in _AIRABLE_AS_FACT:
            # The figure was checked either way. Whether it may carry a 出典 on
            # screen is a separate, stricter question — see evidence.citable_source.
            if citable:
                source_note = credit_format.replace("◯◯", citable.source_domain)
                caution = claim.volatility_note
            else:
                backers = evidence.supporting_domains(results)
                source_note = ""
                caution = lang.no_primary_source(language, backers)
                if claim.volatility_note:
                    caution = lang.join_notes(language, caution, claim.volatility_note)
            out.append(TelopEntry(
                project_id=project_id, script_line_id=line.id,
                in_seconds=line.start_seconds, out_seconds=line.end_seconds,
                telop_type="data",
                text_lines=_fit(_condense(claim.on_screen, "data telop", style_block, language),
                                language),
                source_note=source_note,
                evidence_status=claim.verification_status,
                checked_against=checked,
                caution=caution,
            ))
        elif claim.verification_status == EvidenceStatus.CONFLICTING:
            disputed = True
            entry = TelopEntry(
                project_id=project_id, script_line_id=line.id,
                in_seconds=line.start_seconds, out_seconds=line.end_seconds,
                telop_type="data",
                text_lines=_fit(_condense(claim.on_screen, "data telop", style_block, language),
                                language),
                evidence_status=claim.verification_status,
                checked_against=checked,
                caution=lang.conflicting(language),
            )
            flagged = flagged or entry
            out.append(entry)
        else:
            entry = TelopEntry(
                project_id=project_id, script_line_id=line.id,
                in_seconds=line.start_seconds, out_seconds=line.end_seconds,
                telop_type="data",
                text_lines=_fit(_condense(claim.on_screen, "data telop", style_block, language),
                                language),
                evidence_status=claim.verification_status,
                checked_against=checked,
                caution=claim.volatility_note or lang.unbacked(language),
            )
            flagged = flagged or entry
            out.append(entry)

    # Comment follow: the quoted line itself.
    if line.audio_text.strip() and not _is_filler(line.audio_text, language):
        out.append(TelopEntry(
            project_id=project_id, script_line_id=line.id,
            in_seconds=line.start_seconds, out_seconds=line.end_seconds,
            telop_type="comment",
            text_lines=_fit(_condense(line.audio_text, "comment follow", style_block, language),
                            language),
            evidence_status=EvidenceStatus.FOOTAGE_CONFIRMED,
            # The quotation is confirmed as *said*; the figure inside it can
            # still be the one the data telop just warned about. Marking only
            # the data row leaves the same sentence on the sheet as "as
            # recorded", and an edit house working from that sheet would put
            # the disputed figure on screen anyway.
            caution=lang.quotes_disputed_figure(language) if disputed else "",
            # Whatever the verdict, the reader of this row has to be able to
            # find the row that carries it. A sheet is worked down line by line
            # by somebody who was not at the shoot; "as recorded" on its own
            # hides that the figure in this sentence is flagged two rows up.
            same_statement_as=flagged.id if flagged else "",
        ))
    return out


# Backchannel — the noise an interviewer makes to show they are listening.
# Nobody orders a caption for it, and a sheet that lists "Mhm" as a telop reads
# as a transcript dump rather than a director's order.
_BACKCHANNEL = {
    "mhm", "mm", "mmm", "hmm", "uh", "uhh", "um", "umm", "ah", "oh", "yeah",
    "yep", "yes", "ok", "okay", "right", "sure", "i see", "wow",
    "ええ", "うん", "うーん", "はい", "ふーん", "へえ", "へー", "あー", "えー",
}


def _is_filler(text: str, language: str) -> bool:
    """True when the whole line is a backchannel and nothing else.

    Deliberately narrow: it must match a listed token after punctuation is
    stripped. A short line that carries any content of its own is kept, because
    dropping something a speaker actually said is the worse failure.
    """
    bare = re.sub(r"[\s。、．，.,!?！？…・~〜ー―\-]+$", "", text.strip().lower())
    bare = re.sub(r"^[\s\-–—]+", "", bare)
    return bare in _BACKCHANNEL


def _condense(material: str, telop_type: str, style_block: str = "",
              language: str = lang.JA) -> str:
    if gemini.mock or not material.strip():
        return _strip_punctuation(material, language)
    try:
        limits = lang.CAPTION_LIMITS[language]
        result = gemini.structured(
            _CONDENSE_PROMPT.format(max_lines=limits["max_lines"],
                                    max_chars=limits["max_chars"],
                                    audience=lang.CAPTION_AUDIENCE[language],
                                    caption_rules=lang.CAPTION_RULES[language],
                                    telop_type=telop_type, material=material,
                                    house_style=style_block),
            _Condensed,
        )
        if result.lines:
            return "\n".join(result.lines)
    except Exception:
        pass
    return _strip_punctuation(material, language)


def _strip_punctuation(text: str, language: str = lang.JA) -> str:
    """A Japanese telop carries no 。 or 、 — phrases are separated by a full-width
    space instead. An English lower third keeps its commas and loses only the
    full stop that would otherwise end it.

    An English caption also opens with a capital. The material is often lifted
    from the middle of a sentence — "behind this counter 22 years" — and a sheet
    where some rows start lower case and others upper reads as careless work,
    not as a faithful record of how the speaker said it."""
    if language == lang.JA:
        return re.sub(r"[、。]+", "　", text).strip("　 ")
    text = re.sub(r"\s*\.\s*$", "", text.strip())
    # Only the very first letter, and only when the whole opening word is lower
    # case: a caption may legitimately open with a figure ("22 years") or with a
    # name that carries its own capital inside it ("iPhone", "eBay"), and
    # neither of those is a typing slip to correct.
    first = text.split(" ", 1)[0]
    if first[:1].islower() and first == first.lower():
        return text[:1].upper() + text[1:]
    return text


def _sep(language: str) -> str:
    """What sits between two phrases sharing a line."""
    return "　" if language == lang.JA else " "


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


def _wrap(text: str, language: str = lang.JA) -> list[str]:
    """Break at phrase boundaries first — those are the natural break points in
    both conventions. Breaking mid-phrase is a last resort for a phrase that is
    itself too long for one line."""
    max_chars = lang.CAPTION_LIMITS[language]["max_chars"]
    sep = _sep(language)
    phrases = [p for p in re.split(r"[　 ]+", text) if p]
    lines: list[str] = []
    current = ""
    for phrase in phrases:
        candidate = f"{current}{sep}{phrase}" if current else phrase
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        if len(phrase) <= max_chars:
            current = phrase
        else:
            chunks, chunk = [], ""
            for token in _tokens(phrase):
                if chunk and len(chunk) + len(token) > max_chars:
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


def _fit(text: str, language: str = lang.JA) -> list[str]:
    """Wrap to the line limit. Never drop characters — an over-long telop is a
    decision for the director, so the overflow stays visible in the last line."""
    text = _strip_punctuation(text, language)
    if "\n" in text:
        candidate = [l.strip() for l in text.split("\n") if l.strip()]
    else:
        candidate = _wrap(text, language)
    max_lines = lang.CAPTION_LIMITS[language]["max_lines"]
    if len(candidate) <= max_lines:
        return candidate
    head = candidate[:max_lines - 1]
    return head + [_sep(language).join(candidate[max_lines - 1:])]
