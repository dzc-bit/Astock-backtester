from __future__ import annotations

import re
from html import unescape
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import requests

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


def _parse_epoch(value: object) -> datetime | None:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    if timestamp > 10_000_000_000:
        timestamp = timestamp / 1000
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def _clean_html_text(value: str | None) -> str:
    text = re.sub(r"<[^>]+>", "", value or "")
    return unescape(text).strip()


def _tags(title: str, summary: str | None) -> list[str]:
    text = f"{title} {summary or ''}"
    return [word for word in TAG_WORDS if word in text]


@dataclass
class MarketNewsProvider:
    timeout: float = 5.0
    requester: Callable[..., requests.Response] = requests.get

    def latest_news(self, limit: int = 18) -> MarketNewsResponse:
        now = datetime.now(timezone.utc)
        items: list[MarketNewsItem] = []
        sources: list[str] = []
        try:
            column_items = self._fetch_eastmoney_columns(limit)
            items.extend(column_items)
            if column_items:
                sources.append("eastmoney-columns")
        except Exception:
            pass
        try:
            rolling_items = self._fetch_eastmoney_rolling(limit)
            items.extend(rolling_items)
            if rolling_items:
                sources.append("eastmoney-rolling")
        except Exception:
            pass
        try:
            cailian_items = self._fetch_cailianpress(limit)
            items.extend(cailian_items)
            if cailian_items:
                sources.append("cls-telegraph")
        except Exception:
            pass
        items = self._dedupe_and_sort(items, limit)
        if items:
            return MarketNewsResponse(updated_at=now, source="+".join(sources), items=items)
        return MarketNewsResponse(
            updated_at=now,
            source="fallback",
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

    def _fetch_eastmoney_columns(self, limit: int) -> list[MarketNewsItem]:
        response = self.requester(
            "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns",
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
            timeout=self.timeout,
            headers={"Referer": "https://finance.eastmoney.com/"},
        )
        response.raise_for_status()
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

    def _fetch_eastmoney_rolling(self, limit: int) -> list[MarketNewsItem]:
        response = self.requester(
            "https://finance.eastmoney.com/yaowen.html",
            timeout=self.timeout,
            headers={"Referer": "https://finance.eastmoney.com/"},
        )
        response.raise_for_status()
        text = response.text
        items: list[MarketNewsItem] = []
        for href, title in re.findall(r'<a[^>]+href="([^"]+)"[^>]*title="([^"]+)"', text):
            cleaned_title = _clean_html_text(title)
            href = href.strip()
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

    def _fetch_cailianpress(self, limit: int) -> list[MarketNewsItem]:
        response = self.requester(
            "https://www.cls.cn/nodeapi/telegraphList",
            params={"app": "CailianpressWeb", "category": "", "lastTime": "", "last_time": "", "os": "web", "sv": "7.7.5"},
            timeout=self.timeout,
            headers={"Referer": "https://www.cls.cn/telegraph"},
        )
        response.raise_for_status()
        payload = response.json() or {}
        rows = (payload.get("data") or {}).get("roll_data") or (payload.get("data") or {}).get("list") or []
        items: list[MarketNewsItem] = []
        for row in rows[:limit]:
            title = str(row.get("title") or row.get("content") or "").strip()
            if not title:
                continue
            summary = str(row.get("content") or "").strip() or None
            timestamp = row.get("ctime") or row.get("time") or row.get("modified_time")
            items.append(
                MarketNewsItem(
                    title=_clean_html_text(title)[:120],
                    summary=_clean_html_text(summary) if summary and summary != title else None,
                    source="财联社电报",
                    published_at=_parse_epoch(timestamp),
                    url=f"https://www.cls.cn/detail/{row.get('id')}" if row.get("id") else None,
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
