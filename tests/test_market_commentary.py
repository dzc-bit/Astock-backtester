from __future__ import annotations

import time
from datetime import datetime, timezone

from astock_backtester.data.market_commentary import MarketCommentaryProvider
from astock_backtester.models import (
    MarketBreadth,
    MarketIndexQuote,
    MarketNewsItem,
    MarketNewsResponse,
    RealtimeMarketSnapshot,
    SectorMover,
)


class FakeRealtimeProvider:
    def market_snapshot(self) -> RealtimeMarketSnapshot:
        return RealtimeMarketSnapshot(
            status="live",
            source="fake-live",
            updated_at=datetime(2026, 6, 5, 14, 50, tzinfo=timezone.utc),
            indexes=[
                MarketIndexQuote(
                    symbol="sh000001",
                    name="上证指数",
                    last=3100.0,
                    previous_close=3080.0,
                    change=20.0,
                    change_pct=0.0065,
                    source="fake-live",
                    updated_at=datetime(2026, 6, 5, 14, 50, tzinfo=timezone.utc),
                )
            ],
            breadth=MarketBreadth(up=3600, down=1300, flat=180, total=5080, source="fake-live"),
            strong_sectors=[
                SectorMover(name="AI应用", change_pct=0.042, leading_symbol="300001", source="ths-concept"),
                SectorMover(name="算力租赁", change_pct=0.031, leading_symbol="300002", source="ths-concept"),
            ],
            yesterday_strong_sectors=[
                SectorMover(name="AI应用", change_pct=0.038, leading_symbol="300001", source="local-yesterday"),
                SectorMover(name="机器人", change_pct=0.026, leading_symbol="300024", source="local-yesterday"),
            ],
            message="ok",
        )


class FakeNewsProvider:
    def latest_news(self, limit: int = 12) -> MarketNewsResponse:
        return MarketNewsResponse(
            updated_at=datetime(2026, 6, 5, 14, 55, tzinfo=timezone.utc),
            source="fake-news",
            items=[
                MarketNewsItem(
                    title="政策利好推动AI应用和算力方向走强",
                    summary="盘中AI应用、算力租赁、半导体方向成交活跃。",
                    source="示例财经",
                    published_at=datetime(2026, 6, 5, 14, 30, tzinfo=timezone.utc),
                    tags=["AI", "算力", "政策"],
                    sentiment="positive",
                )
            ],
        )


def test_market_commentary_builds_specific_same_day_view_from_live_snapshot_and_news():
    response = MarketCommentaryProvider(FakeRealtimeProvider(), FakeNewsProvider()).current_commentary()

    assert response.stance == "positive"
    assert response.trade_date.isoformat() == "2026-06-05"
    assert "上证指数+0.65%" in response.summary
    assert "AI应用" in response.summary
    assert "3600" in response.summary
    assert response.drivers[0].title == "强势题材"
    assert "算力租赁" in response.drivers[0].detail
    assert any(point.title == "市场宽度" and "上涨占比 70.9%" in point.detail for point in response.drivers)
    assert any(point.title == "新闻催化" and "候选" in point.detail for point in response.drivers)
    assert any("AI应用" in item for item in response.next_watch)
    assert response.diagnostics == ["实时盘面数据完整：已使用指数、红绿家数、强势题材和昨日强势追踪生成评价。"]


def test_market_commentary_explains_unavailable_realtime_source_without_crashing():
    class BrokenRealtimeProvider:
        def market_snapshot(self) -> RealtimeMarketSnapshot:
            raise RuntimeError("network closed")

    response = MarketCommentaryProvider(BrokenRealtimeProvider(), FakeNewsProvider()).current_commentary()

    assert response.stance == "defensive"
    assert response.drivers
    assert response.drivers[0].title == "新闻线索"
    assert "实时盘面暂不可用，以下仅为新闻线索候选" in response.summary
    assert response.risks
    assert any("实时数据缺失" in item for item in response.risks)
    assert any("实时盘面暂不可用" in item for item in response.next_watch)
    assert response.diagnostics == ["行情评价读取实时快照失败：network closed"]


def test_market_commentary_uses_news_tags_when_realtime_snapshot_fails():
    class BrokenRealtimeProvider:
        def market_snapshot(self) -> RealtimeMarketSnapshot:
            raise TimeoutError("snapshot timeout")

    response = MarketCommentaryProvider(BrokenRealtimeProvider(), FakeNewsProvider()).current_commentary()

    assert response.source == "news-fallback+commentary"
    assert response.stance == "defensive"
    assert "AI" in response.summary
    assert "算力" in response.summary
    assert len(response.drivers) == 1
    assert response.drivers[0].title == "新闻线索"
    assert "AI" in response.drivers[0].detail
    assert "候选" in response.drivers[0].detail
    assert any("盘面确认" in item for item in response.risks)
    assert any("AI" in item for item in response.next_watch)
    assert response.diagnostics == ["行情评价读取实时快照失败：snapshot timeout"]


def test_market_commentary_uses_news_tags_when_realtime_snapshot_is_slow():
    class SlowRealtimeProvider:
        def market_snapshot(self) -> RealtimeMarketSnapshot:
            time.sleep(0.05)
            return FakeRealtimeProvider().market_snapshot()

    response = MarketCommentaryProvider(
        SlowRealtimeProvider(),
        FakeNewsProvider(),
        snapshot_timeout=0.001,
    ).current_commentary()

    assert response.source == "news-fallback+commentary"
    assert "AI" in response.summary
    assert response.drivers[0].title == "新闻线索"
    assert response.diagnostics == ["行情评价读取实时快照超时：0.001秒"]


def test_market_commentary_reports_diagnostic_when_realtime_source_returns_unavailable():
    class UnavailableRealtimeProvider:
        def market_snapshot(self) -> RealtimeMarketSnapshot:
            return RealtimeMarketSnapshot(
                status="unavailable",
                source="fake-live",
                updated_at=datetime(2026, 6, 5, 14, 50, tzinfo=timezone.utc),
                indexes=[],
                breadth=None,
                strong_sectors=[],
                yesterday_strong_sectors=[],
                message="同花顺和东方财富均无可用实时数据",
            )

    response = MarketCommentaryProvider(UnavailableRealtimeProvider(), FakeNewsProvider()).current_commentary()

    assert response.source == "news-fallback+commentary"
    assert response.stance == "defensive"
    assert "实时盘面暂不可用，以下仅为新闻线索候选" in response.summary
    assert "AI" in response.summary
    assert response.drivers[0].title == "新闻线索"
    assert response.diagnostics == [
        "行情评价实时快照不可用：同花顺和东方财富均无可用实时数据",
        "实时盘面不完整：快照状态为 unavailable、缺少指数、缺少红绿家数、缺少强势题材，未生成确定盘面评价。",
    ]


def test_market_commentary_does_not_build_definite_view_from_unavailable_snapshot_with_local_data():
    class UnavailableWithLocalDataProvider:
        def market_snapshot(self) -> RealtimeMarketSnapshot:
            return RealtimeMarketSnapshot(
                status="unavailable",
                source="local-latest",
                updated_at=datetime(2026, 6, 5, 14, 50, tzinfo=timezone.utc),
                indexes=[
                    MarketIndexQuote(
                        symbol="local-market",
                        name="本地全市场",
                        last=10.3,
                        previous_close=10.0,
                        change=0.3,
                        change_pct=0.03,
                        source="local-latest",
                        updated_at=datetime(2026, 6, 5, 14, 50, tzinfo=timezone.utc),
                    )
                ],
                breadth=MarketBreadth(up=4, down=1, flat=0, total=5, source="local-latest"),
                strong_sectors=[
                    SectorMover(name="AI应用", change_pct=0.052, leading_symbol="300001", source="local-market-group"),
                    SectorMover(name="机器人", change_pct=0.031, leading_symbol="300024", source="local-market-group"),
                ],
                yesterday_strong_sectors=[
                    SectorMover(name="AI应用", change_pct=0.038, leading_symbol="300001", source="local-yesterday"),
                ],
                message="实时行情不可用，已使用本地最近交易日数据。",
            )

    response = MarketCommentaryProvider(UnavailableWithLocalDataProvider(), FakeNewsProvider()).current_commentary()

    assert response.source == "news-fallback+commentary"
    assert response.trade_date.isoformat() == "2026-06-05"
    assert response.stance == "defensive"
    assert "实时盘面暂不可用，以下仅为新闻线索候选" in response.summary
    assert "AI应用" not in response.summary
    assert "红盘 4" not in response.summary
    assert response.drivers[0].title == "新闻线索"
    assert "候选" in response.drivers[0].detail
    assert not any(point.title == "强势题材" for point in response.drivers)
    assert any("实时数据缺失" in item for item in response.risks)
    assert any("恢复实时快照后复核" in item for item in response.next_watch)
    assert response.diagnostics == [
        "行情评价实时快照不可用：实时行情不可用，已使用本地最近交易日数据。",
        "实时盘面不完整：快照状态为 unavailable，未生成确定盘面评价。",
    ]


def test_market_commentary_does_not_build_definite_view_from_empty_live_snapshot():
    class EmptyLiveRealtimeProvider:
        def market_snapshot(self) -> RealtimeMarketSnapshot:
            return RealtimeMarketSnapshot(
                status="live",
                source="fake-live-empty",
                updated_at=datetime(2026, 6, 5, 14, 50, tzinfo=timezone.utc),
                indexes=[],
                breadth=None,
                strong_sectors=[],
                yesterday_strong_sectors=[],
                message="实时源返回空快照",
            )

    response = MarketCommentaryProvider(EmptyLiveRealtimeProvider(), FakeNewsProvider()).current_commentary()

    assert response.source == "news-fallback+commentary"
    assert response.stance == "defensive"
    assert "实时盘面暂不可用，以下仅为新闻线索候选" in response.summary
    assert "今日强势题材" not in response.summary
    assert response.drivers[0].title == "新闻线索"
    assert any("实时数据缺失" in item for item in response.risks)
    assert response.diagnostics == ["实时盘面不完整：缺少指数、缺少红绿家数、缺少强势题材，未生成确定盘面评价。"]
