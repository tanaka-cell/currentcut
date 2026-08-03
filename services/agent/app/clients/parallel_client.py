"""Parallel Search API client — the ONLY module allowed to make outbound
search calls. Every call passes the egress gate and writes EgressLog records
before and after. Raw transcripts and restricted-label content never leave.

Real API (docs.parallel.ai): POST {base}/v1/search, header `x-api-key`,
body {objective, search_queries, mode, source_policy{after_date,...}}.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

from .. import config
from ..models.schemas import Claim, Confidentiality, EgressLog, ResearchResult, Segment, RESTRICTED_LABELS
from ..storage import store


class EgressBlocked(Exception):
    pass


class SearchPage(BaseModel):
    url: str
    title: str = ""
    excerpt: str = ""
    published_at: str = ""


class SearchResponse(BaseModel):
    pages: list[SearchPage] = []
    provider: str = "parallel"


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def egress_check(claim: Claim, segment: Segment, query: str) -> tuple[bool, str]:
    """Deterministic gate. Returns (allowed, reason). Fails closed."""
    if segment.confidentiality in RESTRICTED_LABELS:
        return False, f"segment label {segment.confidentiality.value} forbids external search"
    if not segment.allow_external_search:
        return False, "segment not cleared for external search"
    if not claim.allow_external_search:
        return False, "claim not cleared for external search"
    if claim.requires_human_approval:
        return False, "claim requires human approval before external search"
    if not query or len(query) > 160:
        return False, "query missing or too long"
    # The safe query must not smuggle raw transcript sentences out:
    # reject if any 12+ char run of the raw transcript appears in the query.
    nq, nt = _norm(query), _norm(segment.transcript)
    if len(nt) >= 12:
        for i in range(0, len(nt) - 11):
            if nt[i:i + 12] in nq:
                return False, "query contains raw transcript text"
    return True, "ok"


class ParallelClient:
    def __init__(self) -> None:
        self.mock = config.parallel_is_mock()
        self.calls_this_run = 0

    @property
    def provider(self) -> str:
        return "mock" if self.mock else "parallel"

    def search_for_claim(
        self,
        project_id: str,
        claim: Claim,
        segment: Segment,
        after_date: str | None = None,
    ) -> list[ResearchResult]:
        query = claim.safe_search_query or ""
        allowed, reason = egress_check(claim, segment, query)

        log = EgressLog(
            project_id=project_id, claim_id=claim.id, segment_id=segment.id,
            classification=segment.confidentiality.value, query_sent=query if allowed else "",
            provider=self.provider, status="pending", reason=reason,
        )
        if not allowed:
            log.status = "blocked"
            store.put(project_id, "egress_log", log)
            raise EgressBlocked(reason)
        if self.calls_this_run >= config.PARALLEL_MAX_SEARCHES_PER_RUN:
            log.status = "blocked"
            log.reason = "per-run search budget exhausted"
            store.put(project_id, "egress_log", log)
            raise EgressBlocked(log.reason)

        log.status = "sent"
        store.put(project_id, "egress_log", log)
        self.calls_this_run += 1

        try:
            response = self._mock_search(query) if self.mock else self._real_search(query, after_date)
            log.status = "completed"
            log.result_count = len(response.pages)
        except Exception as exc:
            log.status = "failed"
            log.reason = str(exc)[:200]
            store.put(project_id, "egress_log", log)
            raise
        store.put(project_id, "egress_log", log)

        results = []
        for page in response.pages:
            results.append(ResearchResult(
                claim_id=claim.id,
                source_url=page.url,
                source_title=page.title,
                source_domain=urlparse(page.url).netloc,
                published_at=page.published_at,
                excerpt=page.excerpt[:500],
                source_type=self._source_type(page.url),
            ))
        return results

    def _real_search(self, query: str, after_date: str | None) -> SearchResponse:
        body: dict = {
            "objective": f"Verify for a TV news feature: {query}",
            "search_queries": [query],
            "mode": "basic",
        }
        if after_date:
            body["source_policy"] = {"after_date": after_date}
        r = httpx.post(
            f"{config.PARALLEL_BASE_URL}/v1/search",
            headers={"x-api-key": config.PARALLEL_API_KEY, "Content-Type": "application/json"},
            json=body,
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        pages = [
            SearchPage(
                url=p.get("url", ""),
                title=p.get("title", ""),
                excerpt=" ".join(p.get("excerpts", [])) if p.get("excerpts") else p.get("excerpt", ""),
                published_at=p.get("published_date", "") or p.get("publish_date", ""),
            )
            for p in data.get("pages", data.get("results", []))
        ]
        return SearchResponse(pages=pages, provider="parallel")

    def _mock_search(self, query: str) -> SearchResponse:
        """Deterministic fake results keyed off the query so demos are stable."""
        results = {
            "店舗": SearchPage(
                url="https://demo.currentcut.example/press/stores-2026",
                title="スマートベントー社 公式: 全国店舗数のご案内",
                excerpt="2026年8月現在、全国80店舗で展開しています。",
                published_at="2026-07-15",
            ),
            "価格": SearchPage(
                url="https://demo.currentcut.example/products/smartbento",
                title="SmartBento 製品ページ",
                excerpt="希望小売価格 1,980円(税込)。",
                published_at="2026-07-01",
            ),
            "市場": SearchPage(
                url="https://www.e-stat.go.jp/",
                title="政府統計の総合窓口(e-Stat)",
                excerpt="関連する公的統計データ。",
                published_at="2026-06-30",
            ),
        }
        for key, page in results.items():
            if key in query:
                return SearchResponse(pages=[page], provider="mock")
        return SearchResponse(pages=[SearchPage(
            url="https://demo.currentcut.example/search",
            title=f"[mock] result for: {query[:60]}",
            excerpt="Mock evidence excerpt.",
            published_at="2026-08-01",
        )], provider="mock")

    @staticmethod
    def _source_type(url: str) -> str:
        host = urlparse(url).netloc
        if host.endswith(".go.jp") or host.endswith(".gov"):
            return "government"
        if "press" in url or "corporate" in url or "official" in host:
            return "official"
        return "web"


parallel = ParallelClient()
