from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests
from bs4 import BeautifulSoup

from astock_backtester.data.cls import CLS_QUOTE_BASE_URL, CLS_SITE_BASE_URL, cls_request_json
from astock_backtester.data.providers import normalize_symbol
from astock_backtester.data.realtime import (
    THS_HEADERS,
    THS_MARKET_SUMMARY_URL,
    _breadth_from_cls_distribution,
    _normalize_change_pct,
    _parse_float,
    _parse_int,
)
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
THS_MARKET_DEGREE_SOURCE = "ths-market-summary"
THS_MARKET_DEGREE_LABEL = "同花顺大盘评级"
CLS_MARKET_DEGREE_SOURCE = "cls-finance-emotion"
CLS_MARKET_DEGREE_LABEL = "财联社市场热度"
THS_MARKET_BOARD_URL = "http://q.10jqka.com.cn/index/index/board"
THS_CHAMELEON_URL = "https://s.thsi.cn/js/chameleon/chameleon.1.7.min.1781803.js"
THS_MARKET_INDEXFLASH_URLS = (
    "http://q.10jqka.com.cn/api.php?t=indexflash&",
    "https://q.10jqka.com.cn/api.php?t=indexflash&",
)
THS_MARKET_DEGREE_URLS = (*THS_MARKET_INDEXFLASH_URLS, THS_MARKET_BOARD_URL, THS_MARKET_SUMMARY_URL)
THS_MARKET_SCORE_HEADERS = {
    **THS_HEADERS,
    "Accept": "*/*",
    "Referer": THS_MARKET_BOARD_URL,
}
THS_MARKET_DPPJ_RE = re.compile(
    r"""["']?dppj_data["']?\s*[:=]\s*["']?([0-9]{1,3}(?:\.[0-9]+)?)""",
    re.IGNORECASE,
)
THS_MARKET_DEGREE_RE = re.compile(
    r"(?:大盘评分|大盘评级|市场评分|market[_-]?degree|market[_-]?score|score)"
    r"[^0-9]{0,24}([0-9]{1,3}(?:\.[0-9]+)?)",
    re.IGNORECASE,
)


@dataclass
class ClsFinanceProvider:
    requester: Callable[..., requests.Response] = requests.get
    timeout: float = 5.0
    browser_cookie_getter: Callable[[], str | None] | None = None

    def current_board(self) -> ClsFinanceResponse:
        diagnostics: list[str] = []
        today = date.today().isoformat()
        tline = self._read_tline(diagnostics)
        anchors = self._read_anchors(today, diagnostics)
        preclose_px = self._read_preclose(diagnostics)
        emotion = self._read_emotion(diagnostics)
        ths_market_degree = self._read_ths_market_degree(diagnostics)
        emotion = self._with_market_degree_source(emotion, ths_market_degree)
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
        market_degree = _parse_float(data.get("market_degree"))
        return ClsFinanceEmotion(
            market_degree=market_degree,
            market_degree_source=CLS_MARKET_DEGREE_SOURCE if market_degree is not None else None,
            market_degree_label=CLS_MARKET_DEGREE_LABEL if market_degree is not None else None,
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

    def _read_ths_market_degree(self, diagnostics: list[str]) -> float | None:
        errors: list[str] = []
        browser_cookie: str | None = None
        browser_cookie_read = False
        for url in THS_MARKET_DEGREE_URLS:
            headers = dict(THS_MARKET_SCORE_HEADERS)
            if url in THS_MARKET_INDEXFLASH_URLS:
                if not browser_cookie_read:
                    browser_cookie_read = True
                    try:
                        getter = self.browser_cookie_getter or _read_ths_browser_cookie
                        browser_cookie = getter()
                    except Exception as exc:
                        errors.append(f"同花顺浏览器校验读取失败：{exc}")
                if browser_cookie:
                    headers["Cookie"] = browser_cookie
            try:
                response = self.requester(
                    url,
                    timeout=min(self.timeout, 3.0),
                    headers=headers,
                )
                response.raise_for_status()
            except Exception as exc:
                errors.append(f"{url}: {exc}")
                continue
            response.encoding = response.encoding or "gbk"
            text = response.text
            visible_text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
            degree = _parse_ths_market_degree(text)
            if degree is None:
                degree = _parse_ths_market_degree_visible_text(visible_text)
            if degree is None:
                errors.append(f"{url}: 页面未包含可解析的大盘评分")
                continue
            diagnostics.append(f"同花顺大盘评分读取成功：{degree:.1f}")
            return degree
        diagnostics.append(f"同花顺大盘评分读取失败：{'; '.join(errors[:4])}")
        return None

    def _with_market_degree_source(
        self,
        emotion: ClsFinanceEmotion | None,
        ths_market_degree: float | None,
    ) -> ClsFinanceEmotion | None:
        if emotion is None and ths_market_degree is None:
            return None
        if emotion is None:
            emotion = ClsFinanceEmotion()
        if ths_market_degree is not None:
            emotion.market_degree = ths_market_degree
            emotion.market_degree_source = THS_MARKET_DEGREE_SOURCE
            emotion.market_degree_label = THS_MARKET_DEGREE_LABEL
        elif emotion.market_degree is not None and not emotion.market_degree_source:
            emotion.market_degree_source = CLS_MARKET_DEGREE_SOURCE
            emotion.market_degree_label = CLS_MARKET_DEGREE_LABEL
        return emotion


def _parse_ths_market_degree(text: str) -> float | None:
    if not text:
        return None
    payload_degree = _parse_ths_market_degree_payload(text)
    if payload_degree is not None:
        return payload_degree
    for match in THS_MARKET_DPPJ_RE.finditer(text):
        value = _normalize_ths_market_degree(match.group(1))
        if value is not None:
            return value
    return None


def _parse_ths_market_degree_visible_text(text: str) -> float | None:
    if not text:
        return None
    for match in THS_MARKET_DEGREE_RE.finditer(text):
        value = _normalize_ths_market_degree(match.group(1))
        if value is not None:
            return value
    return None


def _parse_ths_market_degree_payload(text: str) -> float | None:
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.startswith("(") and stripped.endswith(")"):
        stripped = stripped[1:-1].strip()
    try:
        payload = json.loads(stripped)
    except (TypeError, ValueError):
        return None
    return _market_degree_from_payload(payload)


def _market_degree_from_payload(payload: Any) -> float | None:
    if isinstance(payload, dict):
        for key in ("dppj_data", "market_degree", "market_score", "score"):
            if key in payload:
                value = _normalize_ths_market_degree(payload.get(key))
                if value is not None:
                    return value
        for value in payload.values():
            nested = _market_degree_from_payload(value)
            if nested is not None:
                return nested
    if isinstance(payload, list):
        for item in payload:
            nested = _market_degree_from_payload(item)
            if nested is not None:
                return nested
    return None


def _normalize_ths_market_degree(value: object) -> float | None:
    parsed = _parse_float(value)
    if parsed is None or parsed < 0:
        return None
    if parsed <= 10:
        return parsed
    if parsed <= 100:
        return parsed / 10
    return None


def _read_ths_browser_cookie() -> str | None:
    node = _resolve_node_executable()
    if node is None:
        return None
    worker = _resolve_ths_cookie_worker()
    try:
        if worker is not None:
            completed = subprocess.run(
                [node, str(worker)],
                cwd=worker.parent,
                check=False,
                capture_output=True,
                text=True,
                timeout=8,
            )
        else:
            script = _ths_browser_cookie_script()
            completed = subprocess.run(
                [node, "-e", script],
                cwd=_project_root(),
                check=False,
                capture_output=True,
                text=True,
                timeout=8,
            )
    except Exception:
        return None
    cookie = completed.stdout.strip()
    if completed.returncode != 0 or "v=" not in cookie:
        return None
    return cookie


def _sidecar_runtime_dir() -> Path | None:
    if getattr(sys, "frozen", False):
        try:
            return Path(sys.executable).resolve().parent
        except OSError:
            return None
    return None


def _resolve_ths_cookie_worker() -> Path | None:
    candidates: list[Path] = []
    sidecar_dir = _sidecar_runtime_dir()
    if sidecar_dir is not None:
        candidates.append(sidecar_dir / "ths-cookie-worker.cjs")
    candidates.append(_project_root() / "src-tauri" / "bin" / "ths-cookie-worker.cjs")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _resolve_node_executable() -> str | None:
    candidates: list[Path] = []
    sidecar_dir = _sidecar_runtime_dir()
    if sidecar_dir is not None:
        candidates.append(sidecar_dir / "node.exe")
    candidates.extend(
        [
            _project_root() / "src-tauri" / "bin" / "node.exe",
            _project_root() / ".tools" / "node-v20.18.1-win-x64" / "node.exe",
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return shutil.which("node")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _ths_browser_cookie_script() -> str:
    return f"""
const {{ JSDOM, VirtualConsole }} = require("jsdom");

(async () => {{
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("error", () => {{}});
  virtualConsole.on("warn", () => {{}});
  const dom = new JSDOM(
    "<!doctype html><html><head><script src=\\"{THS_CHAMELEON_URL}\\"></script></head><body></body></html>",
    {{
      url: "{THS_MARKET_BOARD_URL}",
      resources: "usable",
      runScripts: "dangerously",
      pretendToBeVisual: true,
      virtualConsole,
      userAgent: "Mozilla/5.0"
    }}
  );
  await new Promise((resolve) => setTimeout(resolve, 3000));
  const cookie = dom.window.document.cookie || "";
  dom.window.close();
  process.stdout.write(cookie);
}})().catch(() => process.exit(1));
"""
