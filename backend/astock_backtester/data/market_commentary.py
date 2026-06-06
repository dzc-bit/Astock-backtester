from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from astock_backtester.models import (
    MarketCommentaryPoint,
    MarketCommentaryResponse,
    MarketNewsResponse,
    RealtimeMarketSnapshot,
)


def _format_pct(value: float | None) -> str:
    if value is None:
        return "--"
    sign = "+" if value > 0 else ""
    return f"{sign}{value * 100:.2f}%"


def _today_from_snapshot(snapshot: RealtimeMarketSnapshot | None) -> datetime:
    return snapshot.updated_at if snapshot is not None else datetime.now(timezone.utc)


def _news_theme_text(news: MarketNewsResponse | None) -> str | None:
    if news is None or not news.items:
        return None
    tags: dict[str, int] = {}
    for item in news.items[:12]:
        for tag in item.tags:
            tags[tag] = tags.get(tag, 0) + 1
    if tags:
        top_tags = sorted(tags.items(), key=lambda pair: pair[1], reverse=True)[:3]
        return "、".join(tag for tag, _ in top_tags)
    return news.items[0].title


@dataclass
class MarketCommentaryProvider:
    realtime_provider: object
    news_provider: object | None = None

    def current_commentary(self) -> MarketCommentaryResponse:
        now = datetime.now(timezone.utc)
        diagnostics: list[str] = []
        snapshot: RealtimeMarketSnapshot | None = None
        news: MarketNewsResponse | None = None
        try:
            snapshot = self.realtime_provider.market_snapshot()
        except Exception as exc:
            diagnostics.append(f"行情评价读取实时快照失败：{exc}")
        if self.news_provider is not None:
            try:
                news = self.news_provider.latest_news(limit=12)
            except Exception as exc:
                diagnostics.append(f"行情评价读取新闻失败：{exc}")

        if snapshot is None or snapshot.status == "unavailable":
            if snapshot is not None and snapshot.message:
                diagnostics.append(f"行情评价实时快照不可用：{snapshot.message}")
            return MarketCommentaryResponse(
                updated_at=now,
                trade_date=now.date(),
                source="fallback",
                stance="defensive",
                summary="实时行情源暂不可用，今日评价先降级为防守模式；等待红绿家数、指数和题材榜恢复后再确认方向。",
                drivers=[],
                risks=["当前无法确认真实盘面强弱，避免只凭本地历史数据追高。"],
                next_watch=["优先恢复实时指数、红绿家数和题材榜接口，再运行策略筛选。"],
                diagnostics=diagnostics,
            )

        breadth = snapshot.breadth
        up_ratio = breadth.up / breadth.total if breadth and breadth.total > 0 else None
        main_index = snapshot.indexes[0] if snapshot.indexes else None
        index_pct = main_index.change_pct if main_index else None
        strong = snapshot.strong_sectors[:3]
        yesterday_names = {sector.name for sector in snapshot.yesterday_strong_sectors}
        continued = [sector.name for sector in strong if sector.name in yesterday_names]
        topic_text = "、".join(sector.name for sector in strong) or "暂未形成清晰题材"
        news_theme = _news_theme_text(news)

        if up_ratio is not None and up_ratio >= 0.58 and (index_pct or 0) >= 0:
            stance = "positive"
            tone = "红盘家数占优，指数同步配合"
        elif up_ratio is not None and up_ratio <= 0.42:
            stance = "defensive"
            tone = "绿盘压力偏大，先防守再选择"
        elif index_pct is not None and index_pct > 0 and up_ratio is not None and up_ratio < 0.5:
            stance = "neutral"
            tone = "指数偏红但个股扩散不足"
        else:
            stance = "neutral"
            tone = "盘面分化，适合等条件确认"

        breadth_text = (
            f"红盘 {breadth.up}、绿盘 {breadth.down}、平盘 {breadth.flat}"
            if breadth
            else "红绿家数暂缺"
        )
        index_text = (
            f"{main_index.name}{_format_pct(index_pct)}"
            if main_index
            else "指数暂缺"
        )
        summary_parts = [
            f"{tone}；{index_text}，{breadth_text}。",
            f"今日强势题材集中在 {topic_text}。",
        ]
        if continued:
            summary_parts.append(f"昨日强势中 {('、'.join(continued))} 仍在榜，说明资金有一定延续。")
        if news_theme:
            summary_parts.append(f"新闻侧重点落在 {news_theme}，可与题材榜交叉验证。")

        drivers: list[MarketCommentaryPoint] = []
        if strong:
            drivers.append(
                MarketCommentaryPoint(
                    title="强势题材",
                    detail="、".join(
                        f"{sector.name}{_format_pct(sector.change_pct)}"
                        for sector in strong
                    ),
                    weight="high",
                )
            )
        if breadth:
            drivers.append(
                MarketCommentaryPoint(
                    title="市场宽度",
                    detail=f"{breadth_text}，上涨占比 {up_ratio * 100:.1f}%。" if up_ratio is not None else breadth_text,
                    weight="high" if up_ratio is not None and up_ratio >= 0.58 else "medium",
                )
            )
        if news_theme:
            drivers.append(MarketCommentaryPoint(title="新闻催化", detail=news_theme, weight="medium"))

        risks: list[str] = []
        if up_ratio is not None and index_pct is not None and index_pct > 0 and up_ratio < 0.5:
            risks.append("指数上涨但个股弱，可能是权重护盘，策略需要更挑剔。")
        if not strong:
            risks.append("强势题材未返回，不能把指数波动误判成主线。")
        if not continued and snapshot.yesterday_strong_sectors:
            risks.append("昨日强势题材延续不足，追旧热点容易被切换节奏影响。")
        if not risks:
            risks.append("题材强时仍要看成交量延续，避免单日情绪过热后追高。")

        next_watch = [
            f"继续观察 {strong[0].name} 是否保持榜首和成交扩散。" if strong else "等待强势题材重新返回后再确认主线。",
            "运行策略后优先看命中股票是否集中在当日强势题材里。",
        ]
        if continued:
            next_watch.append(f"昨日强势延续方向：{('、'.join(continued))}，次日先看承接。")

        return MarketCommentaryResponse(
            updated_at=now,
            trade_date=_today_from_snapshot(snapshot).date(),
            source=f"{snapshot.source}+commentary",
            stance=stance,
            summary=" ".join(summary_parts),
            drivers=drivers,
            risks=risks,
            next_watch=next_watch,
            diagnostics=diagnostics,
        )
