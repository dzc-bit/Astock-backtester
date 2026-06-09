from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable

import requests

from astock_backtester.data.cls import CLS_QUOTE_BASE_URL, CLS_SITE_BASE_URL, cls_request_json
from astock_backtester.data.providers import normalize_symbol
from astock_backtester.data.realtime import _breadth_from_cls_distribution, _normalize_change_pct, _parse_float, _parse_int
from astock_backtester.models import (
    ClsFinanceAnchor,
    ClsFinanceEmotion,
    ClsFinancePlate,
    ClsFinancePoolItem,
    ClsFinanceResponse,
    ClsFinanceTlinePoint,
)


CLS_FINANCE_URL = "https://www.cls.cn/finance"
CLS_TLINE_URL = f"{CLS_QUOTE_BASE_URL}/quote/index/tline"
CLS_INDEX_BASIC_URL = f"{CLS_QUOTE_BASE_URL}/quote/index/basic"
CLS_STOCK_EMOTION_URL = f"{CLS_QUOTE_BASE_URL}/v2/quote/a/stock/emotion"
CLS_UP_DOWN_ANALYSIS_URL = f"{CLS_QUOTE_BASE_URL}/quote/index/up_down_analysis"
CLS_TRANSACTION_ANCHOR_URL = f"{CLS_SITE_BASE_URL}/v3/transaction/anchor"


@dataclass
class ClsFinanceProvider:
    requester: Callable[..., requests.Response] = requests.get
    timeout: float = 5.0

    def current_board(self) -> ClsFinanceResponse:
        diagnostics: list[str] = []
        today = date.today().isoformat()
        tline = self._read_tline(diagnostics)
        anchors = self._read_anchors(today, diagnostics)
        preclose_px = self._read_preclose(diagnostics)
        emotion = self._read_emotion(diagnostics)
        up_pool = self._read_up_pool(diagnostics)
        return ClsFinanceResponse(
            updated_at=datetime.now(timezone.utc),
            source="cls-finance",
            source_url=CLS_FINANCE_URL,
            preclose_px=preclose_px,
            tline=tline,
            anchors=anchors,
            emotion=emotion,
            up_pool=up_pool,
            diagnostics=diagnostics,
        )

    def _read_tline(self, diagnostics: list[str]) -> list[ClsFinanceTlinePoint]:
        try:
            payload = cls_request_json(self.requester, CLS_TLINE_URL, timeout=self.timeout)
        except Exception as exc:
            diagnostics.append(f"财联社分时线读取失败：{exc}")
            return []
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            return []
        points: list[ClsFinanceTlinePoint] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            minute = _parse_int(row.get("minute"))
            last_px = _parse_float(row.get("last_px"))
            if minute is None or last_px is None:
                continue
            points.append(
                ClsFinanceTlinePoint(
                    date=_parse_int(row.get("date")),
                    minute=minute,
                    last_px=last_px,
                    change=_normalize_change_pct(row.get("change")),
                )
            )
        return points

    def _read_anchors(self, cdate: str, diagnostics: list[str]) -> list[ClsFinanceAnchor]:
        try:
            payload = cls_request_json(
                self.requester,
                CLS_TRANSACTION_ANCHOR_URL,
                params={"cdate": cdate},
                timeout=self.timeout,
            )
        except Exception as exc:
            diagnostics.append(f"财联社盘面锚点读取失败：{exc}")
            return []
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            return []
        anchors: list[ClsFinanceAnchor] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = str(row.get("symbol_code") or "").strip()
            name = str(row.get("symbol_name") or "").strip()
            if not code or not name:
                continue
            direction = str(row.get("float") or "flat").strip()
            if direction not in {"up", "down"}:
                direction = "flat"
            anchors.append(
                ClsFinanceAnchor(
                    code=code,
                    name=name,
                    article_id=_parse_int(row.get("article_id")),
                    c_time=str(row.get("c_time") or "").strip() or None,
                    direction=direction,
                    url=f"https://www.cls.cn/plate?code={code}" if code.startswith("cls") else None,
                )
            )
        return anchors

    def _read_preclose(self, diagnostics: list[str]) -> float | None:
        try:
            payload = cls_request_json(
                self.requester,
                CLS_INDEX_BASIC_URL,
                params={"secu_code": "sh000001", "fields": "preclose_px"},
                timeout=self.timeout,
            )
        except Exception as exc:
            diagnostics.append(f"财联社指数昨收读取失败：{exc}")
            return None
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        return _parse_float(data.get("preclose_px")) if isinstance(data, dict) else None

    def _read_emotion(self, diagnostics: list[str]) -> ClsFinanceEmotion | None:
        try:
            payload = cls_request_json(self.requester, CLS_STOCK_EMOTION_URL, timeout=self.timeout)
        except Exception as exc:
            diagnostics.append(f"财联社市场热度读取失败：{exc}")
            return None
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        if not isinstance(data, dict):
            return None
        breadth = _breadth_from_cls_distribution(data.get("up_down_dis", {}))
        if breadth is not None:
            breadth.source = "cls-finance-emotion"
        return ClsFinanceEmotion(
            market_degree=_parse_float(data.get("market_degree")),
            shsz_balance=str(data.get("shsz_balance") or "").strip() or None,
            shsz_balance_change=str(data.get("shsz_balance_change_px") or "").strip() or None,
            breadth=breadth,
            up_limit=_parse_int(data.get("up_ratio_num")),
            open_limit=_parse_int(data.get("up_open_num")),
            performance=str(data.get("performance") or "").strip() or None,
        )

    def _read_up_pool(self, diagnostics: list[str]) -> list[ClsFinancePoolItem]:
        try:
            payload = cls_request_json(
                self.requester,
                CLS_UP_DOWN_ANALYSIS_URL,
                params={"type": "up_pool", "way": "last_px", "rever": 1},
                timeout=self.timeout,
            )
        except Exception as exc:
            diagnostics.append(f"财联社涨停池读取失败：{exc}")
            return []
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            return []
        items: list[ClsFinancePoolItem] = []
        for row in rows[:20]:
            if not isinstance(row, dict):
                continue
            symbol = normalize_symbol(str(row.get("secu_code") or ""))
            name = str(row.get("secu_name") or "").strip()
            if not symbol or not name:
                continue
            plates: list[ClsFinancePlate] = []
            for plate in row.get("plate") or []:
                if not isinstance(plate, dict):
                    continue
                plate_code = str(plate.get("secu_code") or "").strip()
                plate_name = str(plate.get("secu_name") or "").strip()
                if plate_code and plate_name:
                    plates.append(
                        ClsFinancePlate(
                            code=plate_code,
                            name=plate_name,
                            change_pct=_normalize_change_pct(plate.get("change")),
                        )
                    )
            items.append(
                ClsFinancePoolItem(
                    symbol=symbol,
                    name=name,
                    change_pct=_normalize_change_pct(row.get("change")),
                    last=_parse_float(row.get("last_px")),
                    time=str(row.get("time") or "").strip() or None,
                    reason=str(row.get("up_reason") or "").strip() or None,
                    limit_up_days=_parse_int(row.get("limit_up_days")),
                    plates=plates,
                )
            )
        return items
