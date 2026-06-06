from __future__ import annotations

from datetime import datetime, timezone

from astock_backtester.data.news_summary import MarketNewsSummaryProvider
from astock_backtester.models import MarketNewsItem, MarketNewsResponse


class FakeNewsProvider:
    def __init__(self, items: list[MarketNewsItem]) -> None:
        self.items = items

    def latest_news(self, limit: int = 24) -> MarketNewsResponse:
        return MarketNewsResponse(
            updated_at=datetime(2026, 6, 5, 14, 30, tzinfo=timezone.utc),
            source="fake-news",
            items=self.items[:limit],
        )


def test_news_summary_groups_today_news_without_mutating_original_news_list():
    items = [
        MarketNewsItem(
            title="AI应用产业链午后走强",
            summary="算力、半导体、软件服务同步活跃。",
            source="示例财经",
            published_at=datetime(2026, 6, 5, 14, 20, tzinfo=timezone.utc),
            tags=["AI", "算力"],
            sentiment="positive",
        ),
        MarketNewsItem(
            title="算力租赁概念持续拉升",
            summary="多只高辨识度个股封板。",
            source="示例快讯",
            published_at=datetime(2026, 6, 5, 14, 10, tzinfo=timezone.utc),
            tags=["算力"],
            sentiment="positive",
        ),
        MarketNewsItem(
            title="退市风险提示增多",
            summary="部分ST公司披露风险公告。",
            source="示例公告",
            published_at=datetime(2026, 6, 5, 13, 50, tzinfo=timezone.utc),
            tags=["ST", "退市"],
            sentiment="negative",
        ),
    ]

    provider = FakeNewsProvider(items)
    response = MarketNewsSummaryProvider(provider).latest_summary()

    assert response.item_count == 3
    assert response.source == "fake-news-summary"
    assert response.themes[0].title in {"算力", "AI"}
    assert response.themes[0].source_count >= 1
    assert "退市风险提示增多" in response.risks[0]
    assert provider.items is items


def test_news_summary_prioritizes_same_day_news_over_older_items():
    items = [
        MarketNewsItem(
            title="昨日AI应用继续发酵",
            summary="昨日算力、半导体反复活跃。",
            source="昨日财经",
            published_at=datetime(2026, 6, 4, 15, 0, tzinfo=timezone.utc),
            tags=["AI", "算力"],
            sentiment="positive",
        ),
        MarketNewsItem(
            title="昨日算力租赁概念走强",
            summary="昨日多只高辨识度个股封板。",
            source="昨日快讯",
            published_at=datetime(2026, 6, 4, 14, 30, tzinfo=timezone.utc),
            tags=["AI", "算力"],
            sentiment="positive",
        ),
        MarketNewsItem(
            title="今日电力改革消息升温",
            summary="电力、政策方向成为今日新闻主线。",
            source="今日财经",
            published_at=datetime(2026, 6, 5, 9, 45, tzinfo=timezone.utc),
            tags=["电力", "政策"],
            sentiment="positive",
        ),
    ]

    response = MarketNewsSummaryProvider(FakeNewsProvider(items)).latest_summary()

    assert response.item_count == 1
    assert response.highlights == ["今日电力改革消息升温"]
    assert response.themes[0].title in {"政策", "电力"}
    assert all("昨日" not in headline for theme in response.themes for headline in theme.headlines)


def test_news_summary_returns_clear_fallback_when_news_provider_is_empty():
    response = MarketNewsSummaryProvider(FakeNewsProvider([])).latest_summary()

    assert response.item_count == 0
    assert response.themes == []
    assert response.risks
    assert response.diagnostics == ["新闻源暂无可汇总内容"]
