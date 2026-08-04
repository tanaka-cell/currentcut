"""Evidence comparator — decides whether a retrieved page actually supports a claim.

Replaces the old numeric-overlap heuristic, which confirmed a bento-box price
claim from an anime fan site because both contained "1980".

Rule: a source supports a claim ONLY if the entity, the attribute, and the
value all match. Anything less is not support. The same pass also extracts a
`dated_qualifier` — an expiry or scheduled change stated in the source
("campaign price until Aug 31", "two more stores opening this month") — which
is what makes the volatility flag useful rather than a restatement of
"prices change", and `value_as_of_year`, so a figure that was true a decade ago
cannot confirm a claim spoken in the present tense.

All the sources for one claim are judged in a single call. That is a speed fix
(ten round trips became one) but not a licence to blur them: the model returns
one verdict per source, and `_align` refuses to guess which source an unlabelled
verdict belongs to.
"""
from __future__ import annotations

import re
import time

from pydantic import BaseModel, Field

from .. import config
from ..clients.gemini_client import gemini
from ..models.schemas import Claim, ResearchResult


_JUDGE_ATTEMPTS = 3
_JUDGE_BACKOFF_SECONDS = 2.0


class EvidenceJudgment(BaseModel):
    entity_match: bool = Field(description="Is the source about the same company/product/thing as the claim?")
    attribute_match: bool = Field(description="Does the source discuss the same attribute (price, store count, ...)?")
    value_match: bool = Field(description="Does the value in the source equal the value in the claim?")
    source_value: str = Field(default="", description="The value stated by the source, verbatim, or empty")
    contradicts_claim: bool = Field(default=False, description="Does the source state something that makes the claim FALSE?")
    claim_names_its_own_date: bool = Field(default=False, description="Does the CLAIM itself specify the period it describes, so old evidence is the right evidence?")
    source_is_primary: bool = Field(default=False, description="Official/first-party/government source rather than commentary")
    dated_qualifier: str = Field(default="", description="Any expiry, validity period or scheduled change stated in the source; empty if none")
    value_as_of_year: int = Field(default=0, description="Year the source's figure describes (not the publication year); 0 if not stated")
    reason: str = Field(default="", description="One sentence")


_RULES = """Answer for each source:
- entity_match: is the source about the SAME company/product as the claim?
  A different company that happens to use the same number is NOT a match.
  If the claim does not name a specific entity, entity_match MUST be false —
  never infer or imagine the subject the speaker "must have meant".
  Do not treat "same product category" as the same entity: a different smart
  lunchbox, a different retailer's product at the same price, or an unrelated
  item that merely costs the same is NOT a match.
  A single brand or chain is NOT the same entity as its whole industry, and the
  reverse is also false. If the claim is about all convenience stores in the
  country and the source reports one chain's store count, entity_match is false.
  If the claim is about one company and the source gives an industry total,
  entity_match is false.
- attribute_match: does the source talk about the same attribute?
- value_match: does the source state the SAME value as the claim?
  When the claim is explicitly approximate ("およそ", "約", "ほど", "around",
  "roughly"), the speaker is rounding, and a source figure that rounds to the
  claimed value AT THE CLAIM'S OWN PRECISION is a match: "およそ5万6千店" is
  supported by an official 55,979 and NOT by 52,010. When the claim states an
  exact value, the source must state that exact value.
  If the source discusses the right subject and attribute but the excerpt never
  states a figure, value_match is false — do not infer it.
- source_value: the value the source states, verbatim ("" if none).
- contradicts_claim: true ONLY if the source states something that makes the
  claim FALSE — the same subject and attribute with a genuinely different value.
  Failing to support is NOT contradicting. A source that gives a range, a
  history, a related figure, or simply does not address the point is not a
  contradiction: "the federal minimum wage has been $7.25 since 2009" is not
  contradicted by a page listing "1938 - 2009" as the history of the rate.
  When in doubt, false — telling a director not to broadcast a true line is as
  damaging as letting a false one through.
- source_is_primary: true only for the subject's own official page, an IR/press
  release, or a government/public statistics source.
- dated_qualifier: ONLY when the source limits how long this value stays true,
  in a way a director would need to act on before broadcast. Three cases count:
  an expiry still ahead ("campaign price until August 31"), a scheduled change
  ("two new stores open in August", "the rate changes in October"), or an
  as-of date on a figure that is republished on a cycle ("as of the end of
  June", "May estimate"). Otherwise return "".
  Do NOT return historical background dates, when a rule was originally
  introduced, publication dates of the article, or anything already in the past
  with no bearing on whether the figure is still current.
- claim_names_its_own_date: true when the CLAIM itself fixes the period it is
  about — "unchanged since 2009", "in the year to March", "before the 2019
  reform". Such a claim cannot go out of date, and a source describing that
  period is exactly the right source for it: the Department of Labor's own page
  saying "the federal minimum wage is $7.25 per hour effective July 24, 2009"
  states the claim word for word. False for a claim in the present tense —
  "there are about 56,000 of them now" — which needs current evidence.
- value_as_of_year: for a MEASURED figure — something counted, surveyed or
  observed at a moment in time — the year that measurement describes, as stated
  by the source ("2014年度末時点の55,774店" → 2014). Not the year the article was
  published or updated. 0 if the source does not say.
  Return 0 for a RULE that is in force: a tax rate, a statutory fee, a legal
  limit, a standard. A rate introduced in 2019 and still applying today is not a
  2019 figure — it is the current rate, and the year it came in says nothing
  about whether it still holds. Only give a year here if the source itself says
  the rule has since changed or is about to.
- reason: one sentence.

Support requires entity_match AND attribute_match AND value_match to all be true."""


class _BatchJudgment(EvidenceJudgment):
    source_index: int = Field(default=-1, description="Index of the source being judged")


class _BatchJudgments(BaseModel):
    judgments: list[_BatchJudgment]


_BATCH_PROMPT = """You verify facts for a TV news feature. For EACH source below,
decide whether it actually supports the CLAIM. Be strict: a shared number is NOT
support. Judge every source independently and return one judgment per source,
with source_index set to that source's number.

CLAIM (spoken on camera): {claim_text}
CLAIM TYPE: {claim_type}

SOURCES
{sources}

{rules}"""


def judge_all(claim: Claim, results: list[ResearchResult]) -> list[EvidenceJudgment]:
    """One call for every source of a claim, rather than one call per source.

    Ten separate calls per claim made a run take minutes and gave the comparator
    no way to see that two sources disagree. The judgments stay independent —
    the prompt asks for one verdict per source — but they cost one round trip.
    """
    if not results:
        return []
    if gemini.mock:
        return [_mock_judge(claim, r) for r in results]

    blocks = []
    for i, r in enumerate(results):
        blocks.append(
            f"[{i}] title: {r.source_title}\n"
            f"    domain: {r.source_domain}\n"
            f"    published: {r.published_at or 'unknown'}\n"
            f"    excerpt: {r.excerpt[:config.EXCERPT_JUDGE_CHARS]}"
        )
    prompt = _BATCH_PROMPT.format(
        claim_text=claim.claim_text,
        claim_type=claim.claim_type,
        sources="\n\n".join(blocks),
        rules=_RULES,
    )
    # A transient API error used to wipe out every source for a claim and read
    # exactly like "no source supported it" — which is how the demo lost its
    # sourced line. Retry, then say plainly that the check did not run.
    # A reply that comes back but lands on no source at all is the same outage
    # wearing a 200, so it is retried on the same terms rather than accepted.
    last_error = "no verdict returned for this source"
    for attempt in range(_JUDGE_ATTEMPTS):
        try:
            aligned = _align(gemini.structured(prompt, _BatchJudgments).judgments, len(results))
            if not all(map(did_not_run, aligned)):
                return aligned
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"[:200]
        if attempt + 1 < _JUDGE_ATTEMPTS:
            time.sleep(_JUDGE_BACKOFF_SECONDS * (attempt + 1))

    # Verification failure must never become support.
    return [_failed_judgment(last_error) for _ in results]


def _align(judgments: list[_BatchJudgment], count: int) -> list[EvidenceJudgment]:
    """Line the model's verdicts up with the sources they were about.

    The model often omits source_index altogether, and keying purely on it
    discarded every judgment in the batch — the whole run then read as "nothing
    supports any of this". So: if any verdict carries an index, indices are
    authoritative and a source without one is simply unjudged. If none do, fall
    back to position, and only when the counts agree exactly — a short list of
    unlabelled verdicts tells us nothing about which sources they describe, and
    guessing would attach a verdict to the wrong source.
    """
    indexed = {j.source_index: j for j in judgments if j.source_index >= 0}
    positional = judgments if not indexed and len(judgments) == count else []

    out: list[EvidenceJudgment] = []
    for i in range(count):
        j = indexed.get(i) or (positional[i] if positional else None)
        # A source the model returned no verdict for is unjudged, and unjudged
        # is not support.
        out.append(EvidenceJudgment(**j.model_dump(exclude={"source_index"}))
                   if j else _failed_judgment("no verdict returned for this source"))
    return out


# EvidenceJudgment doubles as the Gemini response schema, so a "did the check
# run" flag cannot live on it — the model would fill it in. The reason carries
# the distinction instead, and `did_not_run` is the one place that reads it.
NOT_RUN_PREFIX = "verification did not run"


def _failed_judgment(error: str = "") -> EvidenceJudgment:
    detail = f" ({error})" if error else ""
    return EvidenceJudgment(
        entity_match=False, attribute_match=False, value_match=False,
        reason=f"{NOT_RUN_PREFIX}{detail}; not counted as support")


def did_not_run(judgment: EvidenceJudgment) -> bool:
    """True when the comparator never reached a verdict. Distinct from "checked
    and found no support" — the director must not read an outage as a finding."""
    return judgment.reason.startswith(NOT_RUN_PREFIX)


# There is deliberately no single-source `judge()`. It would need its own copy
# of the rules, and two comparator prompts in a repo whose product claim is
# traceability is two answers waiting to disagree. `judge_all` handles one
# source as happily as ten.


def supports(judgment: EvidenceJudgment) -> bool:
    return judgment.entity_match and judgment.attribute_match and judgment.value_match


# A source good enough to be named on air: the body that publishes the figure,
# or the organisation the figure is about.
PRIMARY_SOURCE_TYPES = ("government", "official")


def citable_source(results: list[ResearchResult]) -> ResearchResult | None:
    """The one source that may be printed on screen as 出典, or None.

    Supporting a claim and being fit to name on air are different bars. A
    payments company's explainer of the consumption-tax rates genuinely supports
    "eat-in is 10%" — and putting "出典 stripe.com" under that figure tells the
    viewer the broadcaster got its tax rates from a payments vendor. The
    attribution has to name who actually publishes the number.

    Returning None is a real answer, not a failure: the claim stays checked, the
    telop simply carries no attribution and the director is told to find the
    official release. Naming a source that is merely adjacent is worse than
    naming none.

    `source_type` comes from the URL, decided by code. The comparator's own
    `source_is_primary` is deliberately not consulted here: asked the question
    directly it called nikkei.com and bengo4.com primary sources for a national
    statistic, and one of those reached air. The model finds evidence; the rule
    for what may be credited stays where it can be read and tested.
    """
    primary = [r for r in results
               if r.supports_claim and r.source_type in PRIMARY_SOURCE_TYPES]
    # Deterministic, so the same evidence always yields the same 出典 on the
    # sheet. Both kinds are acceptable; government first is only a tie-break.
    primary.sort(key=lambda r: (PRIMARY_SOURCE_TYPES.index(r.source_type), r.source_url))
    return primary[0] if primary else None


def supporting_domains(results: list[ResearchResult], limit: int = 2) -> list[str]:
    """Who did back the claim, for telling a director where to start looking."""
    seen: list[str] = []
    for r in results:
        if r.supports_claim and r.source_domain and r.source_domain not in seen:
            seen.append(r.source_domain)
    return seen[:limit]


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
