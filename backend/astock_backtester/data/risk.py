from __future__ import annotations

import re
from importlib import resources
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import pandas as pd
import requests

from astock_backtester.data.providers import normalize_symbol
from astock_backtester.data.warehouse import Warehouse
from astock_backtester.models import RiskAlertItem, RiskAlertsResponse


_SINA_SIMPLE_QUOTE_RE = re.compile(r'hq_str_s_(?:sh|sz|bj)(?P<symbol>\d{6})="(?P<body>[^"]*)"')


def _severity_from_risk(risk_type: str, detail: str) -> str:
    text = f"{risk_type} {detail}"
    if "退市" in text or "净资产为负" in text or "低于1元" in text or "市值风险" in text:
        return "high"
    if "审计" in text or "信息披露" in text or "违规" in text:
        return "medium"
    return "low"


def _potential_risk_reason(risk_type: str, detail: str) -> str:
    detail = detail.strip() or "潜在 ST 或退市风险"
    if "信息披露违规" in detail:
        explanation = "涉及信息披露违规线索，后续监管处罚、整改进度或审计意见变化都可能触发特别处理。"
    elif "年报审计风险" in detail:
        explanation = "年报审计存在不确定性，需要重点跟踪审计意见类型、持续经营能力和财务报表调整。"
    elif "营收利润不达标" in detail:
        explanation = "已被 *ST 后下一年度营收或利润指标若继续不达标，存在进一步退市风险。"
    elif "净资产为负" in detail:
        explanation = "净资产为负属于财务类退市风险高敏感项，需要跟踪最近一期净资产修复情况。"
    elif "低于1元" in detail:
        explanation = "股价连续低于面值可能触发交易类退市，需要跟踪连续交易日计数和交易所公告。"
    elif "市值风险退市" in detail:
        explanation = "总市值长期低于交易所阈值可能触发交易类退市，需要跟踪连续交易日计数和市值修复。"
    else:
        explanation = "该风险来自本地潜在风险观察名单，需要结合公告、财报和交易所问询持续复核。"
    return f"{risk_type}：{detail}。{explanation}本条来自潜在 ST 风险观察名单，不等同于已经 ST。"


def _risk_from_name(symbol: str, name: str, source: str, now: datetime) -> RiskAlertItem | None:
    text = name.upper()
    if "退" in name:
        return RiskAlertItem(
            symbol=symbol,
            name=name,
            risk_type="退市风险",
            reason="股票名称包含退市或退市整理特征，需要排查交易权限、流动性和终止上市进展。",
            severity="high",
            source=source,
            detected_at=now,
        )
    if "*ST" in text or "ST" in text:
        return RiskAlertItem(
            symbol=symbol,
            name=name,
            risk_type="ST风险",
            reason="股票名称包含 ST 或 *ST，存在退市风险警示或其他特别处理风险。",
            severity="high" if "*ST" in text else "medium",
            source=source,
            detected_at=now,
        )
    return None


@dataclass
class RiskAlertProvider:
    warehouse: Warehouse
    timeout: float = 1.5
    requester: Callable[..., requests.Response] = requests.get
    adata_loader: Callable[[], pd.DataFrame] | None = None
    include_packaged_watchlist: bool = True

    def current_alerts(self) -> RiskAlertsResponse:
        now = datetime.now(timezone.utc)
        diagnostics: list[str] = []
        watchlist_items, watchlist_diagnostics = self._alerts_from_local_watchlist(now)
        diagnostics.extend(watchlist_diagnostics)
        local_items, local_diagnostics = self._alerts_from_local(now)
        diagnostics.extend(local_diagnostics)
        sina_items, sina_diagnostics = self._alerts_from_sina_local_symbols(now)
        diagnostics.extend(sina_diagnostics)
        eastmoney_items, eastmoney_diagnostics = self._alerts_from_eastmoney(now)
        diagnostics.extend(eastmoney_diagnostics)
        if watchlist_items:
            adata_items = []
        elif eastmoney_items or sina_items:
            adata_items: list[RiskAlertItem] = []
        else:
            adata_items, adata_diagnostics = self._alerts_from_adata_all_codes_with_timeout(now)
            diagnostics.extend(adata_diagnostics)

        items: list[RiskAlertItem] = []
        seen: set[str] = set()
        source_items = watchlist_items if watchlist_items else [*eastmoney_items, *sina_items, *adata_items, *local_items]
        if watchlist_items:
            live_symbols = {item.symbol for item in [*eastmoney_items, *sina_items]}
            watchlist_symbols = {item.symbol for item in watchlist_items}
            new_live_symbols = sorted(live_symbols - watchlist_symbols)
            source_items = [
                *watchlist_items,
                *[item for item in [*eastmoney_items, *sina_items] if item.symbol in new_live_symbols],
            ]
            if new_live_symbols:
                diagnostics.append(
                    f"实时名称扫描发现 {len(new_live_symbols)} 只名单外已 ST 或退市股票，"
                    "已追加到风险清单末尾。"
                )
            else:
                diagnostics.append("实时扫描未发现新增已 ST、*ST 或退市名称变化。")
        for item in source_items:
            if item.symbol not in seen:
                items.append(item)
                seen.add(item.symbol)
        if not items and not diagnostics:
            diagnostics.append("当前东方财富与本地数据均未识别到 ST、*ST 或退市整理股票。")
        return RiskAlertsResponse(
            updated_at=now,
            source=self._source_label(items),
            items=items,
            diagnostics=diagnostics,
        )

    def _source_label(self, items: list[RiskAlertItem]) -> str:
        sources = []
        for source in ("local-watchlist", "eastmoney", "sina", "adata", "local"):
            if any(item.source == source for item in items):
                sources.append(source)
        return "+".join(sources) if sources else "local"

    def _watchlist_paths(self) -> list[object]:
        paths: list[object] = [self.warehouse.cache_root / "potential_risk_watchlist.csv"]
        if self.include_packaged_watchlist:
            try:
                paths.append(resources.files("astock_backtester.data").joinpath("potential_risk_watchlist.csv"))
            except Exception:
                pass
        return paths

    def _read_watchlist_frame(self) -> pd.DataFrame:
        for path in self._watchlist_paths():
            try:
                if hasattr(path, "exists") and not path.exists():
                    continue
                frame = pd.read_csv(path, dtype=str).fillna("")
            except Exception:
                continue
            if not frame.empty:
                return frame
        return pd.DataFrame()

    def _alerts_from_local_watchlist(self, now: datetime) -> tuple[list[RiskAlertItem], list[str]]:
        frame = self._read_watchlist_frame()
        if frame.empty:
            return [], ["本地潜在风险观察名单为空，暂时只能使用实时名称源识别已 ST 风险。"]

        columns = {str(column).strip(): column for column in frame.columns}
        name_column = columns.get("name") or columns.get("股票名称")
        symbol_column = columns.get("symbol") or columns.get("股票代码") or columns.get("code")
        risk_column = columns.get("risk_type") or columns.get("预警类别")
        detail_column = columns.get("detail") or columns.get("细分类别") or columns.get("reason")
        if not name_column or not symbol_column:
            return [], ["本地潜在风险观察名单缺少股票名称或代码字段。"]

        grouped: dict[str, dict[str, object]] = {}
        for _, row in frame.iterrows():
            symbol = normalize_symbol(str(row.get(symbol_column, "")))
            name = str(row.get(name_column, "")).strip()
            if not symbol or not name:
                continue
            risk_type = str(row.get(risk_column, "ST预警") if risk_column else "ST预警").strip() or "ST预警"
            detail = str(row.get(detail_column, "") if detail_column else "").strip()
            current = grouped.setdefault(
                symbol,
                {
                    "name": name,
                    "risk_types": [],
                    "details": [],
                },
            )
            if risk_type not in current["risk_types"]:
                current["risk_types"].append(risk_type)
            if detail and detail not in current["details"]:
                current["details"].append(detail)

        alerts: list[RiskAlertItem] = []
        for symbol, data in grouped.items():
            risk_type = " / ".join(data["risk_types"]) if data["risk_types"] else "ST预警"
            detail = "；".join(data["details"]) if data["details"] else "潜在 ST 或退市风险"
            alerts.append(
                RiskAlertItem(
                    symbol=symbol,
                    name=str(data["name"]),
                    risk_type=risk_type,
                    reason=_potential_risk_reason(risk_type, detail),
                    severity=_severity_from_risk(risk_type, detail),
                    source="local-watchlist",
                    detected_at=now,
                )
            )

        diagnostics = [f"已加载本地潜在风险观察名单 {len(alerts)} 只，打开软件时会同步执行实时名称扫描用于发现变化。"]
        return alerts, diagnostics

    def _load_adata_all_codes(self) -> pd.DataFrame:
        if self.adata_loader is not None:
            return self.adata_loader()
        import adata

        frame = adata.stock.info.all_code()
        return pd.DataFrame() if frame is None else frame

    def _alerts_from_adata_all_codes_with_timeout(self, now: datetime) -> tuple[list[RiskAlertItem], list[str]]:
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self._alerts_from_adata_all_codes, now)
        try:
            result = future.result(timeout=self.timeout)
            executor.shutdown(wait=False, cancel_futures=True)
            return result
        except FutureTimeoutError:
            future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            return [], ["AData 全市场风险名单读取超时，已先使用东方财富与本地风险源。"]

    def _alerts_from_adata_all_codes(self, now: datetime) -> tuple[list[RiskAlertItem], list[str]]:
        try:
            frame = self._load_adata_all_codes()
        except Exception as exc:
            return [], [f"AData 全市场风险名单读取失败：{exc}"]
        if frame.empty:
            return [], ["AData 全市场股票名单为空，无法识别 ST 或退市风险。"]

        code_column = next((column for column in ["stock_code", "code", "symbol"] if column in frame.columns), None)
        name_column = next(
            (column for column in ["short_name", "stock_name", "name", "display_name"] if column in frame.columns),
            None,
        )
        if code_column is None or name_column is None:
            return [], ["AData 全市场股票名单缺少代码或名称字段，无法识别 ST 或退市风险。"]

        alerts: list[RiskAlertItem] = []
        for _, row in frame[[code_column, name_column]].dropna().iterrows():
            symbol = normalize_symbol(str(row[code_column]))
            name = str(row[name_column]).strip()
            if not symbol or not name:
                continue
            alert = _risk_from_name(symbol, name, "adata", now)
            if alert:
                alerts.append(alert)
        diagnostics = [] if alerts else ["AData 全市场股票名单当前未识别到 ST、*ST 或退市整理股票。"]
        return alerts, diagnostics

    def _alerts_from_eastmoney(self, now: datetime) -> tuple[list[RiskAlertItem], list[str]]:
        try:
            response = self.requester(
                "https://push2.eastmoney.com/api/qt/clist/get",
                params={
                    "pn": "1",
                    "pz": "5000",
                    "po": "1",
                    "np": "1",
                    "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                    "fltt": "2",
                    "invt": "2",
                    "fid": "f3",
                    "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
                    "fields": "f12,f14",
                },
                timeout=self.timeout,
                headers={"Referer": "https://quote.eastmoney.com/"},
            )
            response.raise_for_status()
            rows = (((response.json() or {}).get("data") or {}).get("diff")) or []
        except Exception:
            return [], ["东方财富风险源不可用，已使用本地 ST 字段兜底。"]

        alerts: list[RiskAlertItem] = []
        for row in rows:
            symbol = normalize_symbol(str(row.get("f12") or ""))
            name = str(row.get("f14") or "").strip()
            if not symbol or not name:
                continue
            alert = _risk_from_name(symbol, name, "eastmoney", now)
            if alert:
                alerts.append(alert)
        diagnostics = [] if alerts else ["东方财富风险源当前未返回 ST、*ST 或退市整理股票。"]
        return alerts, diagnostics

    def _load_local_symbol_codes(self) -> list[str]:
        symbols: list[str] = []
        seen: set[str] = set()
        for filename in ("symbols.full.csv", "symbols.csv"):
            path = self.warehouse.cache_root / filename
            if not path.exists():
                continue
            try:
                frame = pd.read_csv(path, dtype=str)
            except Exception:
                continue
            code_column = next(
                (column for column in ["symbol", "stock_code", "code"] if column in frame.columns),
                None,
            )
            if code_column is None:
                continue
            for value in frame[code_column].dropna():
                symbol = normalize_symbol(str(value))
                if symbol and symbol not in seen:
                    symbols.append(symbol)
                    seen.add(symbol)
            if symbols:
                return symbols
        try:
            latest = self.warehouse.read_latest_daily_bars(days=1)
        except Exception:
            return symbols
        if latest.empty or "symbol" not in latest.columns:
            return symbols
        for value in latest["symbol"].dropna():
            symbol = normalize_symbol(str(value))
            if symbol and symbol not in seen:
                symbols.append(symbol)
                seen.add(symbol)
        return symbols

    def _sina_symbol(self, symbol: str) -> str | None:
        code = normalize_symbol(symbol)
        if not code:
            return None
        if code.startswith(("6", "9")):
            return f"s_sh{code}"
        if code.startswith(("0", "2", "3")):
            return f"s_sz{code}"
        if code.startswith(("4", "8")):
            return f"s_bj{code}"
        return None

    def _alerts_from_sina_local_symbols(self, now: datetime) -> tuple[list[RiskAlertItem], list[str]]:
        symbols = self._load_local_symbol_codes()
        if not symbols:
            return [], ["本地全市场代码表不存在，无法调用新浪实时名称风险源。"]

        sina_symbols = [value for symbol in symbols if (value := self._sina_symbol(symbol))]
        if not sina_symbols:
            return [], ["本地全市场代码表没有可识别的沪深北代码，无法调用新浪实时名称风险源。"]

        alerts: list[RiskAlertItem] = []
        diagnostics: list[str] = []
        for start in range(0, len(sina_symbols), 400):
            batch = sina_symbols[start : start + 400]
            try:
                response = self.requester(
                    "https://hq.sinajs.cn/list=" + ",".join(batch),
                    timeout=self.timeout,
                    headers={
                        "Referer": "https://finance.sina.com.cn/",
                        "User-Agent": "Mozilla/5.0",
                    },
                )
                response.raise_for_status()
                raw_content = getattr(response, "content", b"")
                if raw_content:
                    text = raw_content.decode("gbk", errors="ignore")
                else:
                    text = getattr(response, "text", "")
            except Exception as exc:
                diagnostics.append(f"新浪实时名称风险源不可用：{exc}")
                break

            for match in _SINA_SIMPLE_QUOTE_RE.finditer(text):
                symbol = normalize_symbol(match.group("symbol"))
                name = match.group("body").split(",", 1)[0].strip()
                if not symbol or not name:
                    continue
                alert = _risk_from_name(symbol, name, "sina", now)
                if alert:
                    alerts.append(alert)

        if not alerts and not diagnostics:
            diagnostics.append("新浪实时名称风险源当前未识别到 ST、*ST 或退市整理股票。")
        return alerts, diagnostics

    def _alerts_from_local(self, now: datetime) -> tuple[list[RiskAlertItem], list[str]]:
        try:
            bars = self.warehouse.read_latest_daily_bars(days=1)
        except Exception as exc:
            return [], [f"本地风险兜底读取失败：{exc}"]
        if bars.empty:
            return [], ["本地最近日线数据为空，无法用 ST 字段兜底。"]

        frame = bars.copy()
        alerts: list[RiskAlertItem] = []
        diagnostics: list[str] = []
        if "name" in frame.columns or "stock_name" in frame.columns:
            name_column = "name" if "name" in frame.columns else "stock_name"
            latest = frame.sort_values("trade_date").drop_duplicates("symbol", keep="last")
            for _, row in latest.iterrows():
                alert = _risk_from_name(str(row["symbol"]), str(row[name_column]), "local", now)
                if alert:
                    alerts.append(alert)
        else:
            diagnostics.append("本地日线缺少股票名称字段，无法从名称识别 ST 或退市风险。")
        if "is_st" in frame.columns:
            latest = frame.sort_values("trade_date").drop_duplicates("symbol", keep="last")
            st_rows = latest[latest["is_st"].fillna(False).astype(bool)]
            existing = {item.symbol for item in alerts}
            for _, row in st_rows.iterrows():
                symbol = str(row["symbol"])
                if symbol in existing:
                    continue
                alerts.append(
                    RiskAlertItem(
                        symbol=symbol,
                        name=symbol,
                        risk_type="ST风险",
                        reason="本地行情字段 is_st 为 true，回测时默认应过滤这类股票。",
                        severity="medium",
                        source="local",
                        detected_at=now,
                    )
                )
        else:
            diagnostics.append("本地日线缺少 is_st 字段，无法用 ST 标记兜底。")
        if not alerts:
            diagnostics.append("本地最近日线未识别到 ST、*ST 或退市整理股票。")
        return alerts, diagnostics
