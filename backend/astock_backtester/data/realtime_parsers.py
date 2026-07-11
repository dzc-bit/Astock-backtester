"""Pure parsing and normalization helpers for realtime market data.

Extracted from ``realtime.py`` to reduce file size without changing any
behavior.  All functions here are stateless and have no ``self`` parameter,
making them easy to unit-test in isolation.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, time, timedelta, timezone

from astock_backtester.data.cls import CLS_QUOTE_BASE_URL
from astock_backtester.data.providers import normalize_symbol
from astock_backtester.models import MarketBreadth, MarketIndexQuote, SectorMover

INDEXES = [
    ("sh000001", "上证指数"),
    ("sz399001", "深证成指"),
    ("sz399006", "创业板指"),
]

YESTERDAY_SECTOR_TRACKING_NOTE = "昨日强势板块追踪来自本地历史。"

BEIJING_TZ = timezone(timedelta(hours=8))

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
MIN_FULL_MARKET_BREADTH_TOTAL = 3000
MIN_LOCAL_BREADTH_RATIO = 0.65
MIN_CONTROLLED_BACKUP_SECTOR_ROWS = 3
THS_MARKET_SUMMARY_URL = "https://q.10jqka.com.cn/index/index/board/all/"
THS_CONCEPT_SECTION_URL = "https://q.10jqka.com.cn/gn/"
THS_INDUSTRY_HTML_URL = "https://q.10jqka.com.cn/thshy/index/field/199112/order/desc/page/{page}/"
THS_INDUSTRY_DETAIL_URL = "https://q.10jqka.com.cn/thshy/detail/code/{board_code}/"
THS_HOT_TOPIC_URL = "http://zx.10jqka.com.cn/event/api/getharden/date/{date}/orderby/date/orderway/desc/charset/GBK/"
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q={symbols}"
CLS_QUOTE_HOME_URL = f"{CLS_QUOTE_BASE_URL}/quote/index/home"
CLS_HOT_PLATE_URL = f"{CLS_QUOTE_BASE_URL}/web_quote/plate/hot_plate"
EASTMONEY_A_SPOT_URL = "https://82.push2.eastmoney.com/api/qt/clist/get"
EASTMONEY_SECTOR_URLS = [
    "https://push2.eastmoney.com/api/qt/clist/get",
    "https://82.push2.eastmoney.com/api/qt/clist/get",
    "https://29.push2.eastmoney.com/api/qt/clist/get",
]

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


def parse_int(value: object) -> int | None:
    text = str(value or "").strip().replace(",", "")
    match = re.search(r"-?\d+", text)
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def parse_float(value: object) -> float | None:
    text = str(value or "").strip().replace("%", "").replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def normalize_change_pct(value: object) -> float | None:
    change_pct = parse_float(value)
    if change_pct is None:
        return None
    return change_pct / 100 if abs(change_pct) > 1 else change_pct


def normalize_sector_change_pct(row: dict) -> float | None:
    change_pct = parse_float(row.get("f3", row.get("change_pct", row.get("涨跌幅"))))
    if change_pct is None:
        return None
    if row.get("_change_pct_unit") == "percent":
        return change_pct / 100
    return change_pct / 100 if abs(change_pct) > 1 else change_pct


def extract_code_from_href(href: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.search(href or "")
    return match.group(1) if match else None


def clean_ths_topic_name(value: object) -> str | None:
    topic = re.sub(r"\s+", "", str(value or ""))
    topic = topic.strip("-_")
    if not topic or topic in THS_GENERIC_TOPICS:
        return None
    if topic.endswith(("个股", "概念股")):
        return None
    return topic


def aggregate_ths_hot_topic_rows(rows: Iterable[dict]) -> list[dict]:
    aggregated: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        reason = str(row.get("reason") or "").strip()
        if not reason:
            continue
        symbol = normalize_symbol(str(row.get("code") or ""))
        gain = parse_float(row.get("zhangfu"))
        turnover = parse_float(row.get("chengjiaoe")) or 0.0
        for raw_topic in THS_TOPIC_SPLIT_RE.split(reason):
            topic = clean_ths_topic_name(raw_topic)
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


def aggregate_ths_hot_topics(rows: Iterable[dict]) -> list[SectorMover]:
    return [
        SectorMover(
            name=item["name"],
            change_pct=normalize_change_pct(item["change_pct"]) or 0.0,
            leading_symbol=item["leading_symbol"],
            source="ths-hot-reason",
        )
        for item in aggregate_ths_hot_topic_rows(rows)
    ]


def decode_sina_response(text: str) -> dict[str, list[str]]:
    quotes: dict[str, list[str]] = {}
    for segment in text.split(";"):
        if "hq_str_" not in segment or "=" not in segment:
            continue
        key = segment.split("hq_str_", 1)[1].split("=", 1)[0].strip()
        raw = segment.split("=", 1)[1].strip().strip('"')
        if raw:
            quotes[key] = raw.split(",")
    return quotes


def quote_from_sina(symbol: str, name: str, values: list[str]) -> MarketIndexQuote | None:
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


def quote_from_cls_home(row: dict) -> MarketIndexQuote | None:
    symbol = str(row.get("secu_code") or "").strip()
    name = str(row.get("secu_name") or symbol).strip()
    if not symbol:
        return None
    last = parse_float(row.get("last_px"))
    if last is None:
        return None
    previous_close = parse_float(row.get("preclose_px"))
    change = parse_float(row.get("change_px"))
    change_pct = normalize_change_pct(row.get("change"))
    return MarketIndexQuote(
        symbol=symbol,
        name=name,
        last=last,
        previous_close=previous_close,
        change=change,
        change_pct=change_pct,
        source="cls-quote-index",
    )


def breadth_from_cls_distribution(data: dict) -> MarketBreadth | None:
    if not isinstance(data, dict):
        return None
    up = parse_int(data.get("rise_num", data.get("up_num")))
    down = parse_int(data.get("fall_num", data.get("down_num")))
    flat = parse_int(data.get("flat_num")) or 0
    if up is None or down is None:
        return None
    distribution = {
        "up_limit": parse_int(data.get("up_num")) or 0,
        "up_10": parse_int(data.get("up_10")) or 0,
        "up_8": parse_int(data.get("up_8")) or 0,
        "up_6": parse_int(data.get("up_6")) or 0,
        "up_4": parse_int(data.get("up_4")) or 0,
        "up_2": parse_int(data.get("up_2")) or 0,
        "flat": flat,
        "down_2": parse_int(data.get("down_2")) or 0,
        "down_4": parse_int(data.get("down_4")) or 0,
        "down_6": parse_int(data.get("down_6")) or 0,
        "down_8": parse_int(data.get("down_8")) or 0,
        "down_10": parse_int(data.get("down_10")) or 0,
        "down_limit": parse_int(data.get("down_num")) or 0,
        "suspend": parse_int(data.get("suspend_num")) or 0,
    }
    return MarketBreadth(
        up=up,
        down=down,
        flat=flat,
        total=up + down + flat,
        source="cls-quote-breadth",
        distribution=distribution,
    )


def sector_rows_from_cls_hot_plate(payload: dict) -> list[dict]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return []
    rows: list[dict] = []
    for group in ("industry", "concept", "area"):
        items = data.get(group)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            leader = None
            up_stock = item.get("up_stock")
            if isinstance(up_stock, list) and up_stock and isinstance(up_stock[0], dict):
                leader = up_stock[0].get("secu_code")
            rows.append(
                {
                    "name": item.get("secu_name"),
                    "change_pct": item.get("change"),
                    "leading_symbol": leader,
                }
            )
    return rows


def dedupe_sectors(groups: Iterable[SectorMover], limit: int = 10) -> list[SectorMover]:
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


def append_yesterday_sector_note(message: str, yesterday_sectors: list[SectorMover]) -> str:
    if not yesterday_sectors or message.endswith(YESTERDAY_SECTOR_TRACKING_NOTE):
        return message
    return f"{message} {YESTERDAY_SECTOR_TRACKING_NOTE}"


def unique_sources(values: Iterable[str | None]) -> list[str]:
    sources: list[str] = []
    for value in values:
        if value and value not in sources:
            sources.append(value)
    return sources


def market_phase(now: datetime) -> str:
    local = now.astimezone(BEIJING_TZ)
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


def phase_diagnostic(phase: str) -> str | None:
    return {
        "non_trading": "周末或非交易日，降低实时接口刷新频率。",
        "pre_open": "盘前非连续竞价时段，降低实时接口刷新频率。",
        "lunch_break": "午间休市，降低实时接口刷新频率。",
        "post_close": "收盘后，降低实时接口刷新频率。",
    }.get(phase)


def is_renderable_snapshot(snapshot) -> bool:
    return bool(
        snapshot.indexes
        and snapshot.breadth
        and snapshot.breadth.total > 0
        and snapshot.strong_sectors
    )


def is_valid_full_market_breadth(
    breadth: MarketBreadth | None, local_symbol_count: int = 0
) -> bool:
    if breadth is None or breadth.total <= 0:
        return False
    if local_symbol_count >= MIN_FULL_MARKET_BREADTH_TOTAL:
        return (
            breadth.total >= MIN_FULL_MARKET_BREADTH_TOTAL
            and breadth.total >= int(local_symbol_count * MIN_LOCAL_BREADTH_RATIO)
        )
    return breadth.total >= MIN_FULL_MARKET_BREADTH_TOTAL


def a_share_market_symbol(symbol: str) -> str | None:
    """Convert a normalized A-share code to the ``sh``/``sz``/``bj`` prefix form
    used by Sina and Tencent quote APIs.

    This unifies the previously duplicated ``_sina_stock_symbol`` and
    ``_tencent_stock_symbol`` methods on ``RealtimeMarketProvider``.
    """
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
