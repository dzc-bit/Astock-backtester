from __future__ import annotations

from datetime import UTC, datetime
from threading import Event, Lock, Thread

import astock_backtester.data.news as news_module
import requests
from astock_backtester.data.news import MarketNewsProvider
from astock_backtester.models import MarketNewsItem


class NewsResponse:
    def __init__(self, *, payload: dict | None = None, text: str = "", status_code: int = 200):
        self._payload = payload or {}
        self.text = text
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(f"HTTP {self.status_code}", response=response)


def test_news_provider_uses_alternate_transport_and_reports_source_diagnostics():
    def primary(_url: str, **_kwargs):
        return NewsResponse(status_code=403)

    def alternate(url: str, **_kwargs):
        if "getNewsByColumns" in url:
            return NewsResponse(
                payload={
                    "data": {
                        "list": [
                            {
                                "title": "算力基础设施投资持续增长",
                                "summary": "多地发布新一轮算力建设规划。",
                                "mediaName": "公开财经",
                                "showTime": "2026-07-10 10:00:00",
                                "url": "https://example.test/news/1",
                            }
                        ]
                    }
                }
            )
        return NewsResponse()

    provider = MarketNewsProvider(
        requester=primary,
        alternate_requester=alternate,
        allow_alternate_transport=True,
    )

    response = provider.latest_news(limit=5)

    assert response.source == "eastmoney-columns"
    assert [item.title for item in response.items] == ["算力基础设施投资持续增长"]
    assert any(
        "eastmoney-news-columns alternate transport used" in item
        for item in response.diagnostics
    )


def test_news_provider_does_not_start_sources_after_total_budget_expires():
    calls = 0

    def requester(_url: str, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("expired news request must not start a source")

    response = MarketNewsProvider(requester=requester, time_budget=0).latest_news()

    assert response.source == "fallback"
    assert calls == 0
    assert response.diagnostics == [
        "market-news source chain stopped because the request budget was exhausted."
    ]


def _news_item(title: str = "算力基础设施投资持续增长") -> MarketNewsItem:
    return MarketNewsItem(
        title=title,
        summary="多地发布新一轮算力建设规划。",
        source="公开财经",
        published_at=datetime(2026, 7, 10, 10, 0, tzinfo=UTC),
        tags=["算力"],
        sentiment="positive",
    )


def test_news_provider_fast_source_is_not_starved_by_blocked_source():
    slow_started = Event()
    release_slow = Event()
    finished = Event()
    result: list = []
    provider = MarketNewsProvider(time_budget=0.05)

    def slow_columns(_limit, _diagnostics, _deadline):
        slow_started.set()
        release_slow.wait(timeout=1)
        return []

    provider._fetch_eastmoney_columns = slow_columns
    provider._fetch_eastmoney_rolling = lambda _limit, _diagnostics, _deadline: []
    provider._fetch_eastmoney_fast_news = lambda _limit, _diagnostics, _deadline: [
        _news_item("东方财富快讯正常返回")
    ]

    def fetch() -> None:
        result.append(provider.latest_news())
        finished.set()

    worker = Thread(target=fetch)
    worker.start()
    assert slow_started.wait(timeout=1)
    try:
        completed_within_budget = finished.wait(timeout=0.2)
    finally:
        release_slow.set()
        worker.join(timeout=1)

    assert completed_within_budget
    assert result[0].source == "eastmoney-fast-news"
    assert [item.title for item in result[0].items] == ["东方财富快讯正常返回"]


def test_news_provider_overlapping_calls_share_one_upstream_refresh():
    slow_started = Event()
    release_slow = Event()
    attempts_lock = Lock()
    column_attempts = 0
    responses: list = []
    provider = MarketNewsProvider(time_budget=1.0, cache_ttl=30.0)

    def slow_columns(_limit, _diagnostics, _deadline):
        nonlocal column_attempts
        with attempts_lock:
            column_attempts += 1
        slow_started.set()
        release_slow.wait(timeout=1)
        return [_news_item()]

    provider._fetch_eastmoney_columns = slow_columns
    provider._fetch_eastmoney_rolling = lambda _limit, _diagnostics, _deadline: []
    provider._fetch_eastmoney_fast_news = lambda _limit, _diagnostics, _deadline: []

    first = Thread(target=lambda: responses.append(provider.latest_news(limit=18)))
    second = Thread(target=lambda: responses.append(provider.latest_news(limit=24)))
    first.start()
    assert slow_started.wait(timeout=1)
    second.start()
    release_slow.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert not first.is_alive()
    assert not second.is_alive()
    assert column_attempts == 1
    assert len(responses) == 2
    assert all(response.items[0].title == "算力基础设施投资持续增长" for response in responses)


def test_news_provider_uses_explicit_recent_success_when_refresh_fails():
    failing = False
    provider = MarketNewsProvider(cache_ttl=0, recent_success_ttl=60)

    def columns(_limit, _diagnostics, _deadline):
        if failing:
            raise OSError("columns disconnected")
        return [_news_item()]

    provider._fetch_eastmoney_columns = columns
    provider._fetch_eastmoney_rolling = lambda _limit, _diagnostics, _deadline: []
    provider._fetch_eastmoney_fast_news = lambda _limit, _diagnostics, _deadline: []

    successful = provider.latest_news()
    failing = True
    fallback = provider.latest_news()

    assert fallback.updated_at == successful.updated_at
    assert fallback.source == "eastmoney-columns+recent-success-cache"
    assert [item.title for item in fallback.items] == ["算力基础设施投资持续增长"]
    assert any("columns disconnected" in item for item in fallback.diagnostics)
    assert any("recent_success_cache_used" in item for item in fallback.diagnostics)


def test_news_provider_parses_rolling_link_independent_of_attribute_order():
    response = NewsResponse(
        text=(
            '<div><a title="算力基础设施迎来新一轮投资建设机会" '
            'class="news-link" href="https://finance.eastmoney.com/a/202607103456.html">详情</a></div>'
        )
    )
    provider = MarketNewsProvider(requester=lambda _url, **_kwargs: response)

    items = provider._fetch_eastmoney_rolling(5, [], None)

    assert [item.title for item in items] == ["算力基础设施迎来新一轮投资建设机会"]
    assert items[0].url == "https://finance.eastmoney.com/a/202607103456.html"


def test_news_provider_parses_eastmoney_7x24_fast_news():
    response = NewsResponse(
        payload={
            "data": {
                "fastNewsList": [
                    {
                        "code": "202607103801597817",
                        "title": "AI投资需求推动全球市场关注",
                        "summary": "多家机构持续关注算力基础设施投资。",
                        "showTime": "2026-07-10 14:27:23",
                    }
                ]
            }
        }
    )
    provider = MarketNewsProvider(requester=lambda _url, **_kwargs: response)

    items = provider._fetch_eastmoney_fast_news(5, [], None)

    assert [item.title for item in items] == ["AI投资需求推动全球市场关注"]
    assert items[0].source == "东方财富7×24"
    assert items[0].summary == "多家机构持续关注算力基础设施投资。"
    assert items[0].published_at.isoformat() == "2026-07-10T14:27:23+08:00"


def test_recent_success_cache_does_not_outlive_stale_ttl(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(news_module, "monotonic", lambda: clock[0])
    failing = False
    provider = MarketNewsProvider(
        time_budget=None,
        cache_ttl=6,
        recent_success_ttl=10,
    )

    def columns(_limit, _diagnostics, _deadline):
        if failing:
            raise OSError("all current sources unavailable")
        return [_news_item()]

    provider._fetch_eastmoney_columns = columns
    provider._fetch_eastmoney_rolling = lambda _limit, _diagnostics, _deadline: []
    provider._fetch_eastmoney_fast_news = lambda _limit, _diagnostics, _deadline: []

    assert provider.latest_news().source == "eastmoney-columns"
    failing = True
    clock[0] = 109.0
    assert provider.latest_news().source == "eastmoney-columns+recent-success-cache"

    clock[0] = 111.0
    expired = provider.latest_news()

    assert expired.source == "fallback"
    assert [item.title for item in expired.items] == ["资讯接口暂不可用"]
