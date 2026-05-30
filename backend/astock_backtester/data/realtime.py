from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable

import pandas as pd
import requests

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
EASTMONEY_HEADERS = {
    "Referer": "https://quote.eastmoney.com/",
    "User-Agent": "Mozilla/5.0",
}
EASTMONEY_UT = "bd1d9ddb04089700cf9c27f6f7426281"
CONCEPT_FIELDS = "f2,f3,f4,f8,f12,f14,f20,f104,f105,f128,f136"
INDUSTRY_FIELDS = "f1,f2,f3,f4,f8,f12,f14,f20,f104,f105,f128,f136"
A_SHARE_BREADTH_FIELDS = "f12,f14,f3"
CONCEPT_FS = "m:90+t:3+f:!50"
INDUSTRY_FS = "m:90+t:2+f:!50"
A_SHARE_BREADTH_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"


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


@dataclass
class RealtimeMarketProvider:
    warehouse: Warehouse
    timeout: float = 4.0
    requester: Callable[..., requests.Response] = requests.get
    _last_live_sector_rows: list[dict] = field(default_factory=list, init=False, repr=False)
    _sector_member_cache: dict[str, list[str]] = field(default_factory=dict, init=False, repr=False)

    def market_snapshot(self) -> RealtimeMarketSnapshot:
        now = datetime.now(timezone.utc)
        indexes = self._fetch_indexes()
        live_sectors = self._fetch_live_sectors()
        live_breadth = self._fetch_live_breadth()
        local_snapshot = self._snapshot_from_local(now)
        strong_sectors = live_sectors or local_snapshot.strong_sectors
        yesterday_sectors = local_snapshot.yesterday_strong_sectors
        breadth = live_breadth or local_snapshot.breadth
        status = "live" if indexes else local_snapshot.status
        source_parts: list[str] = []
        if indexes:
            source_parts.append("ashare-sina")
        if live_breadth:
            source_parts.append("eastmoney-a-share-live")
        elif local_snapshot.breadth:
            source_parts.append("local")
        if live_sectors:
            source_parts.append(live_sectors[0].source)
        elif local_snapshot.strong_sectors:
            source_parts.append("local-market-group")
        if yesterday_sectors:
            source_parts.append("local-yesterday-group")
        source = "+".join(source_parts) if source_parts else local_snapshot.source
        if not indexes:
            message = local_snapshot.message
        elif not live_sectors:
            if live_breadth:
                message = "实时指数与红绿家数来自 Ashare/Sina 和东方财富，全市场题材榜暂不可用，昨日强势追踪使用本地历史。"
            else:
                message = "实时指数来自 Ashare/Sina，红绿家数与昨日强势追踪使用本地历史；东方财富题材榜暂不可用。"
        else:
            uses_industry_fallback = any(item.source == "eastmoney-industry-sector" for item in live_sectors)
            if uses_industry_fallback:
                message = "实时指数来自 Ashare/Sina，强势题材优先取东方财富概念榜，当前已回退到东方财富行业板块；红绿家数来自东方财富实时全A。"
            else:
                message = "实时指数来自 Ashare/Sina，强势题材来自东方财富概念板块，红绿家数来自东方财富实时全A。"
        message = _append_yesterday_sector_note(message, yesterday_sectors)
        return RealtimeMarketSnapshot(
            status=status,
            source=source,
            updated_at=now,
            indexes=indexes or local_snapshot.indexes,
            breadth=breadth,
            strong_sectors=strong_sectors,
            yesterday_strong_sectors=yesterday_sectors,
            message=message,
        )

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
        concept_rows = self._fetch_sector_rows(CONCEPT_FS, CONCEPT_FIELDS)
        concept_sectors = self._parse_sector_rows(
            concept_rows,
            "eastmoney-sector",
        )
        if concept_sectors:
            self._last_live_sector_rows = [dict(row, _source="eastmoney-sector") for row in concept_rows]
            return _dedupe_sectors(concept_sectors, 10)
        industry_rows = self._fetch_sector_rows(INDUSTRY_FS, INDUSTRY_FIELDS)
        industry_sectors = self._parse_sector_rows(
            industry_rows,
            "eastmoney-industry-sector",
        )
        if industry_sectors:
            self._last_live_sector_rows = [dict(row, _source="eastmoney-industry-sector") for row in industry_rows]
            return _dedupe_sectors(industry_sectors, 10)
        sina_sectors = self._fetch_sina_sectors()
        self._last_live_sector_rows = []
        if sina_sectors:
            return _dedupe_sectors(sina_sectors, 10)
        return []

    def _parse_sector_rows(self, rows: list[dict], source: str) -> list[SectorMover]:
        sectors: list[SectorMover] = []
        for row in rows:
            name = str(row.get("f14") or row.get("name") or row.get("板块") or "").strip()
            if not name:
                continue
            try:
                raw_change = row.get("f3", row.get("change_pct", row.get("涨跌幅")))
                change_pct = float(raw_change)
                if abs(change_pct) > 1:
                    change_pct /= 100
            except (TypeError, ValueError):
                continue
            leader = str(row.get("f128") or row.get("leading_symbol") or "").strip() or None
            sectors.append(
                SectorMover(
                    name=name,
                    change_pct=change_pct,
                    leading_symbol=normalize_symbol(leader) if leader else None,
                    source=source,
                )
            )
        return sectors

    def _fetch_sector_rows(self, fs: str, fields: str) -> list[dict]:
        try:
            response = self.requester(
                "https://push2.eastmoney.com/api/qt/clist/get",
                params={
                    "pn": "1",
                    "pz": "100",
                    "po": "1",
                    "np": "1",
                    "ut": EASTMONEY_UT,
                    "fltt": "2",
                    "invt": "2",
                    "fid": "f3",
                    "fs": fs,
                    "fields": fields,
                },
                timeout=self.timeout,
                headers=EASTMONEY_HEADERS,
            )
            response.raise_for_status()
            return (((response.json() or {}).get("data") or {}).get("diff")) or []
        except Exception:
            return []

    def _fetch_live_breadth(self) -> MarketBreadth | None:
        try:
            response = self.requester(
                "https://82.push2.eastmoney.com/api/qt/clist/get",
                params={
                    "pn": "1",
                    "pz": "6000",
                    "po": "1",
                    "np": "1",
                    "ut": EASTMONEY_UT,
                    "fltt": "2",
                    "invt": "2",
                    "fid": "f12",
                    "fs": A_SHARE_BREADTH_FS,
                    "fields": A_SHARE_BREADTH_FIELDS,
                },
                timeout=self.timeout,
                headers=EASTMONEY_HEADERS,
            )
            response.raise_for_status()
            rows = (((response.json() or {}).get("data") or {}).get("diff")) or []
        except Exception:
            return None
        if not rows:
            return None
        up = 0
        down = 0
        flat = 0
        for row in rows:
            try:
                change_pct = float(row.get("f3", 0))
            except (TypeError, ValueError):
                continue
            if change_pct > 0:
                up += 1
            elif change_pct < 0:
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
            source="eastmoney-a-share-live",
        )

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
        for chunk in text.split("},"):
            if "name:" not in chunk or "changepercent:" not in chunk:
                continue
            try:
                name = chunk.split("name:", 1)[1].split(",", 1)[0].strip("'\" ")
                pct_text = chunk.split("changepercent:", 1)[1].split(",", 1)[0].strip("'\" ")
                leader = ""
                if "symbol:" in chunk:
                    leader = chunk.split("symbol:", 1)[1].split(",", 1)[0].strip("'\" ")
                rows.append({"name": name, "change_pct": pct_text, "leading_symbol": leader})
            except Exception:
                continue
        return self._parse_sector_rows(rows, "sina-sector")

    def _snapshot_from_local(self, now: datetime) -> RealtimeMarketSnapshot:
        try:
            bars = self.warehouse.read_latest_daily_bars(days=3)
        except Exception as exc:
            return RealtimeMarketSnapshot(
                status="unavailable",
                source="local",
                updated_at=now,
                message=f"实时行情不可用，本地数据读取失败：{exc}",
            )
        if bars.empty:
            return RealtimeMarketSnapshot(
                status="unavailable",
                source="local",
                updated_at=now,
                message="实时行情不可用，本地历史数据为空。",
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
            indexes=[pseudo_index],
            breadth=breadth,
            strong_sectors=local_sectors,
            yesterday_strong_sectors=yesterday_sectors,
            message=message,
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
        if latest.empty or not self._last_live_sector_rows:
            return []
        rows: list[SectorMover] = []
        data = latest.copy()
        data["symbol"] = data["symbol"].astype(str).map(normalize_symbol)
        for board in self._last_live_sector_rows[:20]:
            board_code = str(board.get("f12") or "").strip()
            board_name = str(board.get("f14") or "").strip()
            if not board_code or not board_name:
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
        try:
            response = self.requester(
                "https://29.push2.eastmoney.com/api/qt/clist/get",
                params={
                    "pn": "1",
                    "pz": "500",
                    "po": "1",
                    "np": "1",
                    "ut": EASTMONEY_UT,
                    "fltt": "2",
                    "invt": "2",
                    "fid": "f12",
                    "fs": f"b:{board_code}+f:!50",
                    "fields": "f12",
                },
                timeout=self.timeout,
                headers=EASTMONEY_HEADERS,
            )
            response.raise_for_status()
            diff = (((response.json() or {}).get("data") or {}).get("diff")) or []
            members = [
                normalize_symbol(str(item.get("f12")).strip())
                for item in diff
                if str(item.get("f12") or "").strip()
            ]
        except Exception:
            members = []
        self._sector_member_cache[board_code] = members
        return members
