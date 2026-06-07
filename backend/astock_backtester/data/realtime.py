from __future__ import annotations

import json
import re
import time as monotonic_time
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from typing import Callable, Iterable

import pandas as pd
import requests
from bs4 import BeautifulSoup

from astock_backtester.data.providers import normalize_symbol
from astock_backtester.data.warehouse import Warehouse
from astock_backtester.models import (
    MarketBreadth,
    MarketIndexQuote,
    RealtimeMarketSnapshot,
    SectorMover,
)


INDEXES = [
    ("sh000001", "上证指数"),
    ("sz399001", "深证成指"),
    ("sz399006", "创业板指"),
]

YESTERDAY_SECTOR_TRACKING_NOTE = "昨日强势板块追踪来自本地历史。"
THS_HEADERS = {
    "Referer": "https://q.10jqka.com.cn/",
    "User-Agent": "Mozilla/5.0",
}
THS_HOT_TOPIC_HEADERS = {
    "Referer": "http://zx.10jqka.com.cn/",
    "User-Agent": "Mozilla/5.0",
}
SINA_HEADERS = {
    "Referer": "https://finance.sina.com.cn/",
    "User-Agent": "Mozilla/5.0",
}
SINA_BREADTH_BATCH_SIZE = 400
THS_MARKET_SUMMARY_URL = "https://q.10jqka.com.cn/index/index/board/all/"
THS_CONCEPT_SECTION_URL = "https://q.10jqka.com.cn/gn/"
THS_INDUSTRY_HTML_URL = "https://q.10jqka.com.cn/thshy/index/field/199112/order/desc/page/{page}/"
THS_INDUSTRY_DETAIL_URL = "https://q.10jqka.com.cn/thshy/detail/code/{board_code}/"
THS_HOT_TOPIC_URL = "http://zx.10jqka.com.cn/event/api/getharden/date/{date}/orderby/date/orderway/desc/charset/GBK/"
THS_TOPIC_SPLIT_RE = re.compile(r"[+＋/、,，;；|]+")
THS_BREADTH_RE = re.compile(r"上涨[：:\s]*(\d+)\D+下跌[：:\s]*(\d+)\D+平盘[：:\s]*(\d+)")
THS_BOARD_CODE_RE = re.compile(r"/code/(\d+)")
THS_STOCK_CODE_RE = re.compile(r"/(\d{6})/?")
THS_GENERIC_TOPICS = {
    "",
    "A股",
    "个股",
    "市场",
    "两市",
    "沪深",
    "题材",
    "概念",
    "主线",
}


def _parse_int(value: object) -> int | None:
    text = str(value or "").strip().replace(",", "")
    match = re.search(r"-?\d+", text)
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def _parse_float(value: object) -> float | None:
    text = str(value or "").strip().replace("%", "").replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _normalize_change_pct(value: object) -> float | None:
    change_pct = _parse_float(value)
    if change_pct is None:
        return None
    return change_pct / 100 if abs(change_pct) > 1 else change_pct


def _normalize_sector_change_pct(row: dict) -> float | None:
    change_pct = _parse_float(row.get("f3", row.get("change_pct", row.get("涨跌幅"))))
    if change_pct is None:
        return None
    if row.get("_change_pct_unit") == "percent":
        return change_pct / 100
    return change_pct / 100 if abs(change_pct) > 1 else change_pct


def _extract_code_from_href(href: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.search(href or "")
    return match.group(1) if match else None


def _clean_ths_topic_name(value: object) -> str | None:
    topic = re.sub(r"\s+", "", str(value or ""))
    topic = topic.strip("-_")
    if not topic or topic in THS_GENERIC_TOPICS:
        return None
    if topic.endswith(("个股", "概念股")):
        return None
    return topic


def _aggregate_ths_hot_topic_rows(rows: Iterable[dict]) -> list[dict]:
    aggregated: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        reason = str(row.get("reason") or "").strip()
        if not reason:
            continue
        symbol = normalize_symbol(str(row.get("code") or ""))
        gain = _parse_float(row.get("zhangfu"))
        turnover = _parse_float(row.get("chengjiaoe")) or 0.0
        for raw_topic in THS_TOPIC_SPLIT_RE.split(reason):
            topic = _clean_ths_topic_name(raw_topic)
            if not topic:
                continue
            item = aggregated.setdefault(
                topic,
                {
                    "name": topic,
                    "count": 0,
                    "gain_sum": 0.0,
                    "turnover_sum": 0.0,
                    "members": [],
                    "leading_symbol": None,
                    "leading_gain": float("-inf"),
                    "source": "ths-hot-reason",
                },
            )
            item["count"] += 1
            if gain is not None:
                item["gain_sum"] += gain
                if gain > item["leading_gain"] and symbol:
                    item["leading_gain"] = gain
                    item["leading_symbol"] = symbol
            item["turnover_sum"] += turnover
            if symbol and symbol not in item["members"]:
                item["members"].append(symbol)

    ranked = sorted(
        aggregated.values(),
        key=lambda item: (
            item["count"],
            item["gain_sum"] / item["count"] if item["count"] else 0.0,
            item["turnover_sum"],
            item["name"],
        ),
        reverse=True,
    )
    rows_out: list[dict] = []
    for item in ranked:
        average_gain = item["gain_sum"] / item["count"] if item["count"] else 0.0
        rows_out.append(
            {
                "name": item["name"],
                "change_pct": average_gain,
                "leading_symbol": item["leading_symbol"],
                "members": item["members"],
                "source": "ths-hot-reason",
            }
        )
    return rows_out


def _aggregate_ths_hot_topics(rows: Iterable[dict]) -> list[SectorMover]:
    return [
        SectorMover(
            name=item["name"],
            change_pct=_normalize_change_pct(item["change_pct"]) or 0.0,
            leading_symbol=item["leading_symbol"],
            source="ths-hot-reason",
        )
        for item in _aggregate_ths_hot_topic_rows(rows)
    ]


def _decode_sina_response(text: str) -> dict[str, list[str]]:
    quotes: dict[str, list[str]] = {}
    for segment in text.split(";"):
        if "hq_str_" not in segment or "=" not in segment:
            continue
        key = segment.split("hq_str_", 1)[1].split("=", 1)[0].strip()
        raw = segment.split("=", 1)[1].strip().strip('"')
        if raw:
            quotes[key] = raw.split(",")
    return quotes


def _quote_from_sina(symbol: str, name: str, values: list[str]) -> MarketIndexQuote | None:
    try:
        last = float(values[3])
        previous_close = float(values[2])
    except (IndexError, TypeError, ValueError):
        return None
    change = last - previous_close
    change_pct = change / previous_close if previous_close else 0.0
    updated_at = None
    try:
        updated_at = datetime.fromisoformat(f"{values[30]}T{values[31]}+08:00")
    except (IndexError, TypeError, ValueError):
        pass
    return MarketIndexQuote(
        symbol=symbol,
        name=name,
        last=last,
        previous_close=previous_close,
        change=change,
        change_pct=change_pct,
        source="ashare-sina",
        updated_at=updated_at,
    )


def _dedupe_sectors(groups: Iterable[SectorMover], limit: int = 10) -> list[SectorMover]:
    sectors: list[SectorMover] = []
    seen: set[str] = set()
    for group in groups:
        if group.name in seen:
            continue
        sectors.append(group)
        seen.add(group.name)
        if len(sectors) >= limit:
            break
    return sectors


def _append_yesterday_sector_note(message: str, yesterday_sectors: list[SectorMover]) -> str:
    if not yesterday_sectors or message.endswith(YESTERDAY_SECTOR_TRACKING_NOTE):
        return message
    return f"{message} {YESTERDAY_SECTOR_TRACKING_NOTE}"


def _market_phase(now: datetime) -> str:
    local = now.astimezone(timezone(timedelta(hours=8)))
    if local.weekday() >= 5:
        return "non_trading"
    current = local.time()
    if current < time(9, 30):
        return "pre_open"
    if time(11, 30) <= current < time(13, 0):
        return "lunch_break"
    if current >= time(15, 0):
        return "post_close"
    return "trading"


def _phase_diagnostic(phase: str) -> str | None:
    return {
        "non_trading": "周末或非交易日，降低实时接口刷新频率。",
        "pre_open": "盘前非连续竞价时段，降低实时接口刷新频率。",
        "lunch_break": "午间休市，降低实时接口刷新频率。",
        "post_close": "收盘后，降低实时接口刷新频率。",
    }.get(phase)


def _is_renderable_snapshot(snapshot: RealtimeMarketSnapshot) -> bool:
    return bool(snapshot.indexes and snapshot.breadth and snapshot.breadth.total > 0 and snapshot.strong_sectors)


def unavailable_market_snapshot(message: str, *, diagnostics: list[str] | None = None) -> RealtimeMarketSnapshot:
    now = datetime.now(timezone.utc)
    return RealtimeMarketSnapshot(
        status="unavailable",
        source="service-fallback",
        updated_at=now,
        market_phase=_market_phase(now),
        message=message,
        diagnostics=diagnostics or [],
    )


@dataclass
class RealtimeMarketProvider:
    warehouse: Warehouse
    timeout: float = 4.0
    requester: Callable[..., requests.Response] = requests.get
    breadth_time_budget: float = 2.0
    _last_live_sector_rows: list[dict] = field(default_factory=list, init=False, repr=False)
    _sector_member_cache: dict[str, list[str]] = field(default_factory=dict, init=False, repr=False)
    _ths_concept_rows_cache: list[dict] | None = field(default=None, init=False, repr=False)
    _ths_industry_rows_cache: list[dict] | None = field(default=None, init=False, repr=False)
    _last_successful_snapshot: RealtimeMarketSnapshot | None = field(default=None, init=False, repr=False)

    def market_snapshot(self) -> RealtimeMarketSnapshot:
        now = datetime.now(timezone.utc)
        phase = _market_phase(now)
        diagnostics: list[str] = []
        phase_note = _phase_diagnostic(phase)
        if phase_note:
            diagnostics.append(phase_note)
        self._ths_concept_rows_cache = None
        self._ths_industry_rows_cache = None
        self._last_live_sector_rows = []
        indexes = self._fetch_indexes()
        live_sectors = self._fetch_live_sectors()
        live_breadth = self._fetch_live_breadth()
        local_snapshot = self._snapshot_from_local(now)
        strong_sectors = live_sectors or local_snapshot.strong_sectors
        yesterday_sectors = local_snapshot.yesterday_strong_sectors
        breadth = live_breadth or local_snapshot.breadth
        status = "live" if indexes else local_snapshot.status
        if not indexes:
            diagnostics.append("实时指数接口暂不可用，尝试使用最近成功快照或本地最近交易日。")
        if indexes and not live_breadth and local_snapshot.breadth:
            diagnostics.append("实时红绿家数接口暂不可用，已回退到本地最近交易日统计。")
        if indexes and not live_sectors and local_snapshot.strong_sectors:
            diagnostics.append("实时强势题材接口暂不可用，已回退到本地最近交易日题材聚合。")
        source_parts: list[str] = []
        if indexes:
            source_parts.append("ashare-sina")
        if live_breadth:
            source_parts.append(live_breadth.source)
        elif local_snapshot.breadth:
            source_parts.append(local_snapshot.breadth.source)
        if live_sectors:
            source_parts.append(live_sectors[0].source)
        elif local_snapshot.strong_sectors:
            source_parts.append(local_snapshot.strong_sectors[0].source)
        if yesterday_sectors:
            source_parts.append("local-yesterday-group")
        source = "+".join(source_parts) if source_parts else local_snapshot.source
        if not indexes:
            message = local_snapshot.message
        else:
            message = self._build_live_message(live_breadth, live_sectors)
        message = _append_yesterday_sector_note(message, yesterday_sectors)
        snapshot = RealtimeMarketSnapshot(
            status=status,
            source=source,
            updated_at=now,
            market_phase=phase,
            indexes=indexes or local_snapshot.indexes,
            breadth=breadth,
            strong_sectors=strong_sectors,
            yesterday_strong_sectors=yesterday_sectors,
            message=message,
            diagnostics=diagnostics,
        )
        if snapshot.status == "live" and _is_renderable_snapshot(snapshot):
            self._last_successful_snapshot = snapshot.model_copy(deep=True)
            return snapshot
        if self._last_successful_snapshot is not None and not indexes:
            retained = self._last_successful_snapshot.model_copy(deep=True)
            retained.status = "stale"
            retained.updated_at = now
            retained.market_phase = phase
            retained.source = (
                retained.source
                if retained.source.endswith("+retained-last-success")
                else f"{retained.source}+retained-last-success"
            )
            retained.message = _append_yesterday_sector_note(
                f"{phase_note or '实时接口暂不可用'} 沿用最近成功行情快照。", retained.yesterday_strong_sectors
            )
            retained.diagnostics = [
                *diagnostics,
                f"沿用最近成功行情快照：{self._last_successful_snapshot.updated_at.isoformat()}。",
            ]
            return retained
        if snapshot.status == "stale" and _is_renderable_snapshot(snapshot):
            self._last_successful_snapshot = snapshot.model_copy(deep=True)
        return snapshot

    def _fetch_indexes(self) -> list[MarketIndexQuote]:
        symbols = ",".join(symbol for symbol, _ in INDEXES)
        url = f"https://hq.sinajs.cn/list={symbols}"
        try:
            response = self.requester(
                url,
                timeout=self.timeout,
                headers={"Referer": "https://finance.sina.com.cn/"},
            )
            response.raise_for_status()
        except Exception:
            return []
        response.encoding = response.encoding or "gbk"
        decoded = _decode_sina_response(response.text)
        quotes: list[MarketIndexQuote] = []
        for symbol, name in INDEXES:
            quote = _quote_from_sina(symbol, name, decoded.get(symbol, []))
            if quote:
                quotes.append(quote)
        return quotes

    def _fetch_live_sectors(self) -> list[SectorMover]:
        ths_concept_rows = self._fetch_ths_concept_section_rows()
        ths_concept_sectors = self._parse_sector_rows(ths_concept_rows, "ths-concept-section")
        if ths_concept_sectors:
            self._last_live_sector_rows = ths_concept_rows
            return _dedupe_sectors(ths_concept_sectors, 10)
        ths_industry_rows = self._fetch_ths_industry_html_rows()
        ths_industry_sectors = self._parse_sector_rows(ths_industry_rows, "ths-industry-html")
        if ths_industry_sectors:
            self._last_live_sector_rows = ths_industry_rows
            return _dedupe_sectors(ths_industry_sectors, 10)
        sina_sectors = self._fetch_sina_sectors()
        self._last_live_sector_rows = []
        if sina_sectors:
            return _dedupe_sectors(sina_sectors, 10)
        ths_hot_topic_rows = self._fetch_ths_hot_topic_rows()
        if ths_hot_topic_rows:
            # Hot-reason rows are useful topic candidates, but their gains are
            # individual stock moves. Do not present them as board quote pct.
            self._last_live_sector_rows = ths_hot_topic_rows
        return []

    def _parse_sector_rows(self, rows: list[dict], source: str) -> list[SectorMover]:
        sectors: list[SectorMover] = []
        for row in rows:
            name = str(row.get("f14") or row.get("name") or row.get("板块") or "").strip()
            if not name:
                continue
            change_pct = _normalize_sector_change_pct(row)
            if change_pct is None:
                continue
            leader = str(row.get("f140") or row.get("f128") or row.get("leading_symbol") or "").strip() or None
            sectors.append(
                SectorMover(
                    name=name,
                    change_pct=change_pct,
                    leading_symbol=normalize_symbol(leader) if leader else None,
                    source=source,
                )
            )
        return sectors

    def _fetch_live_breadth(self) -> MarketBreadth | None:
        ths_breadth = self._fetch_ths_market_summary_breadth()
        if ths_breadth:
            return ths_breadth
        sina_breadth = self._fetch_sina_breadth()
        if sina_breadth:
            return sina_breadth
        return None

    def _fetch_sina_breadth(self) -> MarketBreadth | None:
        deadline = monotonic_time.monotonic() + self.breadth_time_budget
        symbols = self._latest_local_symbols()
        if not symbols:
            return None
        sina_symbols = [sina_symbol for symbol in symbols if (sina_symbol := self._sina_stock_symbol(symbol))]
        if not sina_symbols:
            return None

        up = 0
        down = 0
        flat = 0
        seen: set[str] = set()
        for start in range(0, len(sina_symbols), SINA_BREADTH_BATCH_SIZE):
            remaining = deadline - monotonic_time.monotonic()
            if remaining <= 0:
                return None
            batch = sina_symbols[start : start + SINA_BREADTH_BATCH_SIZE]
            try:
                response = self.requester(
                    "https://hq.sinajs.cn/list=" + ",".join(batch),
                    timeout=min(self.timeout, max(0.2, remaining)),
                    headers=SINA_HEADERS,
                )
                response.raise_for_status()
            except Exception:
                return None
            raw_content = getattr(response, "content", b"")
            if raw_content:
                text = raw_content.decode("gbk", errors="ignore")
            else:
                response.encoding = response.encoding or "gbk"
                text = response.text
            decoded = _decode_sina_response(text)
            if not decoded:
                continue
            for sina_symbol in batch:
                values = decoded.get(sina_symbol, [])
                if len(values) < 4:
                    continue
                previous_close = _parse_float(values[2])
                last = _parse_float(values[3])
                if previous_close is None or previous_close <= 0 or last is None or last <= 0:
                    continue
                symbol = normalize_symbol(sina_symbol[-6:])
                if symbol in seen:
                    continue
                seen.add(symbol)
                if last > previous_close:
                    up += 1
                elif last < previous_close:
                    down += 1
                else:
                    flat += 1
        total = up + down + flat
        if total == 0:
            return None
        return MarketBreadth(
            up=up,
            down=down,
            flat=flat,
            total=total,
            source="sina-a-share-live",
        )

    def _latest_local_symbols(self) -> list[str]:
        try:
            latest = self.warehouse.read_latest_daily_bars(days=1)
        except Exception:
            return []
        if latest.empty or "symbol" not in latest.columns:
            return []
        symbols: list[str] = []
        seen: set[str] = set()
        for value in latest["symbol"].dropna():
            symbol = normalize_symbol(str(value))
            if symbol and symbol not in seen:
                symbols.append(symbol)
                seen.add(symbol)
        return symbols

    def _sina_stock_symbol(self, symbol: str) -> str | None:
        code = normalize_symbol(symbol)
        if not code:
            return None
        if code.startswith(("6", "9")):
            return f"sh{code}"
        if code.startswith(("0", "2", "3")):
            return f"sz{code}"
        if code.startswith(("4", "8")):
            return f"bj{code}"
        return None

    def _fetch_sina_sectors(self) -> list[SectorMover]:
        try:
            response = self.requester(
                "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php",
                timeout=self.timeout,
                headers={
                    "Referer": "https://finance.sina.com.cn/",
                    "User-Agent": "Mozilla/5.0",
                },
            )
            response.raise_for_status()
        except Exception:
            return []
        response.encoding = response.encoding or "gbk"
        text = response.text
        rows: list[dict] = []
        for match in re.finditer(r'"[^"]+"\s*:\s*"([^"]+)"', text):
            values = match.group(1).split(",")
            if len(values) < 6:
                continue
            name = values[1].strip()
            pct_text = values[5].strip()
            leader = values[8].strip() if len(values) > 8 else ""
            if name and _parse_float(pct_text) is not None:
                rows.append(
                    {
                        "name": name,
                        "change_pct": pct_text,
                        "_change_pct_unit": "percent",
                        "leading_symbol": leader,
                    }
                )
        if rows:
            return self._parse_sector_rows(rows, "sina-sector")
        for chunk in text.split("},"):
            if "name:" not in chunk or "changepercent:" not in chunk:
                continue
            try:
                name = chunk.split("name:", 1)[1].split(",", 1)[0].strip("'\" ")
                pct_text = chunk.split("changepercent:", 1)[1].split(",", 1)[0].strip("'\" ")
                leader = ""
                if "symbol:" in chunk:
                    leader = chunk.split("symbol:", 1)[1].split(",", 1)[0].strip("'\" ")
                rows.append(
                    {
                        "name": name,
                        "change_pct": pct_text,
                        "_change_pct_unit": "percent",
                        "leading_symbol": leader,
                    }
                )
            except Exception:
                continue
        return self._parse_sector_rows(rows, "sina-sector")

    def _fetch_ths_hot_topic_rows(self) -> list[dict]:
        today = datetime.now().date()
        for offset in range(3):
            target = today - timedelta(days=offset)
            try:
                response = self.requester(
                    THS_HOT_TOPIC_URL.format(date=target.isoformat()),
                    timeout=self.timeout,
                    headers=THS_HOT_TOPIC_HEADERS,
                )
                response.raise_for_status()
                payload = response.json() or {}
            except Exception:
                continue
            if payload.get("errocode") not in (0, "0", None):
                continue
            rows = payload.get("data") or []
            if not isinstance(rows, list):
                continue
            if rows:
                return _aggregate_ths_hot_topic_rows(rows)
        return []

    def _fetch_ths_concept_section_rows(self) -> list[dict]:
        if self._ths_concept_rows_cache is not None:
            return self._ths_concept_rows_cache
        try:
            response = self.requester(
                THS_CONCEPT_SECTION_URL,
                timeout=self.timeout,
                headers=THS_HEADERS,
            )
            response.raise_for_status()
        except Exception:
            self._ths_concept_rows_cache = []
            return []
        response.encoding = response.encoding or "gbk"
        soup = BeautifulSoup(response.text, "html.parser")
        node = soup.select_one("#gnSection")
        raw_value = str(node.get("value") or "") if node else ""
        if not raw_value:
            self._ths_concept_rows_cache = []
            return []
        try:
            payload = json.loads(raw_value)
        except (TypeError, ValueError):
            self._ths_concept_rows_cache = []
            return []
        if not isinstance(payload, dict):
            self._ths_concept_rows_cache = []
            return []
        rows: list[dict] = []
        seen: set[str] = set()
        for item in payload.values():
            if not isinstance(item, dict):
                continue
            name = str(item.get("platename") or "").strip()
            board_code = str(item.get("platecode") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            rows.append(
                {
                    "code": board_code,
                    "f12": board_code,
                    "name": name,
                    "f14": name,
                    "change_pct": item.get("199112"),
                    "_change_pct_unit": "percent",
                    "_source": "ths-concept-section",
                }
            )
        rows.sort(key=lambda row: _normalize_sector_change_pct(row) or float("-inf"), reverse=True)
        self._ths_concept_rows_cache = rows
        return rows

    def _fetch_ths_industry_html_rows(self, max_pages: int = 3) -> list[dict]:
        if self._ths_industry_rows_cache is not None:
            return self._ths_industry_rows_cache
        rows_out: list[dict] = []
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            try:
                response = self.requester(
                    THS_INDUSTRY_HTML_URL.format(page=page),
                    timeout=self.timeout,
                    headers=THS_HEADERS,
                )
                response.raise_for_status()
            except Exception:
                break
            response.encoding = response.encoding or "gbk"
            soup = BeautifulSoup(response.text, "html.parser")
            table_rows = soup.select("table.m-table.m-pager-table tbody tr")
            if not table_rows:
                break
            added = 0
            for row in table_rows:
                cells = [" ".join(cell.get_text(" ", strip=True).split()) for cell in row.find_all("td")]
                if len(cells) < 10:
                    continue
                links = row.find_all("a", href=True)
                board_code = None
                leader_symbol = None
                for link in links:
                    href = str(link.get("href") or "")
                    if board_code is None and "/thshy/detail/code/" in href:
                        board_code = _extract_code_from_href(href, THS_BOARD_CODE_RE)
                    if leader_symbol is None and "stockpage.10jqka.com.cn" in href:
                        leader_symbol = _extract_code_from_href(href, THS_STOCK_CODE_RE)
                dedupe_key = board_code or cells[1]
                if not dedupe_key or dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                rows_out.append(
                    {
                        "code": board_code or "",
                        "f12": board_code or "",
                        "name": cells[1],
                        "f14": cells[1],
                        "change_pct": cells[2],
                        "_change_pct_unit": "percent",
                        "leading_symbol": normalize_symbol(leader_symbol) if leader_symbol else None,
                        "up_count": _parse_int(cells[6]) or 0,
                        "down_count": _parse_int(cells[7]) or 0,
                    }
                )
                added += 1
            if added == 0:
                break
        self._ths_industry_rows_cache = rows_out
        return rows_out

    def _fetch_ths_market_summary_breadth(self) -> MarketBreadth | None:
        try:
            response = self.requester(
                THS_MARKET_SUMMARY_URL,
                timeout=self.timeout,
                headers=THS_HEADERS,
            )
            response.raise_for_status()
            response.encoding = response.encoding or "gbk"
            text = BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)
            match = THS_BREADTH_RE.search(text)
            if match:
                up, down, flat = (int(item) for item in match.groups())
                return MarketBreadth(
                    up=up,
                    down=down,
                    flat=flat,
                    total=up + down + flat,
                    source="ths-market-summary",
                )
        except Exception:
            pass

        industry_rows = self._fetch_ths_industry_html_rows()
        if not industry_rows:
            return None
        up = sum(int(row.get("up_count") or 0) for row in industry_rows)
        down = sum(int(row.get("down_count") or 0) for row in industry_rows)
        if up + down == 0:
            return None
        total = self._latest_local_symbol_count()
        if total >= up + down:
            flat = total - up - down
        else:
            flat = 0
            total = up + down
        return MarketBreadth(
            up=up,
            down=down,
            flat=flat,
            total=total,
            source="ths-market-summary",
        )

    def _latest_local_symbol_count(self) -> int:
        try:
            bars = self.warehouse.read_latest_daily_bars(days=3)
        except Exception:
            return 0
        if bars.empty or "trade_date" not in bars.columns:
            return 0
        data = bars.copy()
        data["trade_date"] = pd.to_datetime(data["trade_date"])
        latest_date = data["trade_date"].max()
        latest = data[data["trade_date"] == latest_date]
        return int(latest["symbol"].astype(str).nunique())

    def _build_live_message(
        self,
        live_breadth: MarketBreadth | None,
        live_sectors: list[SectorMover],
    ) -> str:
        breadth_label = {
            "ths-market-summary": "同花顺市场总览",
            "sina-a-share-live": "新浪实时个股",
        }.get(live_breadth.source if live_breadth else None)
        sector_label = {
            "ths-hot-reason": "同花顺热点归因",
            "ths-concept-section": "同花顺概念题材板块",
            "ths-industry-html": "同花顺行业板块总览",
            "sina-sector": "新浪行业板块",
        }.get(live_sectors[0].source if live_sectors else None)

        if sector_label and breadth_label:
            return f"实时指数来自 Ashare/Sina，强势题材来自{sector_label}，红绿家数来自{breadth_label}。"
        if sector_label:
            return f"实时指数来自 Ashare/Sina，强势题材来自{sector_label}，红绿家数暂回退到本地最近交易日。"
        if breadth_label:
            return f"实时指数来自 Ashare/Sina，红绿家数来自{breadth_label}，强势题材暂不可用。"
        return "实时指数来自 Ashare/Sina，红绿家数与强势题材暂回退到本地最近交易日。"

    def _snapshot_from_local(self, now: datetime) -> RealtimeMarketSnapshot:
        try:
            bars = self.warehouse.read_latest_daily_bars(days=3)
        except Exception as exc:
            return RealtimeMarketSnapshot(
                status="unavailable",
                source="local",
                updated_at=now,
                market_phase=_market_phase(now),
                message=f"实时行情不可用，本地数据读取失败：{exc}",
                diagnostics=[f"本地最近交易日读取失败：{exc}"],
            )
        if bars.empty:
            return RealtimeMarketSnapshot(
                status="unavailable",
                source="local",
                updated_at=now,
                market_phase=_market_phase(now),
                message="实时行情不可用，本地历史数据为空。",
                diagnostics=["本地最近交易日为空，无法生成兜底快照。"],
            )

        data = bars.copy()
        data["trade_date"] = pd.to_datetime(data["trade_date"])
        recent_dates = sorted(data["trade_date"].drop_duplicates().tolist())[-3:]
        latest_date = recent_dates[-1]
        previous_date = recent_dates[-2] if len(recent_dates) >= 2 else None
        prior_date = recent_dates[-3] if len(recent_dates) >= 3 else None
        latest = self._with_previous_close(data, latest_date, previous_date)
        yesterday = (
            self._with_previous_close(data, previous_date, prior_date)
            if previous_date is not None and prior_date is not None
            else pd.DataFrame()
        )

        up = int((latest["change_pct"] > 0).sum())
        down = int((latest["change_pct"] < 0).sum())
        flat = int((latest["change_pct"] == 0).sum())
        breadth = MarketBreadth(up=up, down=down, flat=flat, total=int(len(latest)), source="local-latest")

        pseudo_index = MarketIndexQuote(
            symbol="local-market",
            name="本地全市场",
            last=float(latest["close"].mean()),
            previous_close=float(latest["previous_close"].mean()),
            change=float(latest["close"].mean() - latest["previous_close"].mean()),
            change_pct=float(latest["change_pct"].mean()),
            source="local-latest",
            updated_at=now,
        )
        local_sectors = self._local_market_groups(latest, source="local-market-group")
        yesterday_sectors = self._local_market_groups(yesterday, source="local-yesterday-group")
        message = _append_yesterday_sector_note(
            f"实时行情源暂不可用，已使用本地最近交易日 {latest_date.date()} 数据。",
            yesterday_sectors,
        )
        return RealtimeMarketSnapshot(
            status="stale",
            source="local-latest",
            updated_at=now,
            market_phase=_market_phase(now),
            indexes=[pseudo_index],
            breadth=breadth,
            strong_sectors=local_sectors,
            yesterday_strong_sectors=yesterday_sectors,
            message=message,
            diagnostics=[f"已使用本地最近交易日 {latest_date.date()} 作为兜底快照。"],
        )

    def _with_previous_close(
        self,
        data: pd.DataFrame,
        target_date: pd.Timestamp,
        previous_date: pd.Timestamp | None,
    ) -> pd.DataFrame:
        current = data[data["trade_date"] == target_date].copy()
        if previous_date is not None:
            previous = data[data["trade_date"] == previous_date][["symbol", "close"]].rename(
                columns={"close": "previous_close"}
            )
            current = current.merge(previous, on="symbol", how="left")
        if "previous_close" not in current:
            current["previous_close"] = current["open"]
        current["previous_close"] = current["previous_close"].fillna(current["open"])
        current["change_pct"] = (current["close"] / current["previous_close"]) - 1
        current["change_pct"] = current["change_pct"].replace([float("inf"), -float("inf")], pd.NA)
        return current

    def _local_market_groups(self, latest: pd.DataFrame, source: str) -> list[SectorMover]:
        sector_rows = self._last_live_sector_rows
        if latest.empty:
            return []
        if not sector_rows:
            sector_rows = self._fetch_ths_hot_topic_rows()
        if not sector_rows:
            return []
        rows: list[SectorMover] = []
        data = latest.copy()
        data["symbol"] = data["symbol"].astype(str).map(normalize_symbol)
        for board in sector_rows[:20]:
            board_code = str(board.get("f12") or board.get("code") or "").strip()
            board_name = str(board.get("f14") or board.get("name") or "").strip()
            members = [normalize_symbol(item) for item in board.get("members") or [] if str(item).strip()]
            if not board_name:
                continue
            if not members:
                if not board_code:
                    continue
                members = self._fetch_board_members(board_code)
            if not members:
                continue
            valid = data[data["symbol"].isin(members)].dropna(subset=["change_pct"])
            if valid.empty:
                continue
            leader = valid.sort_values("change_pct", ascending=False).iloc[0]
            rows.append(
                SectorMover(
                    name=board_name,
                    change_pct=float(valid["change_pct"].mean()),
                    leading_symbol=normalize_symbol(str(leader["symbol"])),
                    source=source,
                )
            )
        return sorted(rows, key=lambda item: item.change_pct, reverse=True)[:10]

    def _fetch_board_members(self, board_code: str) -> list[str]:
        cached = self._sector_member_cache.get(board_code)
        if cached is not None:
            return cached
        if board_code.isdigit() and board_code.startswith("88"):
            members = self._fetch_ths_board_members(board_code)
        else:
            members = []
        self._sector_member_cache[board_code] = members
        return members

    def _fetch_ths_board_members(self, board_code: str) -> list[str]:
        try:
            response = self.requester(
                THS_INDUSTRY_DETAIL_URL.format(board_code=board_code),
                timeout=self.timeout,
                headers=THS_HEADERS,
            )
            response.raise_for_status()
        except Exception:
            return []
        response.encoding = response.encoding or "gbk"
        soup = BeautifulSoup(response.text, "html.parser")
        rows = soup.select("table.m-table.m-pager-table tbody tr")
        members: list[str] = []
        seen: set[str] = set()
        for row in rows:
            cells = [" ".join(cell.get_text(" ", strip=True).split()) for cell in row.find_all("td")]
            if len(cells) < 3:
                continue
            symbol = normalize_symbol(cells[1])
            if not symbol or not symbol.isdigit() or symbol in seen:
                continue
            seen.add(symbol)
            members.append(symbol)
        return members
