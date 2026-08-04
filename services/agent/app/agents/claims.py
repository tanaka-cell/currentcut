"""Claim Extraction Agent — verifiable claims + safe external search queries.

The safe query never quotes the transcript; it is rebuilt from entity + metric
keywords ("○○社 店舗数 公式 2026" style), enforced again by the egress gate.
"""
from __future__ import annotations

import re

from pydantic import BaseModel

from .. import lang
from ..clients.gemini_client import gemini
from ..fanout import fan_out
from ..models.schemas import Claim, Segment, Verifiability
from ..storage import store

# Claim types whose facts change often → re-check before air.
_VOLATILITY = {
    "price": "high", "store_count": "high", "ranking": "high",
    "popularity": "high", "stat": "medium", "release_date": "medium",
    "superlative": "medium", "other": "low",
}
# "人気/話題" style claims need a human before searching (brief §6).
_HUMAN_APPROVAL_TYPES = {"popularity", "superlative"}

# What the director is told about a claim nobody could look up. Written in the
# language of the shoot, because it lands on the order sheet somebody reads —
# see app/lang.py.
_UNCHECKABLE_NOTE = lang.UNCHECKABLE_NOTE


class _LlmClaim(BaseModel):
    claim_text: str
    claim_subject: str
    claim_type: str
    verifiability: str = "public_record"
    safe_search_query: str
    publisher_search_query: str = ""


class _LlmClaims(BaseModel):
    claims: list[_LlmClaim]


_LLM_PROMPT = """You extract verifiable factual claims from TV interview transcripts.
From the transcript below, list claims that can be checked against public web
sources (counts, prices, dates, stats, rankings, superlatives like "first/biggest",
popularity claims like "popular/trending").

WRITE EVERYTHING — claim_text, claim_subject and both queries — IN THE SAME
LANGUAGE AS THE TRANSCRIPT. The examples below are in that language too.

CRITICAL: every claim must be SELF-CONTAINED. The claim_text must name what the
claim is about, even when the speaker only said "{ex_subjectless}".
Write "{ex_self_contained}" — never a bare "{ex_subjectless}". A claim without
its subject cannot be verified, because any page containing that number would
appear to match.
claim_subject: the thing the claim is really about — see verifiability below,
because for a public rule or a national figure the subject is that public thing,
NOT the speaker. "" only if nothing identifiable is named.

verifiability: which of these three the claim is. This decides whether it is
checked at all, so read the cases carefully.
- "public_record": the substance is published somewhere public — national or
  industry statistics, a statutory rate, a law or regulation, an organisation's
  own official figures. **A statutory or nationally-set figure stays
  public_record even when the speaker says it about themselves.**
  {ex_first_person_rule} — the speaker does not set it, so the subject is that
  public thing, not their business. Same for a licence fee, a tax rate, a
  subsidy amount, an industry-wide total.
  Set claim_subject to the public thing (e.g. {ex_public_subject}), and write
  claim_text so it states the public fact.
- "own_business": a figure only the speaker could know, because nobody publishes
  it — their own takings, their own headcount, their own customer numbers, how
  long they personally have traded. Searching for these returns unrelated pages
  that merely share a number.
- "unidentified_subject": the claim is about something real but unnamed —
  {ex_unnamed}. No source can ever be about the same entity, so it cannot be
  checked. Do NOT guess a name.

A claim has to ASSERT something a viewer could be wrong about — a figure, a
date, a rank, a comparison, a change. Skip anything that merely says the subject
exists or that the speaker is subject to it. From "we pay the federal minimum
wage here, seven twenty-five an hour", the claim is that the rate IS $7.25, not
that a federal minimum wage exists; "there is a federal minimum wage" would be
checked, confirmed, and put on screen saying nothing. Interviews are split one
sentence per segment, so a sentence on its own often reads as a bare mention —
use the CONTEXT to recover what was actually being asserted.

Extract ALL THREE KINDS. own_business and unidentified_subject claims are not
searched, but they are still spoken on camera and still need captions, so
leaving them out loses them from the script and the telop sheet. Never drop a
claim because it cannot be checked — label it and move on.
If a sentence contains both a public fact and the speaker's own situation,
extract them as two claims with the labels they each deserve.

For each claim build TWO search queries. Short keywords only, never a quoted
transcript sentence:
- safe_search_query: entity + metric + year (+ the figure itself if the claim
  states one — the page that states the number is the one we need).
- publisher_search_query: the same fact aimed at whoever actually publishes it —
  name the ministry, agency, statistics office, industry association or the
  organisation's own press pages ({ex_publisher_queries}).
  Leave "" if you genuinely cannot name a likely publisher.
claim_type: one of store_count/price/release_date/stat/ranking/superlative/popularity/other.

CONTEXT is background only — use it to work out what the speaker is referring
to. Extract claims ONLY from TRANSCRIPT. Do not extract claims that appear in
CONTEXT but not in TRANSCRIPT.

CONTEXT (other utterances in this shoot): {context}
TRANSCRIPT (speaker {speaker}) — extract from this only: {transcript}
Return JSON."""

# Deterministic extraction for mock mode / tests.
_MOCK_RULES = [
    (r"(?P<num>[\d,]+)\s*店舗", "store_count", "店舗数 統計 公式 2026"),
    (r"(?P<num>[\d,]+)\s*円", "price", "価格 公式 2026"),
    (r"満足度\s*(?P<num>[\d.]+)\s*[%％]", "stat", "満足度 調査 統計 2026"),
    (r"(人気|話題|バズって)", "popularity", "人気 調査 2026"),
    (r"(日本初|業界初|最大|唯一)", "superlative", "日本初 公式 2026"),
]


def extract_claims(project_id: str, segments: list[Segment]) -> list[Claim]:
    claims: list[Claim] = []
    language = lang.of_segments(segments)
    # Speakers drop the subject after introducing it ("...and the price is
    # 1,980 yen"). Carry earlier utterances so the extractor can restore it.
    context = " / ".join(s.transcript for s in segments if s.transcript.strip())[:1200]
    spoken = [s for s in segments if s.transcript.strip()]

    def read_one(seg: Segment):
        if gemini.mock:
            return _mock_extract(seg.transcript)
        try:
            llm = gemini.structured(
                _LLM_PROMPT.format(speaker=seg.speaker or "unknown",
                                   transcript=seg.transcript, context=context,
                                   **_examples(language)),
                _LlmClaims,
            )
            return [
                (_with_subject(c.claim_text, c.claim_subject), c.claim_type,
                 c.safe_search_query, _verifiability(c.verifiability),
                 [q for q in (c.publisher_search_query,) if q.strip()])
                for c in llm.claims
            ]
        except Exception:
            return _mock_extract(seg.transcript)  # degraded, still safe

    # Read every segment at once, then fold the results in order. The folding
    # stays sequential on purpose: "have I already seen this fact?" is answered
    # against the claims kept so far, so the order decides which wording of a
    # repeated fact is the one that gets verified.
    per_segment = fan_out(spoken, read_one)

    for seg, extracted in zip(spoken, per_segment):
        # Restricted segments are still analyzed internally (mining them for
        # claims is fine) but their claims may never reach external search.
        externally_searchable = seg.allow_external_search
        for claim_text, claim_type, safe_query, verifiability, extra in extracted:
            if _seen_before(claim_text, claim_type, claims):
                continue  # same fact restated; verify it once
            needs_human = claim_type in _HUMAN_APPROVAL_TYPES
            # Only claims a public source could actually settle are searched.
            # The other two kinds are attributed to the speaker instead: looking
            # them up returns pages that merely share a number.
            checkable = verifiability is Verifiability.PUBLIC_RECORD
            searchable = externally_searchable and not needs_human and checkable
            claims.append(Claim(
                segment_id=seg.id,
                claim_text=claim_text,
                claim_type=claim_type,
                volatility=_VOLATILITY.get(claim_type, "medium"),
                verifiability=verifiability,
                safe_search_query=safe_query if searchable else None,
                extra_search_queries=extra if searchable else [],
                allow_external_search=searchable,
                requires_human_approval=needs_human,
                volatility_note=_UNCHECKABLE_NOTE[language].get(verifiability, ""),
            ))
    store.put_many(project_id, "claims", claims)
    return claims


def _key(text: str) -> str:
    return re.sub(r"[\s、。,.:：]|です|ます|である|されている|いる", "", text)


def _seen_before(claim_text: str, claim_type: str, claims: list[Claim]) -> bool:
    """Speakers restate the same number across takes; each restatement is the
    same fact and should cost one verification, not several."""
    key = _key(claim_text)
    for existing in claims:
        if existing.claim_type != claim_type:
            continue
        other = _key(existing.claim_text)
        if key == other or key in other or other in key:
            return True
    return False


def _mentions(claim_text: str, subject: str) -> bool:
    """Is the subject already in the claim, however it happens to be written?

    An exact substring test said no to subject "small businesses in this
    country" inside "Small businesses in this country employ almost half of the
    private workforce" — because of one capital letter — and the caption went
    out reading "small businesses in this country: Small businesses in this
    country employ almost half…".
    """
    def norm(s: str) -> str:
        return re.sub(r"[\s　、。,.:：'’\"()（）-]+", "", s).casefold()

    return norm(subject) in norm(claim_text)


def _with_subject(claim_text: str, subject: str) -> str:
    """Belt and braces: if the model still returned a subjectless claim, prefix
    the subject it identified. A claim with no subject verifies against anything."""
    if not subject or _mentions(claim_text, subject):
        return claim_text
    return f"{subject}: {claim_text}"


def _examples(language: str) -> dict:
    """Prompt examples in the shoot's own language — see lang.CLAIM_EXAMPLES."""
    return {f"ex_{k}": v for k, v in lang.CLAIM_EXAMPLES[language].items()}


def _verifiability(raw: str) -> Verifiability:
    """Unknown values fall back to the un-searchable side. A claim wrongly held
    back is a caption the director writes by hand; a claim wrongly sent out is
    an unrelated page presented as evidence."""
    try:
        return Verifiability(raw.strip().lower())
    except ValueError:
        return Verifiability.UNIDENTIFIED_SUBJECT


def _mock_extract(transcript: str) -> list[tuple[str, str, str, Verifiability, list[str]]]:
    found = []
    for pattern, claim_type, query in _MOCK_RULES:
        m = re.search(pattern, transcript)
        if m:
            found.append((m.group(0), claim_type, query, Verifiability.PUBLIC_RECORD, []))
    return found
