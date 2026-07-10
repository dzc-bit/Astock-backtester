from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from astock_backtester.models import (
    MarketNewsItem,
    MarketNewsResponse,
    MarketNewsSummaryResponse,
    MarketNewsTheme,
)

FALLBACK_KEYWORDS = ("AI", "算力", "半导体", "机器人", "新能源", "电力", "地产", "券商", "政策", "退市", "ST")


def _theme_keys(item: MarketNewsItem) -> list[str]:
    keys = [tag for tag in item.tags if tag]
    text = f"{item.title} {item.summary or ''}"
    keys.extend(keyword for keyword in FALLBACK_KEYWORDS if keyword in text and keyword not in keys)
    return keys or ["市场动态"]


def _theme_sentiment(items: list[MarketNewsItem]) -> str:
    counts = Counter(item.sentiment for item in items)
    if counts["negative"] > counts["positive"]:
        return "negative"
    if counts["positive"] > counts["negative"]:
        return "positive"
    return "neutral"


def _theme_summary(theme: str, items: list[MarketNewsItem]) -> str:
    first = items[0]
    headline = first.summary or first.title
    if len(items) == 1:
        return headline
    sources = "、".join(sorted({item.source for item in items})[:3])
    return f"{theme}相关消息 {len(items)} 条，来源覆盖 {sources}；代表内容：{headline}"


def _same_day_items(news: MarketNewsResponse) -> list[MarketNewsItem]:
    trade_date = news.updated_at.date()
    dated_items = [
        item
        for item in news.items
        if item.published_at is not None and item.published_at.date() == trade_date
    ]
    return dated_items or news.items


@dataclass
class MarketNewsSummaryProvider:
    news_provider: object

    def latest_summary(self, limit: int = 24) -> MarketNewsSummaryResponse:
        now = datetime.now(timezone.utc)
        try:
            news: MarketNewsResponse = self.news_provider.latest_news(limit=limit)
        except Exception as exc:
            return MarketNewsSummaryResponse(
                updated_at=now,
                source="fallback",
                item_count=0,
                themes=[],
                highlights=[],
                risks=["新闻源读取失败，暂时无法形成当日新闻脉络。"],
                diagnostics=[f"新闻汇总读取失败：{exc}"],
            )
        diagnostics = list(news.diagnostics)
        if news.source == "fallback" or not news.items:
            return MarketNewsSummaryResponse(
                updated_at=now,
                source=f"{news.source}-summary",
                item_count=0,
                themes=[],
                highlights=[],
                risks=["当前没有可汇总的新闻，先不要把资讯缺口解读成市场没有事件。"],
                diagnostics=[*diagnostics, "新闻源暂无可汇总内容"],
            )
        items = _same_day_items(news)[:limit]

        groups: dict[str, list[MarketNewsItem]] = defaultdict(list)
        for item in items:
            for key in _theme_keys(item):
                groups[key].append(item)

        ranked = sorted(groups.items(), key=lambda pair: (len(pair[1]), pair[0]), reverse=True)[:6]
        themes = [
            MarketNewsTheme(
                title=theme,
                summary=_theme_summary(theme, items),
                sentiment=_theme_sentiment(items),  # type: ignore[arg-type]
                source_count=len({item.source for item in items}),
                headlines=[item.title for item in items[:4]],
            )
            for theme, items in ranked
        ]
        highlights = [
            item.title
            for item in sorted(
                items,
                key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )[:5]
        ]
        risks = [
            item.title
            for item in items
            if item.sentiment == "negative" or any(tag in {"ST", "退市"} for tag in item.tags)
        ][:4]
        if not risks:
            risks = ["新闻面暂未集中出现退市、ST 或明显利空词，但仍需结合盘面确认。"]

        return MarketNewsSummaryResponse(
            updated_at=now,
            source=f"{news.source}-summary",
            item_count=len(items),
            themes=themes,
            highlights=highlights,
            risks=risks,
            diagnostics=diagnostics,
        )
