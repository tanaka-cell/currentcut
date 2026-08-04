"""Parallel Search API client — the ONLY module allowed to make outbound
search calls. Every call passes the egress gate and writes EgressLog records
before and after. Raw transcripts and restricted-label content never leave.

Uses the official `parallel-web` SDK (contest Stage-1 checks verify official
SDK imports): from parallel import Parallel; client.search.create(...).
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from pydantic import BaseModel

from .. import config, lang
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
    # The safe query must not smuggle a verbatim span of the transcript out.
    # What counts as a span differs by language — see lang.quotes_transcript.
    if lang.quotes_transcript(query, segment.transcript):
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
        # A keyword query finds pages *about* the subject; a query naming the
        # likely publisher finds the page that actually states the figure. Both
        # go out in one call, and every one of them passes the gate first.
        queries = [q for q in [claim.safe_search_query, *claim.extra_search_queries] if q]
        query = " | ".join(queries)  # what the Egress Log records verbatim
        allowed, reason = True, "ok"
        for q in queries or [""]:
            allowed, reason = egress_check(claim, segment, q)
            if not allowed:
                break

        def record(status: str, reason: str, phase: str = "attempt",
                   attempt_id: str = "", result_count: int = 0) -> EgressLog:
            """Append-only: every write is a new row, so the attempt record
            survives alongside its outcome."""
            entry = EgressLog(
                project_id=project_id, claim_id=claim.id, segment_id=segment.id,
                classification=segment.confidentiality.value,
                query_sent=query if status in ("sent", "completed") else "",
                provider=self.provider, status=status, reason=reason,
                phase=phase, attempt_id=attempt_id, result_count=result_count,
            )
            store.put(project_id, "egress_log", entry)
            return entry

        if not allowed:
            record("blocked", reason)
            raise EgressBlocked(reason)
        if self.calls_this_run >= config.PARALLEL_MAX_SEARCHES_PER_RUN:
            record("blocked", "per-run search budget exhausted")
            raise EgressBlocked("per-run search budget exhausted")

        attempt = record("sent", reason)
        self.calls_this_run += 1

        try:
            response = (self._mock_search(query) if self.mock
                        else self._real_search(queries, after_date))
        except Exception as exc:
            record("failed", str(exc)[:200], phase="outcome", attempt_id=attempt.id)
            raise
        record("completed", "ok", phase="outcome", attempt_id=attempt.id,
               result_count=len(response.pages))

        results = []
        for page in response.pages:
            results.append(ResearchResult(
                claim_id=claim.id,
                source_url=page.url,
                source_title=page.title,
                source_domain=urlparse(page.url).netloc,
                published_at=page.published_at,
                excerpt=page.excerpt[:config.EXCERPT_STORE_CHARS],
                source_type=self._source_type(page.url),
            ))
        return results

    _sdk_client = None

    def _real_search(self, queries: list[str], after_date: str | None) -> SearchResponse:
        from parallel import Parallel  # official SDK, imported lazily

        if self._sdk_client is None:
            type(self)._sdk_client = Parallel(api_key=config.PARALLEL_API_KEY)
        # The objective is outbound too, so it is built from the gated queries
        # and nothing else — never from the claim or the transcript.
        kwargs: dict = {
            "objective": "Find the source that states this figure for a TV news "
                         f"feature, and quote it: {' / '.join(queries)}",
            "search_queries": queries,
            "mode": "basic",
            # Without a budget the API returns snippets too short to contain the
            # number, and every claim then reads as "the source does not state
            # the value". Measured: 42–299 chars per page unset, ~2,500 with it.
            "max_chars_total": config.PARALLEL_MAX_CHARS_TOTAL,
        }
        if after_date:
            kwargs["advanced_settings"] = {"source_policy": {"after_date": after_date}}
        result = self._sdk_client.search(**kwargs)
        pages = []
        for p in getattr(result, "results", None) or getattr(result, "pages", None) or []:
            get = (lambda k, d="": getattr(p, k, None) or (p.get(k, d) if isinstance(p, dict) else d) or d)
            excerpts = get("excerpts", [])
            pages.append(SearchPage(
                url=get("url"),
                title=get("title"),
                excerpt=" ".join(excerpts) if isinstance(excerpts, list) else str(excerpts),
                published_at=get("published_date") or get("publish_date"),
            ))
        return SearchResponse(pages=pages, provider="parallel")

    def _mock_search(self, query: str) -> SearchResponse:
        """Deterministic fake results keyed off the query so demos are stable."""
        results = {
            "店舗": SearchPage(
                url="https://demo.currentcut.example/corporate/ir/stores-2026",
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

    # Press-release distributors and aggregators carry first-party text but are
    # not themselves the source. Attributing an on-air figure to one of these
    # would put the wrong name on screen.
    _DISTRIBUTORS = ("prtimes.jp", "atpress.ne.jp", "value-press.com", "dreamnews.jp",
                     "newscast.jp", "kyodonewsprwire.jp", "note.com", "ameblo.jp",
                     "news.yahoo.co.jp", "news.google.com", "hatenablog.com",
                     # English-language equivalents: wire services that carry
                     # first-party text without being the source of it.
                     "prnewswire.com", "businesswire.com", "globenewswire.com",
                     "einpresswire.com", "medium.com", "substack.com",
                     "reddit.com", "quora.com")

    # Public-authority domains that are reserved by registration, so the suffix
    # alone is proof. Kept to suffixes that cannot be bought: .gov and .go.jp
    # are restricted registries, and a shoot in one country routinely cites
    # another's statistics office, so the whole list applies everywhere.
    _GOVERNMENT_SUFFIXES = (
        ".gov", ".mil",                       # United States
        ".go.jp", ".lg.jp",                   # Japan
        ".gov.uk", ".nhs.uk", ".parliament.uk",  # United Kingdom
        ".gc.ca", ".canada.ca",               # Canada
        ".gov.au",                            # Australia
        ".govt.nz",                           # New Zealand
        ".gov.ie",                            # Ireland
        ".europa.eu",                         # European Union
        ".un.org", ".who.int", ".oecd.org",   # intergovernmental
    )

    @classmethod
    def _source_type(cls, url: str) -> str:
        host = urlparse(url).netloc.lower()
        if any(host == s.lstrip(".") or host.endswith(s) for s in cls._GOVERNMENT_SUFFIXES):
            return "government"
        if any(host == d or host.endswith("." + d) for d in cls._DISTRIBUTORS):
            return "web"
        # First-party pages: the organisation's own site, its IR or newsroom.
        path = urlparse(url).path.lower()
        if any(seg in path for seg in ("/ir/", "/corporate/", "/company/", "/about/")):
            return "official"
        return "web"


parallel = ParallelClient()
