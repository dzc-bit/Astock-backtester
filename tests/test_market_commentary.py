from __future__ import annotations

import time
from datetime import datetime, timezone

from astock_backtester.data.market_commentary import MarketCommentaryProvider
from astock_backtester.models import (
    MarketBriefingResponse,
    MarketBriefingSection,
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


class FakeFupanProvider:
    def latest_fupan(self) -> MarketBriefingResponse:
        return MarketBriefingResponse(
            kind="fupan",
            updated_at=datetime(2026, 6, 5, 15, 35, tzinfo=timezone.utc),
            source="ths-fupan",
            source_url="https://stock.10jqka.com.cn/fupan/",
            summary="收盘后复盘：机器人、算力和AI应用方向活跃，指数震荡但题材承接尚可。",
            sections=[
                MarketBriefingSection(
                    title="同花顺解盘",
                    content="机器人板块午后继续走强，多只个股涨停。算力方向保持资金关注，明日观察成交额能否继续放大。",
                    links=[],
                    tables=[],
                )
            ],
            diagnostics=[],
        )


def test_market_commentary_builds_specific_same_day_view_from_live_snapshot_and_news():
    response = MarketCommentaryProvider(FakeRealtimeProvider(), FakeNewsProvider()).current_commentary()

    assert response.mode == "intraday"
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


def test_market_commentary_accepts_retained_post_close_snapshot_as_review():
    class RetainedPostCloseProvider:
        def market_snapshot(self) -> RealtimeMarketSnapshot:
            snapshot = FakeRealtimeProvider().market_snapshot()
            snapshot.status = "stale"
            snapshot.market_phase = "post_close"
            snapshot.source = "ashare-sina+retained-last-success"
            snapshot.message = "收盘后使用最近成功行情快照。"
            snapshot.diagnostics = ["收盘后降低刷新频率，沿用 2026-06-05 14:50 的成功快照。"]
            return snapshot

    response = MarketCommentaryProvider(RetainedPostCloseProvider(), FakeNewsProvider()).current_commentary()

    assert response.mode == "post_close"
    assert response.source == "ashare-sina+retained-last-success+commentary"
    assert "收盘后复盘" in response.summary
    assert "AI应用" in response.summary
    assert any("收盘后降低刷新频率" in item for item in response.diagnostics)
    assert not response.summary.startswith("实时盘面暂不可用")


def test_market_commentary_labels_lunch_break_snapshot_as_review():
    class LunchBreakProvider:
        def market_snapshot(self) -> RealtimeMarketSnapshot:
            snapshot = FakeRealtimeProvider().market_snapshot()
            snapshot.status = "stale"
            snapshot.market_phase = "lunch_break"
            snapshot.source = "ashare-sina+retained-last-success"
            snapshot.message = "午间休市使用最近成功行情快照。"
            snapshot.diagnostics = ["午间休市，使用最近成功行情快照生成回顾。"]
            return snapshot

    response = MarketCommentaryProvider(LunchBreakProvider(), FakeNewsProvider()).current_commentary()

    assert response.mode == "lunch_break_review"
    assert "午间盘面回顾" in response.summary
    assert any("午间休市" in item for item in response.diagnostics)


def test_market_commentary_accepts_weekend_snapshot_as_recent_trading_day_review():
    class WeekendRetainedProvider:
        def market_snapshot(self) -> RealtimeMarketSnapshot:
            snapshot = FakeRealtimeProvider().market_snapshot()
            snapshot.status = "stale"
            snapshot.market_phase = "non_trading"
            snapshot.source = "local-latest+retained-last-success"
            snapshot.message = "非交易日使用最近交易日快照。"
            snapshot.diagnostics = ["周末非交易日，使用最近交易日快照生成回顾。"]
            return snapshot

    response = MarketCommentaryProvider(WeekendRetainedProvider(), FakeNewsProvider()).current_commentary()

    assert response.mode == "non_trading_review"
    assert "非交易日最近交易日回顾" in response.summary
    assert response.trade_date.isoformat() == "2026-06-05"
    assert any("周末非交易日" in item for item in response.diagnostics)
    assert response.drivers[0].title == "强势题材"


def test_market_commentary_explains_unavailable_realtime_source_without_crashing():
    class BrokenRealtimeProvider:
        def market_snapshot(self) -> RealtimeMarketSnapshot:
            raise RuntimeError("network closed")

    response = MarketCommentaryProvider(BrokenRealtimeProvider(), FakeNewsProvider()).current_commentary()

    assert response.mode == "local_brief_review"
    assert response.stance == "defensive"
    assert response.drivers
    assert response.drivers[0].title == "后端防守判断"
    assert "后端简短判断" in response.summary
    assert response.risks
    assert any("不能把新闻或局部数据包装成确定结论" in item for item in response.risks)
    assert any("完整红绿家数" in item for item in response.next_watch)
    assert response.diagnostics == [
        "行情评价读取实时快照失败：network closed",
        "后端已生成简短防守判断，避免前端 fallback 或局部数据被包装成确定行情结论。",
    ]


def test_market_commentary_uses_news_tags_when_realtime_snapshot_fails():
    class BrokenRealtimeProvider:
        def market_snapshot(self) -> RealtimeMarketSnapshot:
            raise TimeoutError("snapshot timeout")

    response = MarketCommentaryProvider(BrokenRealtimeProvider(), FakeNewsProvider()).current_commentary()

    assert response.mode == "local_brief_review"
    assert response.source == "local-brief-commentary"
    assert response.stance == "defensive"
    assert "AI" in response.summary
    assert "算力" in response.summary
    assert len(response.drivers) == 1
    assert response.drivers[0].title == "后端防守判断"
    assert "AI" in response.drivers[0].detail
    assert any("不能把新闻或局部数据包装成确定结论" in item for item in response.risks)
    assert any("完整红绿家数" in item for item in response.next_watch)
    assert response.diagnostics == [
        "行情评价读取实时快照失败：snapshot timeout",
        "后端已生成简短防守判断，避免前端 fallback 或局部数据被包装成确定行情结论。",
    ]


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

    assert response.source == "local-brief-commentary"
    assert "AI" in response.summary
    assert response.drivers[0].title == "后端防守判断"
    assert response.diagnostics == [
        "行情评价读取实时快照超时：0.001秒",
        "后端已生成简短防守判断，避免前端 fallback 或局部数据被包装成确定行情结论。",
    ]


def test_market_commentary_default_snapshot_timeout_allows_longer_realtime_reads():
    provider = MarketCommentaryProvider(FakeRealtimeProvider(), FakeNewsProvider())

    assert provider.snapshot_timeout == 30.0


def test_market_commentary_uses_fupan_when_realtime_snapshot_is_slow():
    class SlowRealtimeProvider:
        def market_snapshot(self) -> RealtimeMarketSnapshot:
            time.sleep(0.05)
            return FakeRealtimeProvider().market_snapshot()

    response = MarketCommentaryProvider(
        SlowRealtimeProvider(),
        FakeNewsProvider(),
        briefing_provider=FakeFupanProvider(),
        snapshot_timeout=0.001,
    ).current_commentary()

    assert response.mode == "post_close"
    assert response.source == "ths-fupan+briefing-commentary"
    assert response.stance == "neutral"
    assert "收盘后复盘" in response.summary
    assert "机器人" in response.summary
    assert "算力" in response.drivers[0].detail
    assert response.drivers[0].title == "同花顺复盘"
    assert any("实时盘面读取失败，已用同花顺复盘" in item for item in response.diagnostics)
    assert not response.summary.startswith("实时盘面暂不可用")


def test_market_commentary_ignores_noisy_briefing_fallback_text():
    class BrokenRealtimeProvider:
        def market_snapshot(self) -> RealtimeMarketSnapshot:
            raise TimeoutError("snapshot timeout")

    class NoisyFupanProvider:
        def latest_fupan(self) -> MarketBriefingResponse:
            return MarketBriefingResponse(
                kind="fupan",
                updated_at=datetime(2026, 6, 5, 15, 35, tzinfo=timezone.utc),
                source="ths-fupan",
                source_url="https://stock.10jqka.com.cn/fupan/",
                summary="同比指数盈利",
                sections=[
                    MarketBriefingSection(
                        title="指数表现",
                        content="板块名称 最新涨幅 涨跌幅% 股票数（只） 1293.69 +14.46 +1.13% 363.54亿 2026-06-05 15:00:00",
                        links=[],
                        tables=[],
                    )
                ],
                diagnostics=[],
            )

    response = MarketCommentaryProvider(
        BrokenRealtimeProvider(),
        FakeNewsProvider(),
        briefing_provider=NoisyFupanProvider(),
        snapshot_timeout=None,
    ).current_commentary()

    dumped = str(response.model_dump(mode="json"))
    assert response.source == "local-brief-commentary"
    assert "同比指数盈利" not in dumped
    assert "1293.69" not in dumped
    assert "363.54亿" not in dumped


def test_market_commentary_labels_market_fallback_briefing_as_public_market_fallback():
    class BrokenRealtimeProvider:
        def market_snapshot(self) -> RealtimeMarketSnapshot:
            raise TimeoutError("snapshot timeout")

    class MarketFallbackFupanProvider:
        def latest_fupan(self) -> MarketBriefingResponse:
            return MarketBriefingResponse(
                kind="fupan",
                updated_at=datetime(2026, 6, 5, 15, 35, tzinfo=timezone.utc),
                source="ths-fupan+market-fallback",
                source_url="https://stock.10jqka.com.cn/fupan/",
                summary="公开行情回顾：指数震荡，半导体方向保持活跃。",
                sections=[MarketBriefingSection(title="公开行情回顾", content="半导体涨幅靠前，只作为复盘线索。")],
                diagnostics=["同花顺复盘读取失败：network closed"],
            )

    response = MarketCommentaryProvider(
        BrokenRealtimeProvider(),
        FakeNewsProvider(),
        briefing_provider=MarketFallbackFupanProvider(),
        snapshot_timeout=None,
    ).current_commentary()

    assert response.source == "ths-fupan+market-fallback+briefing-commentary"
    assert response.drivers[0].title == "公开行情复盘兜底"
    assert "公开行情复盘兜底" in response.summary
    assert any("公开行情复盘兜底" in item for item in response.risks)
    assert not any("同花顺复盘公开页面" in item for item in response.risks)


def test_market_commentary_labels_local_briefing_as_local_brief_review():
    class BrokenRealtimeProvider:
        def market_snapshot(self) -> RealtimeMarketSnapshot:
            raise TimeoutError("snapshot timeout")

    class LocalBriefFupanProvider:
        def latest_fupan(self) -> MarketBriefingResponse:
            return MarketBriefingResponse(
                kind="fupan",
                updated_at=datetime(2026, 6, 5, 15, 35, tzinfo=timezone.utc),
                source="ths-fupan+local-brief",
                source_url="https://stock.10jqka.com.cn/fupan/",
                summary="本地简短复盘：当前只给防守口径。",
                sections=[MarketBriefingSection(title="本地简短复盘", content="不包装成确定行情结论。")],
                diagnostics=["同花顺复盘和公开行情兜底均不可用"],
            )

    response = MarketCommentaryProvider(
        BrokenRealtimeProvider(),
        FakeNewsProvider(),
        briefing_provider=LocalBriefFupanProvider(),
        snapshot_timeout=None,
    ).current_commentary()

    assert response.source == "ths-fupan+local-brief+briefing-commentary"
    assert response.drivers[0].title == "本地简短复盘"
    assert "本地简短复盘" in response.summary
    assert any("本地简短复盘" in item for item in response.risks)
    assert not any("同花顺复盘公开页面" in item for item in response.risks)


def test_market_commentary_builds_backend_brief_review_when_realtime_and_fupan_are_unavailable():
    class EmptyLiveRealtimeProvider:
        def market_snapshot(self) -> RealtimeMarketSnapshot:
            return RealtimeMarketSnapshot(
                status="unavailable",
                source="fake-live-empty",
                updated_at=datetime(2026, 6, 5, 14, 50, tzinfo=timezone.utc),
                indexes=[],
                breadth=None,
                strong_sectors=[],
                yesterday_strong_sectors=[],
                message="实时源返回空快照",
            )

    class EmptyFupanProvider:
        def latest_fupan(self) -> MarketBriefingResponse:
            return MarketBriefingResponse(
                kind="fupan",
                updated_at=datetime(2026, 6, 5, 15, 35, tzinfo=timezone.utc),
                source="fallback",
                source_url=None,
                summary="",
                sections=[],
                diagnostics=["同花顺复盘页面没有可解析正文"],
            )

    response = MarketCommentaryProvider(
        EmptyLiveRealtimeProvider(),
        FakeNewsProvider(),
        briefing_provider=EmptyFupanProvider(),
    ).current_commentary()

    assert response.source == "local-brief-commentary"
    assert response.mode == "local_brief_review"
    assert response.stance == "defensive"
    assert "后端简短判断" in response.summary
    assert "实时盘面和同花顺复盘暂不可用" in response.summary
    assert response.drivers[0].title == "后端防守判断"
    assert any("不能把新闻或局部数据包装成确定结论" in item for item in response.risks)
    assert any("后端已生成简短防守判断" in item for item in response.diagnostics)


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

    assert response.source == "local-brief-commentary"
    assert response.stance == "defensive"
    assert "后端简短判断" in response.summary
    assert "AI" in response.summary
    assert response.drivers[0].title == "后端防守判断"
    assert response.diagnostics == [
        "行情评价实时快照不可用：同花顺和东方财富均无可用实时数据",
        "实时盘面不完整：快照状态为 unavailable、缺少指数、缺少红绿家数、缺少强势题材，未生成确定盘面评价。",
        "后端已生成简短防守判断，避免前端 fallback 或局部数据被包装成确定行情结论。",
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

    assert response.source == "local-brief-commentary"
    assert response.trade_date.isoformat() == "2026-06-05"
    assert response.stance == "defensive"
    assert "后端简短判断" in response.summary
    assert "AI应用" not in response.summary
    assert "红盘 4" not in response.summary
    assert response.drivers[0].title == "后端防守判断"
    assert not any(point.title == "强势题材" for point in response.drivers)
    assert any("不能把新闻或局部数据包装成确定结论" in item for item in response.risks)
    assert any("完整红绿家数" in item for item in response.next_watch)
    assert response.diagnostics[0] == "行情评价实时快照不可用：实时行情不可用，已使用本地最近交易日数据。"
    assert "快照状态为 unavailable" in response.diagnostics[1]
    assert "红绿家数不完整" in response.diagnostics[1]


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

    assert response.source == "local-brief-commentary"
    assert response.stance == "defensive"
    assert "后端简短判断" in response.summary
    assert "今日强势题材" not in response.summary
    assert response.drivers[0].title == "后端防守判断"
    assert any("不能把新闻或局部数据包装成确定结论" in item for item in response.risks)
    assert response.diagnostics == [
        "实时盘面不完整：缺少指数、缺少红绿家数、缺少强势题材，未生成确定盘面评价。",
        "后端已生成简短防守判断，避免前端 fallback 或局部数据被包装成确定行情结论。",
    ]


def test_market_commentary_rejects_live_snapshot_with_partial_breadth_total():
    class PartialBreadthRealtimeProvider:
        def market_snapshot(self) -> RealtimeMarketSnapshot:
            return RealtimeMarketSnapshot(
                status="live",
                source="ashare-sina+sina-a-share-live+ths-concept",
                updated_at=datetime(2026, 6, 5, 14, 50, tzinfo=timezone.utc),
                indexes=[
                    MarketIndexQuote(
                        symbol="sh000001",
                        name="上证指数",
                        last=3100.0,
                        previous_close=3080.0,
                        change=20.0,
                        change_pct=0.0065,
                        source="ashare-sina",
                    )
                ],
                breadth=MarketBreadth(up=107, down=80, flat=5, total=192, source="sina-a-share-live"),
                strong_sectors=[
                    SectorMover(name="AI应用", change_pct=0.042, leading_symbol="300001", source="ths-concept")
                ],
                yesterday_strong_sectors=[],
                message="局部实时宽度",
                diagnostics=["红绿家数来源 sina-a-share-live 不完整：total=192，低于全市场阈值。"],
            )

    response = MarketCommentaryProvider(PartialBreadthRealtimeProvider(), FakeNewsProvider()).current_commentary()

    assert response.source == "local-brief-commentary"
    assert response.mode == "local_brief_review"
    assert "后端简短判断" in response.summary
    assert not any("实时盘面数据完整" in item for item in response.diagnostics)
    assert any("红绿家数不完整" in item for item in response.diagnostics)


def test_market_commentary_rejects_live_snapshot_with_local_fallback_sectors():
    class LocalSectorRealtimeProvider:
        def market_snapshot(self) -> RealtimeMarketSnapshot:
            return RealtimeMarketSnapshot(
                status="live",
                source="ashare-sina+sina-a-share-live+local-market-group",
                updated_at=datetime(2026, 6, 5, 14, 50, tzinfo=timezone.utc),
                indexes=[
                    MarketIndexQuote(
                        symbol="sh000001",
                        name="上证指数",
                        last=3100.0,
                        previous_close=3080.0,
                        change=20.0,
                        change_pct=0.0065,
                        source="ashare-sina",
                    )
                ],
                breadth=MarketBreadth(up=3300, down=1500, flat=300, total=5100, source="sina-a-share-live"),
                strong_sectors=[
                    SectorMover(name="AI应用", change_pct=0.042, leading_symbol="300001", source="local-market-group")
                ],
                yesterday_strong_sectors=[],
                message="live breadth with local sectors",
                diagnostics=["实时强势题材接口暂不可用，已回退到本地最近交易日题材聚合。"],
            )

    response = MarketCommentaryProvider(LocalSectorRealtimeProvider(), FakeNewsProvider()).current_commentary()

    assert response.source == "local-brief-commentary"
    assert response.mode == "local_brief_review"
    assert not any("实时盘面数据完整" in item for item in response.diagnostics)
    assert any("local fallback" in item for item in response.diagnostics)
