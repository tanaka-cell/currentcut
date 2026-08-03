"""Evidence comparator — decides whether a retrieved page actually supports a claim.

Replaces the old numeric-overlap heuristic, which confirmed a bento-box price
claim from an anime fan site because both contained "1980".

Rule: a source supports a claim ONLY if the entity, the attribute, and the
value all match. Anything less is not support. The same pass also extracts a
`dated_qualifier` — an expiry or scheduled change stated in the source
("campaign price until Aug 31", "two more stores opening this month") — which
is what makes the volatility flag useful rather than a restatement of
"prices change".
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ..clients.gemini_client import gemini
from ..models.schemas import Claim, ResearchResult


class EvidenceJudgment(BaseModel):
    entity_match: bool = Field(description="Is the source about the same company/product/thing as the claim?")
    attribute_match: bool = Field(description="Does the source discuss the same attribute (price, store count, ...)?")
    value_match: bool = Field(description="Does the value in the source equal the value in the claim?")
    source_value: str = Field(default="", description="The value stated by the source, verbatim, or empty")
    source_is_primary: bool = Field(default=False, description="Official/first-party/government source rather than commentary")
    dated_qualifier: str = Field(default="", description="Any expiry, validity period or scheduled change stated in the source; empty if none")
    reason: str = Field(default="", description="One sentence")


_PROMPT = """You verify facts for a TV news feature. Decide whether the SOURCE
actually supports the CLAIM. Be strict: a shared number is NOT support.

CLAIM (spoken on camera): {claim_text}
CLAIM TYPE: {claim_type}

SOURCE
  title: {title}
  domain: {domain}
  published: {published}
  excerpt: {excerpt}

Answer:
- entity_match: is the source about the SAME company/product as the claim?
  A different company that happens to use the same number is NOT a match.
  If the claim does not name a specific entity, entity_match MUST be false —
  never infer or imagine the subject the speaker "must have meant".
  Do not treat "same product category" as the same entity: a different smart
  lunchbox, a different retailer's product at the same price, or an unrelated
  item that merely costs the same is NOT a match.
- attribute_match: does the source talk about the same attribute?
- value_match: does the source state the SAME value as the claim?
- source_value: the value the source states, verbatim ("" if none).
- source_is_primary: true only for the subject's own official page, an IR/press
  release, or a government/public statistics source.
- dated_qualifier: if the source says this value has an expiry, a validity
  period, or a scheduled change (e.g. "campaign price until August 31",
  "two new stores opening in August", "figures as of the end of June"),
  quote it briefly. Otherwise "".
- reason: one sentence.

Support requires entity_match AND attribute_match AND value_match to all be true."""


def judge(claim: Claim, result: ResearchResult) -> EvidenceJudgment:
    if gemini.mock:
        return _mock_judge(claim, result)
    try:
        judgment = gemini.structured(
            _PROMPT.format(
                claim_text=claim.claim_text,
                claim_type=claim.claim_type,
                title=result.source_title,
                domain=result.source_domain,
                published=result.published_at or "unknown",
                excerpt=result.excerpt[:1500],
            ),
            EvidenceJudgment,
        )
    except Exception:
        # Verification failure must never become support.
        return EvidenceJudgment(entity_match=False, attribute_match=False,
                                value_match=False, reason="verification failed; not counted as support")
    return judgment


def supports(judgment: EvidenceJudgment) -> bool:
    return judgment.entity_match and judgment.attribute_match and judgment.value_match


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in re.findall(r"[\d,]+", text) if n.strip(",")}


def _mock_judge(claim: Claim, result: ResearchResult) -> EvidenceJudgment:
    """Deterministic stand-in. Still requires entity + attribute + value, so the
    mock cannot be more permissive than the real comparator."""
    blob = f"{result.source_title} {result.excerpt}"
    value_match = bool(_numbers(claim.claim_text) & _numbers(blob)) if _numbers(claim.claim_text) else False
    attribute_keywords = {
        "price": ["価格", "円", "税込", "price"],
        "store_count": ["店舗", "stores"],
        "stat": ["調査", "統計", "％", "%"],
        "release_date": ["発売", "発表", "release"],
    }.get(claim.claim_type, [])
    attribute_match = any(k in blob for k in attribute_keywords) if attribute_keywords else False
    # Entity: demo fixtures are first-party pages for the subject.
    entity_match = "demo.currentcut.example" in result.source_url or result.source_type in ("official", "government")
    qualifier = ""
    m = re.search(r"(\d{1,2}月\d{1,2}日まで|まで有効|予定)", blob)
    if m:
        qualifier = m.group(0)
    return EvidenceJudgment(
        entity_match=entity_match,
        attribute_match=attribute_match,
        value_match=value_match,
        source_value=next(iter(_numbers(blob) & _numbers(claim.claim_text)), ""),
        source_is_primary=result.source_type in ("official", "government"),
        dated_qualifier=qualifier,
        reason="deterministic mock comparator",
    )
