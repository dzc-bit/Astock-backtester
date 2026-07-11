from __future__ import annotations

import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html import unescape
from threading import Lock
from time import monotonic

import requests
from bs4 import BeautifulSoup

from astock_backtester.data.http_transport import resilient_get, should_allow_alternate_transport
from astock_backtester.models import MarketNewsItem, MarketNewsResponse

POSITIVE_WORDS = ("利好", "拉升", "走强", "活跃", "增长", "抢筹", "突破")
NEGATIVE_WORDS = ("利空", "下跌", "退市", "风险", "调查", "亏损", "警示")
TAG_WORDS = ("AI", "半导体", "电力设备", "政策", "融资", "退市", "ST", "券商", "地产", "新能源", "算力")
BEIJING_TZ = timezone(timedelta(hours=8))


def _sentiment(title: str, summary: str | None) -> str:
    text = f"{title} {summary or ''}"
    if any(word in text for word in NEGATIVE_WORDS):
        return "negative"
    if any(word in text for word in POSITIVE_WORDS):
        return "positive"
    return "neutral"


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=BEIJING_TZ)
    except ValueError:
        return None


def _clean_html_text(value: str | None) -> str:
    text = re.sub(r"<[^>]+>", "", value or "")
    return unescape(text).strip()


def _tags(title: str, summary: str | None) -> list[str]:
    text = f"{title} {summary or ''}"
    return [word for word in TAG_WORDS if word in text]


@dataclass
class MarketNewsProvider:
    timeout: float = 5.0
    time_budget: float | None = 12.0
    cache_ttl: float = 5.0
    recent_success_ttl: float = 15 * 60.0
    requester: Callable[..., requests.Response] = requests.get
    alternate_requester: Callable[..., requests.Response] | None = None
    allow_alternate_transport: bool | None = None
    _refresh_lock: Lock = field(default_factory=Lock, init=False, repr=False)
    _cached_response: MarketNewsResponse | None = field(default=None, init=False, repr=False)
    _cached_until: float = field(default=0.0, init=False, repr=False)
    _last_successful_response: MarketNewsResponse | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _last_successful_at: float = field(default=0.0, init=False, repr=False)

    def _allow_public_alternate_transport(self) -> bool:
        return should_allow_alternate_transport(self.requester, self.allow_alternate_transport)

    def _request(
        self,
        url: str,
        *,
        source: str,
        diagnostics: list[str],
        deadline: float | None,
        **kwargs,
    ) -> requests.Response:
        return resilient_get(
            self.requester,
            url,
            timeout=self.timeout,
            source=source,
            diagnostics=diagnostics,
            retries=1,
            deadline=deadline,
            alternate_requester=self.alternate_requester,
            allow_alternate=self._allow_public_alternate_transport(),
            **kwargs,
        )

    def _budget_available(self, deadline: float | None, diagnostics: list[str]) -> bool:
        if deadline is None or monotonic() < deadline:
            return True
        message = "market-news source chain stopped because the request budget was exhausted."
        if message not in diagnostics:
            diagnostics.append(message)
        return False

    def latest_news(self, limit: int = 18) -> MarketNewsResponse:
        with self._refresh_lock:
            cached = self._fresh_cached_response(limit)
            if cached is not None:
                return cached

            response = self._fetch_latest_news(max(limit, 24))
            fetched_at = monotonic()
            cache_until = fetched_at + max(0.0, self.cache_ttl)
            if response.source != "fallback" and response.items:
                self._last_successful_response = response.model_copy(deep=True)
                self._last_successful_at = fetched_at
            elif (
                self._last_successful_response is not None
                and self.recent_success_ttl > 0
                and fetched_at - self._last_successful_at <= max(0.0, self.recent_success_ttl)
            ):
                retained = self._last_successful_response.model_copy(deep=True)
                retained.source = f"{retained.source}+recent-success-cache"
                retained.diagnostics = [
                    *response.diagnostics,
                    "market-news recent_success_cache_used after current sources failed.",
                ]
                response = retained
                cache_until = min(
                    cache_until,
                    self._last_successful_at + self.recent_success_ttl,
                )

            self._cached_response = response.model_copy(deep=True)
            self._cached_until = cache_until
            return self._response_for_limit(response, limit)

    def _fresh_cached_response(self, limit: int) -> MarketNewsResponse | None:
        if self._cached_response is None or self.cache_ttl <= 0:
            return None
        if monotonic() >= self._cached_until:
            return None
        return self._response_for_limit(self._cached_response, limit)

    def _response_for_limit(self, response: MarketNewsResponse, limit: int) -> MarketNewsResponse:
        copied = response.model_copy(deep=True)
        copied.items = copied.items[: max(0, limit)]
        return copied

    def _fetch_latest_news(self, limit: int) -> MarketNewsResponse:
        now = datetime.now(timezone.utc)
        items: list[MarketNewsItem] = []
        sources: list[str] = []
        diagnostics: list[str] = []
        deadline = None if self.time_budget is None else monotonic() + max(0, self.time_budget)
        if not self._budget_available(deadline, diagnostics):
            return self._fallback_response(now, diagnostics)

        source_specs = [
            ("eastmoney-columns", "eastmoney-news-columns", self._fetch_eastmoney_columns),
            ("eastmoney-rolling", "eastmoney-news-rolling", self._fetch_eastmoney_rolling),
            ("eastmoney-fast-news", "eastmoney-fast-news", self._fetch_eastmoney_fast_news),
        ]
        executor = ThreadPoolExecutor(max_workers=len(source_specs))
        futures = {
            source: executor.submit(self._run_source, fetcher, failure_label, limit, deadline)
            for source, failure_label, fetcher in source_specs
        }
        try:
            if deadline is None:
                done, pending = wait(futures.values())
            else:
                done, pending = wait(futures.values(), timeout=max(0.0, deadline - monotonic()))
        finally:
            for future in futures.values():
                if not future.done():
                    future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)

        for source, failure_label, _fetcher in source_specs:
            future = futures[source]
            if future not in done:
                diagnostics.append(f"{failure_label} exceeded the market-news request budget.")
                continue
            source_items, source_diagnostics = future.result()
            diagnostics.extend(source_diagnostics)
            items.extend(source_items)
            if source_items:
                sources.append(source)
        items = self._dedupe_and_sort(items, limit)
        if items:
            return MarketNewsResponse(
                updated_at=now,
                source="+".join(sources),
                items=items,
                diagnostics=diagnostics,
            )
        return self._fallback_response(now, diagnostics)

    def _run_source(
        self,
        fetcher: Callable[[int, list[str], float | None], list[MarketNewsItem]],
        failure_label: str,
        limit: int,
        deadline: float | None,
    ) -> tuple[list[MarketNewsItem], list[str]]:
        diagnostics: list[str] = []
        try:
            return fetcher(limit, diagnostics, deadline), diagnostics
        except Exception as exc:
            diagnostics.append(f"{failure_label} failed: {exc}")
            return [], diagnostics

    def _fallback_response(self, now: datetime, diagnostics: list[str]) -> MarketNewsResponse:
        return MarketNewsResponse(
            updated_at=now,
            source="fallback",
            diagnostics=diagnostics,
            items=[
                MarketNewsItem(
                    title="资讯接口暂不可用",
                    summary="已保留资讯区，网络恢复后会自动展示东方财富、财联社等市场新闻。",
                    source="本地服务",
                    published_at=now,
                    tags=["系统"],
                    sentiment="neutral",
                )
            ],
        )

    def _fetch_eastmoney_columns(
        self, limit: int, diagnostics: list[str], deadline: float | None
    ) -> list[MarketNewsItem]:
        response = self._request(
            "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns",
            source="eastmoney-news-columns",
            diagnostics=diagnostics,
            deadline=deadline,
            params={
                "client": "web",
                "biz": "web_news_col",
                "column": "345",
                "order": "1",
                "needInteractData": "0",
                "page_index": "1",
                "page_size": str(limit),
                "types": "1",
                "req_trace": "astock-backtester",
            },
            headers={"Referer": "https://finance.eastmoney.com/"},
        )
        payload = response.json()
        rows = ((payload or {}).get("data") or {}).get("list") or []
        items: list[MarketNewsItem] = []
        for row in rows[:limit]:
            title = str(row.get("title") or "").strip()
            if not title:
                continue
            summary = str(row.get("summary") or "").strip() or None
            items.append(
                MarketNewsItem(
                    title=title,
                    summary=summary,
                    source=str(row.get("mediaName") or "东方财富"),
                    published_at=_parse_time(row.get("showTime")),
                    url=str(row.get("url") or row.get("uniqueUrl") or "").strip() or None,
                    tags=_tags(title, summary),
                    sentiment=_sentiment(title, summary),  # type: ignore[arg-type]
                )
            )
        return items

    def _fetch_eastmoney_rolling(
        self, limit: int, diagnostics: list[str], deadline: float | None
    ) -> list[MarketNewsItem]:
        response = self._request(
            "https://finance.eastmoney.com/yaowen.html",
            source="eastmoney-news-rolling",
            diagnostics=diagnostics,
            deadline=deadline,
            headers={"Referer": "https://finance.eastmoney.com/"},
        )
        soup = BeautifulSoup(response.text, "html.parser")
        items: list[MarketNewsItem] = []
        for link in soup.select("a[href][title]"):
            cleaned_title = _clean_html_text(str(link.get("title") or ""))
            href = str(link.get("href") or "").strip()
            if not cleaned_title or len(cleaned_title) < 8:
                continue
            items.append(
                MarketNewsItem(
                    title=cleaned_title,
                    source="东方财富",
                    published_at=None,
                    url=href if href.startswith("http") else None,
                    tags=_tags(cleaned_title, None),
                    sentiment=_sentiment(cleaned_title, None),  # type: ignore[arg-type]
                )
            )
            if len(items) >= limit:
                break
        return items

    def _fetch_eastmoney_fast_news(
        self, limit: int, diagnostics: list[str], deadline: float | None
    ) -> list[MarketNewsItem]:
        response = self._request(
            "https://np-weblist.eastmoney.com/comm/web/getFastNewsList",
            source="eastmoney-fast-news",
            diagnostics=diagnostics,
            deadline=deadline,
            params={
                "client": "web",
                "biz": "web_724",
                "fastColumn": "102",
                "sortEnd": "",
                "pageSize": str(limit),
                "req_trace": "astock-backtester",
            },
            headers={"Referer": "https://kuaixun.eastmoney.com/"},
        )
        payload = response.json() or {}
        rows = (payload.get("data") or {}).get("fastNewsList") or []
        items: list[MarketNewsItem] = []
        for row in rows[:limit]:
            title = _clean_html_text(str(row.get("title") or ""))
            if not title:
                continue
            summary = _clean_html_text(str(row.get("summary") or "")) or None
            items.append(
                MarketNewsItem(
                    title=title[:120],
                    summary=summary if summary != title else None,
                    source="东方财富7×24",
                    published_at=_parse_time(row.get("showTime")),
                    url=None,
                    tags=_tags(title, summary),
                    sentiment=_sentiment(title, summary),  # type: ignore[arg-type]
                )
            )
        return items

    def _dedupe_and_sort(self, items: list[MarketNewsItem], limit: int) -> list[MarketNewsItem]:
        seen: set[str] = set()
        deduped: list[MarketNewsItem] = []
        for item in items:
            key = item.url or item.title
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        deduped.sort(key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return deduped[:limit]
