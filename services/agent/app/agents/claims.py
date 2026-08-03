"""Claim Extraction Agent — verifiable claims + safe external search queries.

The safe query never quotes the transcript; it is rebuilt from entity + metric
keywords ("○○社 店舗数 公式 2026" style), enforced again by the egress gate.
"""
from __future__ import annotations

import re

from pydantic import BaseModel

from ..clients.gemini_client import gemini
from ..models.schemas import Claim, Segment
from ..storage import store

# Claim types whose facts change often → re-check before air.
_VOLATILITY = {
    "price": "high", "store_count": "high", "ranking": "high",
    "popularity": "high", "stat": "medium", "release_date": "medium",
    "superlative": "medium", "other": "low",
}
# "人気/話題" style claims need a human before searching (brief §6).
_HUMAN_APPROVAL_TYPES = {"popularity", "superlative"}


class _LlmClaim(BaseModel):
    claim_text: str
    claim_type: str
    safe_search_query: str


class _LlmClaims(BaseModel):
    claims: list[_LlmClaim]


_LLM_PROMPT = """You extract verifiable factual claims from TV interview transcripts.
From the transcript below, list claims that can be checked against public web
sources (counts, prices, dates, stats, rankings, superlatives like "first/biggest",
popularity claims like "popular/trending").
For each claim build a SAFE search query: short keywords only
(entity + metric + "公式" + year). NEVER quote the transcript sentence itself.
Write claim_text in the same language as the transcript.
claim_type: one of store_count/price/release_date/stat/ranking/superlative/popularity/other.
Transcript (speaker {speaker}): {transcript}
Return JSON."""

# Deterministic extraction for mock mode / tests.
_MOCK_RULES = [
    (r"(?P<num>[\d,]+)\s*店舗", "store_count", "スマートベントー 店舗数 公式 2026"),
    (r"(?P<num>[\d,]+)\s*円", "price", "SmartBento 価格 公式 2026"),
    (r"満足度\s*(?P<num>[\d.]+)\s*[%％]", "stat", "弁当箱 市場 満足度 調査 2026"),
    (r"(人気|話題|バズって)", "popularity", "スマート弁当箱 人気 2026"),
    (r"(日本初|業界初|最大|唯一)", "superlative", "スマート弁当箱 日本初 2026"),
]


def extract_claims(project_id: str, segments: list[Segment]) -> list[Claim]:
    claims: list[Claim] = []
    for seg in segments:
        if not seg.transcript.strip():
            continue
        # Restricted segments are still analyzed internally (mining them for
        # claims is fine) but their claims may never reach external search.
        externally_searchable = seg.allow_external_search

        if gemini.mock:
            extracted = _mock_extract(seg.transcript)
        else:
            try:
                llm = gemini.structured(
                    _LLM_PROMPT.format(speaker=seg.speaker or "unknown", transcript=seg.transcript),
                    _LlmClaims,
                )
                extracted = [(c.claim_text, c.claim_type, c.safe_search_query) for c in llm.claims]
            except Exception:
                extracted = _mock_extract(seg.transcript)  # degraded, still safe

        for claim_text, claim_type, safe_query in extracted:
            needs_human = claim_type in _HUMAN_APPROVAL_TYPES
            claims.append(Claim(
                segment_id=seg.id,
                claim_text=claim_text,
                claim_type=claim_type,
                volatility=_VOLATILITY.get(claim_type, "medium"),
                safe_search_query=safe_query if externally_searchable else None,
                allow_external_search=externally_searchable and not needs_human,
                requires_human_approval=needs_human,
            ))
    store.put_many(project_id, "claims", claims)
    return claims


def _mock_extract(transcript: str) -> list[tuple[str, str, str]]:
    found = []
    for pattern, claim_type, query in _MOCK_RULES:
        m = re.search(pattern, transcript)
        if m:
            found.append((m.group(0), claim_type, query))
    return found
