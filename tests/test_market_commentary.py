from __future__ import annotations

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
    assert "AI应用" in response.summary
    assert "3600" in response.summary
    assert response.drivers[0].title == "强势题材"
    assert "算力租赁" in response.drivers[0].detail
    assert any("AI应用" in item for item in response.next_watch)
    assert response.diagnostics == []


def test_market_commentary_explains_unavailable_realtime_source_without_crashing():
    class BrokenRealtimeProvider:
        def market_snapshot(self) -> RealtimeMarketSnapshot:
            raise RuntimeError("network closed")

    response = MarketCommentaryProvider(BrokenRealtimeProvider(), FakeNewsProvider()).current_commentary()

    assert response.stance == "defensive"
    assert response.drivers == []
    assert response.risks
    assert response.diagnostics == ["行情评价读取实时快照失败：network closed"]


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

    assert response.source == "fallback"
    assert response.stance == "defensive"
    assert response.diagnostics == ["行情评价实时快照不可用：同花顺和东方财富均无可用实时数据"]
