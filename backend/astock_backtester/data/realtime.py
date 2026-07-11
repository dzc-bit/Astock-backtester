from __future__ import annotations

import json
import re
import time as monotonic_time
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import Event, Lock
from typing import Any, Callable, Iterable

import pandas as pd
import requests
from bs4 import BeautifulSoup

from astock_backtester.data.cls import cls_request_json
from astock_backtester.data.http_transport import resilient_get, should_allow_alternate_transport
from astock_backtester.data.providers import normalize_symbol
from astock_backtester.data.realtime_parsers import (
    CLS_HOT_PLATE_URL,
    CLS_QUOTE_HOME_URL,
    EASTMONEY_A_SPOT_URL,
    EASTMONEY_SECTOR_URLS,
    INDEXES,
    MIN_CONTROLLED_BACKUP_SECTOR_ROWS,
    SINA_BREADTH_BATCH_SIZE,
    SINA_HEADERS,
    TENCENT_QUOTE_URL,
    THS_BOARD_CODE_RE,
    THS_BREADTH_RE,
    THS_CONCEPT_SECTION_URL,
    THS_HEADERS,
    THS_HOT_TOPIC_HEADERS,
    THS_HOT_TOPIC_URL,
    THS_INDUSTRY_DETAIL_URL,
    THS_INDUSTRY_HTML_URL,
    THS_MARKET_SUMMARY_URL,
    THS_STOCK_CODE_RE,
    a_share_market_symbol,
    is_valid_full_market_breadth,
)
from astock_backtester.data.realtime_parsers import (
    aggregate_ths_hot_topic_rows as _aggregate_ths_hot_topic_rows,
)
from astock_backtester.data.realtime_parsers import (
    append_yesterday_sector_note as _append_yesterday_sector_note,
)
from astock_backtester.data.realtime_parsers import (
    breadth_from_cls_distribution as _breadth_from_cls_distribution,
)
from astock_backtester.data.realtime_parsers import (
    decode_sina_response as _decode_sina_response,
)
from astock_backtester.data.realtime_parsers import (
    dedupe_sectors as _dedupe_sectors,
)
from astock_backtester.data.realtime_parsers import (
    extract_code_from_href as _extract_code_from_href,
)
from astock_backtester.data.realtime_parsers import (
    is_renderable_snapshot as _is_renderable_snapshot,
)
from astock_backtester.data.realtime_parsers import (
    market_phase as _market_phase,
)
from astock_backtester.data.realtime_parsers import (
    normalize_sector_change_pct as _normalize_sector_change_pct,
)
from astock_backtester.data.realtime_parsers import (
    parse_float as _parse_float,
)
from astock_backtester.data.realtime_parsers import (
    parse_int as _parse_int,
)
from astock_backtester.data.realtime_parsers import (
    phase_diagnostic as _phase_diagnostic,
)
from astock_backtester.data.realtime_parsers import (
    quote_from_cls_home as _quote_from_cls_home,
)
from astock_backtester.data.realtime_parsers import (
    quote_from_sina as _quote_from_sina,
)
from astock_backtester.data.realtime_parsers import (
    sector_rows_from_cls_hot_plate as _sector_rows_from_cls_hot_plate,
)
from astock_backtester.data.realtime_parsers import (
    unique_sources as _unique_sources,
)
from astock_backtester.data.warehouse import Warehouse
from astock_backtester.models import (
    MarketBreadth,
    MarketIndexQuote,
    RealtimeMarketSnapshot,
    SectorMover,
)


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
class BrowserMarketProvider:
    timeout: float = 2.5

    def fetch_breadth_from_dom(self, url: str) -> MarketBreadth | None:
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            return None
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=int(self.timeout * 1000))
                text = page.locator("body").inner_text(timeout=int(self.timeout * 1000))
                browser.close()
        except Exception:
            return None
        match = THS_BREADTH_RE.search(text)
        if not match:
            return None
        up, down, flat = (int(item) for item in match.groups())
        return MarketBreadth(up=up, down=down, flat=flat, total=up + down + flat, source="browser-market-provider")


@dataclass
class HeavyMarketCrawlerProvider:
    requester: Callable[..., requests.Response] = requests.get
    timeout: float = 2.5
    browser_provider: BrowserMarketProvider | None = None
    _last_successful_breadth: MarketBreadth | None = field(default=None, init=False, repr=False)

    def fetch_breadth(self) -> MarketBreadth | None:
        # The provider instance is cached on ``RealtimeMarketProvider`` and can
        # be invoked from a worker thread that may already have timed out.  It
        # therefore must NOT retain any cross-request breadth state; every call
        # returns a value scoped to the caller and publishes nothing shared.
        for url in [
            THS_MARKET_SUMMARY_URL,
            "https://q.10jqka.com.cn/",
        ]:
            breadth = self._fetch_public_html_breadth(url)
            if breadth is not None:
                return breadth
        if self.browser_provider is not None:
            breadth = self.browser_provider.fetch_breadth_from_dom(THS_MARKET_SUMMARY_URL)
            if breadth is not None:
                return breadth
        return None

    def _fetch_public_html_breadth(self, url: str) -> MarketBreadth | None:
        try:
            response = self.requester(url, timeout=self.timeout, headers=THS_HEADERS)
            response.raise_for_status()
            response.encoding = response.encoding or "gbk"
        except Exception:
            return None
        text = BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)
        match = THS_BREADTH_RE.search(text)
        if not match:
            return None
        up, down, flat = (int(item) for item in match.groups())
        return MarketBreadth(up=up, down=down, flat=flat, total=up + down + flat, source="heavy-market-crawler")


@dataclass
class RealtimeMarketProvider:
    warehouse: Warehouse
    timeout: float = 4.0
    requester: Callable[..., requests.Response] = requests.get
    alternate_requester: Callable[..., Any] | None = None
    allow_alternate_transport: bool | None = None
    breadth_time_budget: float = 2.0
    breadth_source_timeout: float = 0.8
    sector_time_budget: float = 3.0
    sector_source_timeout: float = 0.8
    local_snapshot_time_budget: float = 2.0
    allow_eastmoney_breadth_fallback: bool = False
    _sector_member_cache: dict[str, list[str]] = field(default_factory=dict, init=False, repr=False)
    _last_successful_snapshot: RealtimeMarketSnapshot | None = field(default=None, init=False, repr=False)
    _state_lock: Lock = field(default_factory=Lock, init=False, repr=False)
    _heavy_market_provider: HeavyMarketCrawlerProvider | None = field(default=None, init=False, repr=False)
    # P1-4: monotonic generation counters to determine publication rights
    # without relying on wall-clock timestamps.
    _request_generation: int = field(default=0, init=False, repr=False)
    _last_snapshot_generation: int = field(default=0, init=False, repr=False)
    # Round-4: fixed-capacity single-flight executors.  Each provider slot
    # has its own 1-worker executor reused across requests.  An in-flight
    # lock prevents stacking concurrent work; a new request that finds the
    # slot busy returns None / empty immediately instead of creating yet
    # another thread.
    _breadth_executor: ThreadPoolExecutor | None = field(default=None, init=False, repr=False)
    _sector_executor: ThreadPoolExecutor | None = field(default=None, init=False, repr=False)
    _local_executor: ThreadPoolExecutor | None = field(default=None, init=False, repr=False)
    _breadth_in_flight: Lock = field(default_factory=Lock, init=False, repr=False)
    _sector_in_flight: Lock = field(default_factory=Lock, init=False, repr=False)
    _local_in_flight: Lock = field(default_factory=Lock, init=False, repr=False)

    def _get_breadth_executor(self) -> ThreadPoolExecutor:
        if self._breadth_executor is None:
            self._breadth_executor = ThreadPoolExecutor(max_workers=1)
        return self._breadth_executor

    def _get_sector_executor(self) -> ThreadPoolExecutor:
        if self._sector_executor is None:
            self._sector_executor = ThreadPoolExecutor(max_workers=1)
        return self._sector_executor

    def _get_local_executor(self) -> ThreadPoolExecutor:
        if self._local_executor is None:
            self._local_executor = ThreadPoolExecutor(max_workers=1)
        return self._local_executor

    def _next_request_generation(self) -> int:
        """Atomically increment and return a new request generation number."""
        with self._state_lock:
            self._request_generation += 1
            return self._request_generation

    def _remember_successful_snapshot(
        self,
        snapshot: RealtimeMarketSnapshot,
        *,
        generation: int | None = None,
    ) -> None:
        with self._state_lock:
            current = self._last_successful_snapshot
            if current is None:
                self._last_successful_snapshot = snapshot.model_copy(deep=True)
                if generation is not None:
                    self._last_snapshot_generation = generation
                return
            # P1-4: production always passes generation.  For mixed-mode
            # safety, compare BOTH generation and updated_at so a legacy
            # call with a newer wall-clock time can never clobber a
            # generation-tracked snapshot.  Example: gen=5 (no-generation
            # legacy) with t=10:05 must not overwrite gen=6 with t=10:00.
            if generation is not None:
                should_update = generation > self._last_snapshot_generation
            elif self._last_snapshot_generation > 0:
                # A generation-tracked snapshot is present — a legacy
                # (no-generation) call must never overwrite it, even
                # when the legacy call has a newer wall-clock timestamp.
                should_update = False
            else:
                should_update = snapshot.updated_at > current.updated_at
            if should_update:
                self._last_successful_snapshot = snapshot.model_copy(deep=True)
                if generation is not None:
                    self._last_snapshot_generation = generation

    def _retained_successful_snapshot(self) -> RealtimeMarketSnapshot | None:
        with self._state_lock:
            if self._last_successful_snapshot is None:
                return None
            return self._last_successful_snapshot.model_copy(deep=True)

    def market_snapshot(self) -> RealtimeMarketSnapshot:
        for event in self.market_snapshot_events():
            if event.get("type") == "result":
                snapshot = event.get("snapshot")
                if isinstance(snapshot, RealtimeMarketSnapshot):
                    return snapshot
        raise RuntimeError("Realtime market snapshot stream ended without a result.")

    def market_snapshot_events(self) -> Iterable[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        # P1-4: each request gets a monotonic generation so that late
        # arrivals cannot overwrite results from a newer request.
        request_generation = self._next_request_generation()
        phase = _market_phase(now)
        diagnostics: list[str] = []
        breadth_diagnostics: list[str] = []
        sector_diagnostics: list[str] = []
        phase_note = _phase_diagnostic(phase)
        if phase_note:
            diagnostics.append(phase_note)

        indexes: list[MarketIndexQuote] = []
        live_breadth: MarketBreadth | None = None
        live_sectors: list[SectorMover] = []
        live_sector_rows: list[dict] = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(self._fetch_indexes): "indexes",
                executor.submit(self._fetch_live_breadth_with_budget, breadth_diagnostics): "breadth",
                executor.submit(
                    self._fetch_live_sectors_with_budget,
                    sector_diagnostics,
                    live_sector_rows,
                ): "sectors",
            }
            for future in as_completed(futures):
                event_type = futures[future]
                try:
                    value = future.result()
                except Exception as exc:
                    diagnostics.append(f"实时行情{event_type}分块读取失败：{exc}")
                    value = [] if event_type != "breadth" else None
                if event_type == "indexes":
                    indexes = value
                    yield {
                        "type": "indexes",
                        "indexes": indexes,
                        "updated_at": now,
                        "market_phase": phase,
                        "diagnostics": list(diagnostics),
                    }
                elif event_type == "breadth":
                    live_breadth = value
                    yield {
                        "type": "breadth",
                        "breadth": live_breadth,
                        "updated_at": now,
                        "market_phase": phase,
                        "diagnostics": [*diagnostics, *breadth_diagnostics],
                    }
                else:
                    live_sectors = value
                    yield {
                        "type": "sectors",
                        "strong_sectors": live_sectors,
                        "updated_at": now,
                        "market_phase": phase,
                        "diagnostics": [*diagnostics, *sector_diagnostics],
                    }
        diagnostics.extend(breadth_diagnostics)
        diagnostics.extend(sector_diagnostics)
        has_live_context = bool(indexes and live_breadth and live_sectors)
        skip_local_topic_fetch = any(
            item.startswith(("实时强势题材接口超时", "实时强势题材接口失败"))
            for item in sector_diagnostics
        )
        local_snapshot = (
            None
            if has_live_context
            else self._snapshot_from_local_with_budget(
                now,
                diagnostics,
                live_sector_rows,
                skip_topic_fetch=skip_local_topic_fetch,
            )
        )
        strong_sectors = live_sectors or (local_snapshot.strong_sectors if local_snapshot else [])
        yesterday_sectors = local_snapshot.yesterday_strong_sectors if local_snapshot else []
        breadth = live_breadth or (local_snapshot.breadth if local_snapshot else None)
        if not live_breadth and breadth:
            yield {
                "type": "breadth",
                "breadth": breadth,
                "updated_at": now,
                "market_phase": phase,
                "diagnostics": list(diagnostics),
            }
        if not live_sectors and strong_sectors:
            yield {
                "type": "sectors",
                "strong_sectors": strong_sectors,
                "yesterday_strong_sectors": yesterday_sectors,
                "updated_at": now,
                "market_phase": phase,
                "diagnostics": list(diagnostics),
            }
        elif live_sectors:
            yield {
                "type": "sectors",
                "strong_sectors": strong_sectors,
                "yesterday_strong_sectors": yesterday_sectors,
                "updated_at": now,
                "market_phase": phase,
                "diagnostics": list(diagnostics),
            }
        has_partial_realtime_context = bool(indexes or live_breadth or live_sectors)
        status = "live" if has_live_context else ("stale" if has_partial_realtime_context else local_snapshot.status)
        if local_snapshot and not live_breadth and local_snapshot.diagnostics:
            diagnostics.extend(local_snapshot.diagnostics)
        if not indexes:
            diagnostics.append("实时指数接口暂不可用，尝试使用最近成功快照或本地最近交易日。")
        if local_snapshot and indexes and not live_breadth and local_snapshot.breadth:
            diagnostics.append("实时红绿家数接口暂不可用，已回退到本地最近交易日统计。")
        if local_snapshot and indexes and not live_breadth and local_snapshot.breadth is None:
            diagnostics.append("实时红绿家数接口暂不可用，本地最近交易日红绿宽度也不完整，已隐藏该宽度统计。")
        if local_snapshot and indexes and not live_sectors and local_snapshot.strong_sectors:
            diagnostics.append("实时强势题材接口暂不可用，已回退到本地最近交易日题材聚合。")
        source_parts: list[str] = []
        if indexes:
            source_parts.extend(_unique_sources(quote.source for quote in indexes))
        if live_breadth:
            source_parts.append(live_breadth.source)
        elif local_snapshot and local_snapshot.breadth:
            source_parts.append(local_snapshot.breadth.source)
        if live_sectors:
            source_parts.append(live_sectors[0].source)
        elif local_snapshot and local_snapshot.strong_sectors:
            source_parts.append(local_snapshot.strong_sectors[0].source)
        if yesterday_sectors:
            source_parts.append("local-yesterday-group")
        source = "+".join(source_parts) if source_parts else (local_snapshot.source if local_snapshot else "live")
        if not indexes:
            message = local_snapshot.message
        else:
            message = self._build_live_message(
                live_breadth,
                live_sectors,
                index_source=indexes[0].source if indexes else None,
            )
        message = _append_yesterday_sector_note(message, yesterday_sectors)
        snapshot = RealtimeMarketSnapshot(
            status=status,
            source=source,
            updated_at=now,
            market_phase=phase,
            indexes=indexes or (local_snapshot.indexes if local_snapshot else []),
            breadth=breadth,
            strong_sectors=strong_sectors,
            yesterday_strong_sectors=yesterday_sectors,
            message=message,
            diagnostics=diagnostics,
        )
        if snapshot.status == "live" and _is_renderable_snapshot(snapshot):
            self._remember_successful_snapshot(snapshot, generation=request_generation)
            yield {"type": "result", "snapshot": snapshot}
            return
        retained = self._retained_successful_snapshot()
        if retained is not None and not indexes:
            retained_at = retained.updated_at
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
            # P1-2: merge current request diagnostics + original snapshot
            # diagnostics + retained time hint.  Deduplicate ALL sources
            # (including current diagnostics against themselves) while
            # keeping insertion order stable.
            seen: set[str] = set()
            merged_diagnostics: list[str] = []
            for item in diagnostics:
                if item not in seen:
                    seen.add(item)
                    merged_diagnostics.append(item)
            for item in retained.diagnostics:
                if item not in seen:
                    seen.add(item)
                    merged_diagnostics.append(item)
            retained_hint = f"沿用最近成功行情快照：{retained_at.isoformat()}。"
            if retained_hint not in seen:
                merged_diagnostics.append(retained_hint)
            retained.diagnostics = merged_diagnostics
            yield {"type": "result", "snapshot": retained}
            return
        yield {"type": "result", "snapshot": snapshot}

    def _call_live_breadth(
        self,
        diagnostics: list[str],
        deadline: float | None = None,
        cancel_event: Event | None = None,
    ) -> MarketBreadth | None:
        try:
            return self._fetch_live_breadth(
                diagnostics,
                deadline=deadline,
                cancel_event=cancel_event,
            )
        except TypeError:
            try:
                return self._fetch_live_breadth(diagnostics)
            except TypeError:
                return self._fetch_live_breadth()

    def _fetch_live_breadth_with_budget(self, diagnostics: list[str]) -> MarketBreadth | None:
        if self.breadth_time_budget is None:
            worker_diagnostics: list[str] = []
            result = self._call_live_breadth(worker_diagnostics)
            diagnostics.extend(worker_diagnostics)
            return result
        # Single-flight: if the breadth slot is already busy, reject
        # immediately instead of stacking another thread.
        if not self._breadth_in_flight.acquire(blocking=False):
            diagnostics.append("实时红绿家数接口繁忙：上一轮请求尚未完成，已跳过本轮。")
            return None
        try:
            deadline = monotonic_time.monotonic() + self.breadth_time_budget
            cancel_event = Event()
            # The worker writes only to its private diagnostics list.  The caller
            # publishes those diagnostics ONLY when the future completes within the
            # budget; on timeout the private list is discarded so a late worker can
            # never pollute the shared diagnostics.
            worker_diagnostics: list[str] = []
            executor = self._get_breadth_executor()
            future = executor.submit(
                self._call_live_breadth, worker_diagnostics, deadline, cancel_event
            )
        except Exception:
            self._breadth_in_flight.release()
            raise
        future.add_done_callback(lambda _future: self._breadth_in_flight.release())
        try:
            remaining = max(0.0, deadline - monotonic_time.monotonic())
            result = future.result(timeout=remaining)
            # Double-check: even after future.result returns, the computation
            # itself may have exhausted the budget.  Discard the result if so.
            if monotonic_time.monotonic() > deadline:
                raise TimeoutError
            diagnostics.extend(worker_diagnostics)
            return result
        except TimeoutError:
            cancel_event.set()
            future.cancel()
            diagnostics.append(f"实时红绿家数接口超时：{self.breadth_time_budget:g}秒，已继续返回可用行情。")
            return None
        except Exception as exc:
            diagnostics.append(f"实时红绿家数接口失败：{exc}，已继续返回可用行情。")
            return None

    def _fetch_live_sectors_with_budget(
        self,
        diagnostics: list[str],
        sector_rows_out: list[dict] | None = None,
    ) -> list[SectorMover]:
        worker_rows: list[dict] = []
        worker_diagnostics: list[str] = []
        if self.sector_time_budget is None:
            sectors = self._call_live_sectors(worker_diagnostics, sector_rows_out=worker_rows)
            diagnostics.extend(worker_diagnostics)
            if sector_rows_out is not None:
                sector_rows_out[:] = worker_rows
            return sectors
        # Single-flight: if the sector slot is already busy, reject
        # immediately instead of stacking another thread.
        if not self._sector_in_flight.acquire(blocking=False):
            diagnostics.append("实时强势题材接口繁忙：上一轮请求尚未完成，已跳过本轮。")
            return []
        try:
            deadline = monotonic_time.monotonic() + self.sector_time_budget
            cancel_event = Event()
            # The worker writes only to its private diagnostics/rows.  Both are
            # published ONLY when the future completes within the budget; on timeout
            # they are discarded so a late worker cannot pollute shared state.
            executor = self._get_sector_executor()
            future = executor.submit(
                self._call_live_sectors,
                worker_diagnostics,
                deadline,
                cancel_event,
                worker_rows,
            )
        except Exception:
            self._sector_in_flight.release()
            raise
        future.add_done_callback(lambda _future: self._sector_in_flight.release())
        try:
            remaining = max(0.0, deadline - monotonic_time.monotonic())
            sectors = future.result(timeout=remaining)
            if monotonic_time.monotonic() > deadline:
                raise TimeoutError
            diagnostics.extend(worker_diagnostics)
            if sector_rows_out is not None:
                sector_rows_out[:] = worker_rows
            return sectors
        except TimeoutError:
            cancel_event.set()
            future.cancel()
            diagnostics.append(f"实时强势题材接口超时：{self.sector_time_budget:g}秒，已先返回红绿家数并回退本地题材。")
            return []
        except Exception as exc:
            diagnostics.append(f"实时强势题材接口失败：{exc}，已回退本地题材。")
            return []

    def _snapshot_from_local_with_budget(
        self,
        now: datetime,
        diagnostics: list[str],
        sector_rows: list[dict] | None = None,
        *,
        skip_topic_fetch: bool = False,
    ) -> RealtimeMarketSnapshot:
        if self.local_snapshot_time_budget is None:
            return self._call_snapshot_from_local(now, sector_rows, skip_topic_fetch)
        # Single-flight: if the local snapshot slot is already busy, reject
        # immediately instead of stacking another thread.
        if not self._local_in_flight.acquire(blocking=False):
            diagnostics.append("本地兜底行情快照繁忙：上一轮本地快照尚未完成，已跳过本轮。")
            return unavailable_market_snapshot(
                "本地兜底行情快照生成繁忙。",
                diagnostics=["本地兜底行情快照繁忙：上一轮尚未完成。"],
            )
        try:
            deadline = monotonic_time.monotonic() + self.local_snapshot_time_budget
            cancel_event = Event()
            executor = self._get_local_executor()
            future = executor.submit(
                self._call_snapshot_from_local,
                now,
                sector_rows,
                skip_topic_fetch,
                deadline,
                cancel_event,
            )
        except Exception:
            self._local_in_flight.release()
            raise
        future.add_done_callback(lambda _future: self._local_in_flight.release())
        try:
            remaining = max(0.0, deadline - monotonic_time.monotonic())
            result = future.result(timeout=remaining)
            if monotonic_time.monotonic() > deadline:
                raise TimeoutError
            return result
        except TimeoutError:
            # Signal the still-running worker so any late sector-member cache
            # write is blocked before it can commit to shared state.
            cancel_event.set()
            future.cancel()
            diagnostics.append(f"本地兜底行情快照超时：{self.local_snapshot_time_budget:g}秒，已继续返回可用行情。")
            return unavailable_market_snapshot(
                "本地兜底行情快照生成超时。",
                diagnostics=[f"本地兜底行情快照超时：{self.local_snapshot_time_budget:g}秒。"],
            )
        except Exception as exc:
            diagnostics.append(f"本地兜底行情快照失败：{exc}，已继续返回可用行情。")
            return unavailable_market_snapshot(
                f"本地兜底行情快照生成失败：{exc}",
                diagnostics=[f"本地兜底行情快照失败：{exc}"],
            )

    def _call_live_sectors(
        self,
        diagnostics: list[str],
        deadline: float | None = None,
        cancel_event: Event | None = None,
        sector_rows_out: list[dict] | None = None,
    ) -> list[SectorMover]:
        try:
            return self._fetch_live_sectors(
                diagnostics,
                deadline=deadline,
                cancel_event=cancel_event,
                sector_rows_out=sector_rows_out,
            )
        except TypeError:
            try:
                return self._fetch_live_sectors(diagnostics)
            except TypeError:
                return self._fetch_live_sectors()

    def _call_snapshot_from_local(
        self,
        now: datetime,
        sector_rows: list[dict] | None,
        skip_topic_fetch: bool = False,
        deadline: float | None = None,
        cancel_event: Event | None = None,
    ) -> RealtimeMarketSnapshot:
        try:
            return self._snapshot_from_local(
                now,
                sector_rows=sector_rows,
                skip_topic_fetch=skip_topic_fetch,
                deadline=deadline,
                cancel_event=cancel_event,
            )
        except TypeError:
            try:
                return self._snapshot_from_local(
                    now,
                    sector_rows=sector_rows,
                    skip_topic_fetch=skip_topic_fetch,
                )
            except TypeError:
                try:
                    return self._snapshot_from_local(now, sector_rows=sector_rows)
                except TypeError:
                    return self._snapshot_from_local(now)

    def _fetch_indexes(self) -> list[MarketIndexQuote]:
        cls_quotes = self._fetch_cls_indexes()
        if cls_quotes:
            return cls_quotes
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

    def _fetch_cls_home_payload(self) -> dict[str, Any]:
        return cls_request_json(
            self.requester,
            CLS_QUOTE_HOME_URL,
            timeout=min(self.timeout, 2.5),
        )

    def _fetch_cls_indexes(self) -> list[MarketIndexQuote]:
        try:
            payload = self._fetch_cls_home_payload()
        except Exception:
            return []
        rows = payload.get("data", {}).get("index_quote", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            return []
        quotes = [quote for row in rows if isinstance(row, dict) and (quote := _quote_from_cls_home(row))]
        preferred = {symbol for symbol, _ in INDEXES}
        ordered = [quote for quote in quotes if quote.symbol in preferred]
        return ordered or quotes[: len(INDEXES)]

    def _sector_request_timeout(self, max_seconds: float | None = None) -> float:
        timeout = self.sector_source_timeout
        if self.sector_time_budget is not None:
            timeout = min(timeout, max(0.2, self.sector_time_budget / 3))
        if max_seconds is not None:
            timeout = min(timeout, max_seconds)
        return min(self.timeout, timeout)

    def _context_expired(
        self,
        cancel_event: Event | None,
        deadline: float | None,
    ) -> bool:
        """Return True when the request budget is exhausted.

        Unlike :meth:`_source_chain_cancelled`, this is a side-effect-free
        check used to gate writes to cross-request shared caches without
        emitting a diagnostic message.
        """
        if cancel_event is not None and cancel_event.is_set():
            return True
        if deadline is not None and monotonic_time.monotonic() >= deadline:
            return True
        return False

    def _source_chain_cancelled(
        self,
        cancel_event: Event | None,
        deadline: float | None,
        diagnostics: list[str],
        chain: str,
    ) -> bool:
        cancelled = cancel_event is not None and cancel_event.is_set()
        expired = deadline is not None and monotonic_time.monotonic() >= deadline
        if not cancelled and not expired:
            return False
        message = f"{chain} source chain stopped because the request budget was exhausted."
        if message not in diagnostics:
            diagnostics.append(message)
        return True

    def _publish_sector_rows(
        self,
        rows: list[dict],
        sector_rows_out: list[dict] | None,
        cancel_event: Event | None,
        deadline: float | None,
        diagnostics: list[str],
    ) -> bool:
        if self._source_chain_cancelled(cancel_event, deadline, diagnostics, "strong-sector"):
            return False
        if sector_rows_out is not None:
            sector_rows_out[:] = rows
        return True

    def _allow_public_alternate_transport(self) -> bool:
        return should_allow_alternate_transport(self.requester, self.allow_alternate_transport)

    def _request_public_html(
        self,
        url: str,
        *,
        timeout: float,
        source: str,
        diagnostics: list[str],
        deadline: float | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        return resilient_get(
            self.requester,
            url,
            timeout=timeout,
            source=source,
            diagnostics=diagnostics,
            retries=1,
            deadline=deadline,
            alternate_requester=self.alternate_requester,
            allow_alternate=self._allow_public_alternate_transport(),
            headers=headers,
        )

    def _call_ths_concept_section_rows(
        self,
        diagnostics: list[str],
        deadline: float | None,
        cancel_event: Event | None,
    ) -> list[dict]:
        try:
            return self._fetch_ths_concept_section_rows(
                diagnostics=diagnostics,
                deadline=deadline,
                cancel_event=cancel_event,
            )
        except TypeError:
            return self._fetch_ths_concept_section_rows()

    def _call_ths_industry_html_rows(
        self,
        diagnostics: list[str],
        deadline: float | None,
        cancel_event: Event | None,
    ) -> list[dict]:
        try:
            return self._fetch_ths_industry_html_rows(
                diagnostics=diagnostics,
                deadline=deadline,
                cancel_event=cancel_event,
            )
        except TypeError:
            return self._fetch_ths_industry_html_rows()

    def _fetch_live_sectors(
        self,
        diagnostics: list[str] | None = None,
        *,
        deadline: float | None = None,
        cancel_event: Event | None = None,
        sector_rows_out: list[dict] | None = None,
    ) -> list[SectorMover]:
        diagnostics = diagnostics if diagnostics is not None else []
        if self._source_chain_cancelled(cancel_event, deadline, diagnostics, "strong-sector"):
            return []
        cls_sectors = self._call_cls_hot_plate_sectors(
            diagnostics,
            sector_rows_out,
            deadline,
            cancel_event,
        )
        if cls_sectors:
            return _dedupe_sectors(cls_sectors, 10)
        diagnostics.append("cls-hot-plate strong-sector source returned no valid rows.")
        if self._source_chain_cancelled(cancel_event, deadline, diagnostics, "strong-sector"):
            return []
        ths_concept_rows = self._call_ths_concept_section_rows(diagnostics, deadline, cancel_event)
        if self._source_chain_cancelled(cancel_event, deadline, diagnostics, "strong-sector"):
            return []
        ths_concept_sectors = self._parse_sector_rows(ths_concept_rows, "ths-concept-section")
        if ths_concept_sectors:
            if not self._publish_sector_rows(
                ths_concept_rows, sector_rows_out, cancel_event, deadline, diagnostics
            ):
                return []
            return _dedupe_sectors(ths_concept_sectors, 10)
        diagnostics.append("ths-concept-section strong-sector source returned no valid rows.")
        if self._source_chain_cancelled(cancel_event, deadline, diagnostics, "strong-sector"):
            return []
        ths_industry_rows = self._call_ths_industry_html_rows(diagnostics, deadline, cancel_event)
        if self._source_chain_cancelled(cancel_event, deadline, diagnostics, "strong-sector"):
            return []
        ths_industry_sectors = self._parse_sector_rows(ths_industry_rows, "ths-industry-html")
        if ths_industry_sectors:
            if not self._publish_sector_rows(
                ths_industry_rows, sector_rows_out, cancel_event, deadline, diagnostics
            ):
                return []
            return _dedupe_sectors(ths_industry_sectors, 10)
        diagnostics.append("ths-industry-html strong-sector source returned no valid rows.")
        if self._source_chain_cancelled(cancel_event, deadline, diagnostics, "strong-sector"):
            return []
        sina_sectors = self._fetch_sina_sectors()
        if sina_sectors:
            if not self._publish_sector_rows(
                [], sector_rows_out, cancel_event, deadline, diagnostics
            ):
                return []
            return _dedupe_sectors(sina_sectors, 10)
        diagnostics.append("sina-sector strong-sector source returned no valid rows.")
        if self._source_chain_cancelled(cancel_event, deadline, diagnostics, "strong-sector"):
            return []
        akshare_concept_rows = self._fetch_akshare_sector_rows_with_timeout("concept", "akshare-sector", diagnostics)
        akshare_concept_sectors = self._parse_sector_rows(akshare_concept_rows, "akshare-sector")
        if akshare_concept_sectors:
            if not self._publish_sector_rows(
                akshare_concept_rows, sector_rows_out, cancel_event, deadline, diagnostics
            ):
                return []
            return _dedupe_sectors(akshare_concept_sectors, 10)
        diagnostics.append("akshare-sector strong-sector source returned no valid rows.")
        if self._source_chain_cancelled(cancel_event, deadline, diagnostics, "strong-sector"):
            return []
        akshare_industry_rows = self._fetch_akshare_sector_rows_with_timeout("industry", "akshare-industry-sector", diagnostics)
        akshare_industry_sectors = self._parse_sector_rows(akshare_industry_rows, "akshare-industry-sector")
        if akshare_industry_sectors:
            if not self._publish_sector_rows(
                akshare_industry_rows, sector_rows_out, cancel_event, deadline, diagnostics
            ):
                return []
            return _dedupe_sectors(akshare_industry_sectors, 10)
        diagnostics.append("akshare-industry-sector strong-sector source returned no valid rows.")
        if self._source_chain_cancelled(cancel_event, deadline, diagnostics, "strong-sector"):
            return []
        eastmoney_concept_rows = self._call_eastmoney_sector_rows(
            ["m:90+t:3+f:!50", "m:90+t:3"],
            diagnostics=diagnostics,
            source_label="eastmoney-sector",
        )
        eastmoney_concept_sectors = self._parse_sector_rows(eastmoney_concept_rows, "eastmoney-sector")
        if eastmoney_concept_sectors:
            if not self._publish_sector_rows(
                eastmoney_concept_rows, sector_rows_out, cancel_event, deadline, diagnostics
            ):
                return []
            return _dedupe_sectors(eastmoney_concept_sectors, 10)
        diagnostics.append("eastmoney-sector controlled backup returned no valid rows.")
        if self._source_chain_cancelled(cancel_event, deadline, diagnostics, "strong-sector"):
            return []
        eastmoney_industry_rows = self._call_eastmoney_sector_rows(
            ["m:90+t:2+f:!50", "m:90+t:2"],
            diagnostics=diagnostics,
            source_label="eastmoney-industry-sector",
        )
        eastmoney_industry_sectors = self._parse_sector_rows(eastmoney_industry_rows, "eastmoney-industry-sector")
        if eastmoney_industry_sectors:
            if not self._publish_sector_rows(
                eastmoney_industry_rows, sector_rows_out, cancel_event, deadline, diagnostics
            ):
                return []
            return _dedupe_sectors(eastmoney_industry_sectors, 10)
        diagnostics.append("eastmoney-industry-sector controlled backup returned no valid rows.")
        if self._source_chain_cancelled(cancel_event, deadline, diagnostics, "strong-sector"):
            return []
        ths_hot_topic_rows = self._fetch_ths_hot_topic_rows()
        if ths_hot_topic_rows:
            # Hot-reason rows are useful topic candidates, but their gains are
            # individual stock moves. Do not present them as board quote pct.
            self._publish_sector_rows(
                ths_hot_topic_rows,
                sector_rows_out,
                cancel_event,
                deadline,
                diagnostics,
            )
        else:
            diagnostics.append("ths-hot-reason strong-topic source returned no valid rows.")
        return []

    def _call_cls_hot_plate_sectors(
        self,
        diagnostics: list[str],
        sector_rows_out: list[dict] | None,
        deadline: float | None,
        cancel_event: Event | None,
    ) -> list[SectorMover]:
        try:
            return self._fetch_cls_hot_plate_sectors(
                diagnostics,
                sector_rows_out=sector_rows_out,
                deadline=deadline,
                cancel_event=cancel_event,
            )
        except TypeError:
            return self._fetch_cls_hot_plate_sectors(diagnostics)

    def _fetch_cls_hot_plate_sectors(
        self,
        diagnostics: list[str],
        *,
        sector_rows_out: list[dict] | None = None,
        deadline: float | None = None,
        cancel_event: Event | None = None,
    ) -> list[SectorMover]:
        try:
            payload = cls_request_json(
                self.requester,
                CLS_HOT_PLATE_URL,
                params={"type": "industry,concept,area", "way": "change", "rever": 1},
                timeout=self._sector_request_timeout(max_seconds=2.0),
            )
        except Exception as exc:
            diagnostics.append(f"cls-hot-plate strong-sector source failed: {exc}")
            return []
        rows = _sector_rows_from_cls_hot_plate(payload)
        sectors = self._parse_sector_rows(rows, "cls-hot-plate")
        if sectors and not self._publish_sector_rows(
            rows, sector_rows_out, cancel_event, deadline, diagnostics
        ):
            return []
        return sectors

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

    def _fetch_live_breadth(
        self,
        diagnostics: list[str],
        *,
        deadline: float | None = None,
        cancel_event: Event | None = None,
    ) -> MarketBreadth | None:
        fetchers: list[tuple[str, Callable[[], MarketBreadth | None]]] = [
            ("财联社涨跌分布", self._fetch_cls_breadth),
            (
                "同花顺市场总览",
                lambda: self._call_ths_market_summary_breadth(diagnostics, deadline, cancel_event),
            ),
            ("Sina 批量实时个股", self._fetch_sina_breadth),
            ("Tencent 批量实时个股", lambda: self._fetch_tencent_breadth(diagnostics)),
            ("AKShare 实时个股", lambda: self._fetch_akshare_breadth_with_timeout(diagnostics)),
            ("重型公开行情爬虫", lambda: self._fetch_heavy_breadth(diagnostics)),
        ]
        if self.allow_eastmoney_breadth_fallback:
            fetchers.append(("东方财富轻量 spot 兜底", lambda: self._fetch_eastmoney_breadth(diagnostics)))
        local_symbol_count: int | None = None
        for label, fetcher in fetchers:
            if self._source_chain_cancelled(cancel_event, deadline, diagnostics, "market-breadth"):
                return None
            try:
                breadth = fetcher()
            except Exception as exc:
                diagnostics.append(f"{label}红绿家数读取失败：{exc}")
                continue
            if breadth is None:
                continue
            if breadth.source == "cls-quote-breadth" and breadth.total > 0:
                return breadth
            if local_symbol_count is None:
                local_symbol_count = max(self._latest_local_symbol_count(), self._coverage_symbol_count())
            if self._breadth_is_complete(breadth, local_symbol_count, diagnostics):
                return breadth
        return None

    def _fetch_cls_breadth(self) -> MarketBreadth | None:
        payload = self._fetch_cls_home_payload()
        distribution = payload.get("data", {}).get("up_down_dis", {}) if isinstance(payload, dict) else {}
        return _breadth_from_cls_distribution(distribution)

    def _breadth_is_complete(
        self,
        breadth: MarketBreadth,
        local_symbol_count: int,
        diagnostics: list[str],
    ) -> bool:
        if is_valid_full_market_breadth(breadth, local_symbol_count):
            return True
        ratio_text = (
            f"，本地股票池={local_symbol_count}，比例={breadth.total / local_symbol_count:.1%}"
            if local_symbol_count > 0
            else "，本地股票池不可用"
        )
        diagnostics.append(
            f"全市场红绿家数不完整：source={breadth.source} total={breadth.total}{ratio_text}，已判定该来源失败。"
        )
        return False

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

    def _breadth_request_timeout(self) -> float:
        timeout = self.breadth_source_timeout
        if self.breadth_time_budget is not None:
            timeout = min(timeout, max(0.2, self.breadth_time_budget / 2))
        return min(self.timeout, timeout)

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
        return a_share_market_symbol(symbol)

    def _tencent_stock_symbol(self, symbol: str) -> str | None:
        return a_share_market_symbol(symbol)

    def _fetch_tencent_breadth(self, diagnostics: list[str]) -> MarketBreadth | None:
        deadline = monotonic_time.monotonic() + self.breadth_time_budget
        symbols = self._latest_local_symbols()
        if not symbols:
            return None
        quote_symbols = [quote for symbol in symbols if (quote := self._tencent_stock_symbol(symbol))]
        up = 0
        down = 0
        flat = 0
        seen: set[str] = set()
        for start in range(0, len(quote_symbols), SINA_BREADTH_BATCH_SIZE):
            remaining = deadline - monotonic_time.monotonic()
            if remaining <= 0:
                diagnostics.append("Tencent 批量实时个股红绿家数超时。")
                return None
            batch = quote_symbols[start : start + SINA_BREADTH_BATCH_SIZE]
            try:
                response = self.requester(
                    TENCENT_QUOTE_URL.format(symbols=",".join(batch)),
                    timeout=min(self.timeout, max(0.2, remaining)),
                    headers={"Referer": "https://stockapp.finance.qq.com/", "User-Agent": "Mozilla/5.0"},
                )
                response.raise_for_status()
            except Exception as exc:
                diagnostics.append(f"Tencent 批量实时个股请求失败：{exc}")
                return None
            response.encoding = response.encoding or "gbk"
            for segment in response.text.split(";"):
                if '="' not in segment or "~" not in segment:
                    continue
                key = segment.split("v_", 1)[-1].split("=", 1)[0].strip()
                values = segment.split("=", 1)[1].strip().strip('"').split("~")
                if len(values) < 5:
                    continue
                last = _parse_float(values[3])
                previous_close = _parse_float(values[4])
                symbol = normalize_symbol(key[-6:])
                if not symbol or symbol in seen or last is None or previous_close is None or previous_close <= 0:
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
        return MarketBreadth(up=up, down=down, flat=flat, total=total, source="tencent-a-share-live")

    def _fetch_akshare_breadth(self, diagnostics: list[str]) -> MarketBreadth | None:
        try:
            import akshare as ak

            frame = ak.stock_zh_a_spot_em()
        except Exception as exc:
            diagnostics.append(f"AKShare 实时个股红绿家数读取失败：{exc}")
            return None
        if frame is None or frame.empty:
            diagnostics.append("AKShare 实时个股红绿家数返回空数据。")
            return None
        change_column = next((column for column in ["涨跌幅", "change_pct", "pct_chg"] if column in frame.columns), None)
        code_column = next((column for column in ["代码", "股票代码", "symbol", "code"] if column in frame.columns), None)
        if change_column is None or code_column is None:
            diagnostics.append("AKShare 实时个股红绿家数字段不完整。")
            return None
        data = frame[[code_column, change_column]].copy()
        data[code_column] = data[code_column].astype(str).map(normalize_symbol)
        data[change_column] = pd.to_numeric(data[change_column], errors="coerce")
        data = data.dropna(subset=[code_column, change_column])
        data = data[data[code_column].astype(str).str.fullmatch(r"\d{6}")]
        if data.empty:
            return None
        up = int((data[change_column] > 0).sum())
        down = int((data[change_column] < 0).sum())
        flat = int((data[change_column] == 0).sum())
        return MarketBreadth(up=up, down=down, flat=flat, total=up + down + flat, source="akshare-a-share-live")

    def _fetch_akshare_breadth_with_timeout(self, diagnostics: list[str]) -> MarketBreadth | None:
        timeout = self._breadth_request_timeout()
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self._fetch_akshare_breadth, diagnostics)
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            future.cancel()
            diagnostics.append(f"AKShare 实时个股红绿家数读取超时：{timeout:g}秒。")
            return None
        except Exception as exc:
            diagnostics.append(f"AKShare 实时个股红绿家数读取失败：{exc}")
            return None
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _fetch_heavy_breadth(self, diagnostics: list[str]) -> MarketBreadth | None:
        if self._heavy_market_provider is None:
            self._heavy_market_provider = HeavyMarketCrawlerProvider(
                requester=self.requester,
                timeout=min(self.timeout, 1.2),
                browser_provider=BrowserMarketProvider(timeout=min(self.timeout, 2.5)),
            )
        breadth = self._heavy_market_provider.fetch_breadth()
        if breadth is None:
            diagnostics.append("重型公开行情爬虫未取得完整红绿家数。")
        return breadth

    def _fetch_eastmoney_breadth(self, diagnostics: list[str]) -> MarketBreadth | None:
        try:
            response = self.requester(
                EASTMONEY_A_SPOT_URL,
                timeout=min(self.timeout, 2.5),
                headers={"Referer": "https://quote.eastmoney.com/", "User-Agent": "Mozilla/5.0"},
                params={
                    "pn": "1",
                    "pz": "6000",
                    "po": "1",
                    "np": "1",
                    "fltt": "2",
                    "invt": "2",
                    "fid": "f3",
                    "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
                    "fields": "f12,f14,f2,f3",
                },
            )
            response.raise_for_status()
            payload = response.json() or {}
        except Exception as exc:
            diagnostics.append(f"东方财富轻量 spot 红绿家数读取失败：{exc}")
            return None
        rows = payload.get("data", {}).get("diff", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list) or not rows:
            diagnostics.append("东方财富轻量 spot 红绿家数返回空数据。")
            return None
        up = 0
        down = 0
        flat = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = normalize_symbol(str(row.get("f12") or ""))
            change_pct = _parse_float(row.get("f3"))
            price = _parse_float(row.get("f2"))
            if not code or change_pct is None or price is None or price <= 0:
                continue
            if change_pct > 0:
                up += 1
            elif change_pct < 0:
                down += 1
            else:
                flat += 1
        total = up + down + flat
        if total == 0:
            diagnostics.append("东方财富轻量 spot 红绿家数字段校验后为空。")
            return None
        return MarketBreadth(up=up, down=down, flat=flat, total=total, source="eastmoney-a-share-spot")

    def _call_eastmoney_sector_rows(
        self,
        fs_values: str | list[str],
        diagnostics: list[str],
        source_label: str,
    ) -> list[dict]:
        try:
            return self._fetch_eastmoney_sector_rows(fs_values, diagnostics=diagnostics, source_label=source_label)
        except TypeError:
            # Compatibility for tests that monkeypatch the old one-argument helper.
            return self._fetch_eastmoney_sector_rows(fs_values)

    def _fetch_eastmoney_sector_rows(
        self,
        fs_values: str | list[str],
        diagnostics: list[str] | None = None,
        source_label: str = "eastmoney-sector",
    ) -> list[dict]:
        diagnostics = diagnostics if diagnostics is not None else []
        values = [fs_values] if isinstance(fs_values, str) else fs_values
        for url in EASTMONEY_SECTOR_URLS:
            for fs in values:
                payload = self._request_eastmoney_sector_payload(url, fs, diagnostics, source_label)
                rows = payload.get("data", {}).get("diff", []) if isinstance(payload, dict) else []
                valid = self._normalize_sector_rows(rows)
                if len(valid) >= MIN_CONTROLLED_BACKUP_SECTOR_ROWS:
                    diagnostics.append(
                        f"{source_label} controlled backup accepted host={url} fs={fs} valid_rows={len(valid)}."
                    )
                    return valid
                if rows:
                    diagnostics.append(
                        f"{source_label} controlled backup rejected host={url} fs={fs}: "
                        f"valid_rows={len(valid)} below_min={MIN_CONTROLLED_BACKUP_SECTOR_ROWS}."
                    )
        return []

    def _request_eastmoney_sector_payload(
        self,
        url: str,
        fs: str,
        diagnostics: list[str] | None = None,
        source_label: str = "eastmoney-sector",
    ) -> dict:
        try:
            response = self.requester(
                url,
                timeout=self._sector_request_timeout(max_seconds=2.5),
                headers={"Referer": "https://quote.eastmoney.com/", "User-Agent": "Mozilla/5.0"},
                params={
                    "pn": "1",
                    "pz": "50",
                    "po": "1",
                    "np": "1",
                    "fltt": "2",
                    "invt": "2",
                    "fid": "f3",
                    "fs": fs,
                    "fields": "f2,f3,f4,f8,f12,f14,f20,f104,f105,f128,f136",
                },
            )
            response.raise_for_status()
            payload = response.json() or {}
        except Exception as exc:
            if diagnostics is not None:
                diagnostics.append(
                    f"{source_label} controlled backup request failed host={url} fs={fs}: {exc}"
                )
            return {}
        if not isinstance(payload, dict):
            if diagnostics is not None:
                diagnostics.append(
                    f"{source_label} controlled backup invalid payload host={url} fs={fs}: "
                    f"type={type(payload).__name__}"
                )
            return {}
        return payload

    def _normalize_sector_rows(self, rows: object) -> list[dict]:
        if not isinstance(rows, list):
            return []
        valid: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("f14") or "").strip()
            code = str(row.get("f12") or "").strip()
            if not name or not code:
                continue
            if _normalize_sector_change_pct(row) is None:
                continue
            row["_change_pct_unit"] = "percent"
            valid.append(row)
        return valid

    def _fetch_akshare_sector_rows(self, board_type: str) -> list[dict]:
        try:
            import akshare as ak

            if board_type == "concept":
                frame = ak.stock_board_concept_name_em()
            else:
                frame = ak.stock_board_industry_name_em()
        except Exception:
            return []
        if frame is None or getattr(frame, "empty", True):
            return []
        rows: list[dict] = []
        for _, item in frame.head(50).iterrows():
            row = {
                "f12": item.get("板块代码") or item.get("代码") or item.get("code") or "",
                "f14": item.get("板块名称") or item.get("名称") or item.get("name") or "",
                "f3": item.get("涨跌幅") or item.get("change_pct") or item.get("涨跌幅%") or None,
                "f128": item.get("领涨股票") or item.get("领涨股") or "",
            }
            if _normalize_sector_change_pct(row) is not None and str(row["f14"]).strip():
                rows.append(row)
        return rows

    def _fetch_akshare_sector_rows_with_timeout(
        self,
        board_type: str,
        source: str,
        diagnostics: list[str],
    ) -> list[dict]:
        timeout = self._sector_request_timeout()
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self._fetch_akshare_sector_rows, board_type)
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            future.cancel()
            diagnostics.append(f"{source} strong-sector source timeout after {timeout:g}s.")
            return []
        except Exception as exc:
            diagnostics.append(f"{source} strong-sector source failed: {exc}")
            return []
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _fetch_sina_sectors(self) -> list[SectorMover]:
        try:
            response = self.requester(
                "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php",
                timeout=self._sector_request_timeout(),
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
                    timeout=self._sector_request_timeout(),
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

    def _fetch_ths_concept_section_rows(
        self,
        diagnostics: list[str] | None = None,
        deadline: float | None = None,
        cancel_event: Event | None = None,
    ) -> list[dict]:
        diagnostics = diagnostics if diagnostics is not None else []
        try:
            response = self._request_public_html(
                THS_CONCEPT_SECTION_URL,
                timeout=self._sector_request_timeout(),
                source="ths-concept-section",
                diagnostics=diagnostics,
                deadline=deadline,
                headers=THS_HEADERS,
            )
        except Exception:
            if self._source_chain_cancelled(cancel_event, deadline, diagnostics, "strong-sector"):
                return []
            return []
        if self._source_chain_cancelled(cancel_event, deadline, diagnostics, "strong-sector"):
            return []
        response.encoding = response.encoding or "gbk"
        soup = BeautifulSoup(response.text, "html.parser")
        node = soup.select_one("#gnSection")
        raw_value = str(node.get("value") or "") if node else ""
        if not raw_value:
            return []
        try:
            payload = json.loads(raw_value)
        except (TypeError, ValueError):
            return []
        if not isinstance(payload, dict):
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
        return rows

    def _fetch_ths_industry_html_rows(
        self,
        max_pages: int = 3,
        diagnostics: list[str] | None = None,
        deadline: float | None = None,
        cancel_event: Event | None = None,
    ) -> list[dict]:
        diagnostics = diagnostics if diagnostics is not None else []
        rows_out: list[dict] = []
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            if self._source_chain_cancelled(cancel_event, deadline, diagnostics, "strong-sector"):
                return []
            try:
                response = self._request_public_html(
                    THS_INDUSTRY_HTML_URL.format(page=page),
                    timeout=self._sector_request_timeout(),
                    source="ths-industry-html",
                    diagnostics=diagnostics,
                    deadline=deadline,
                    headers=THS_HEADERS,
                )
            except Exception:
                break
            if self._source_chain_cancelled(cancel_event, deadline, diagnostics, "strong-sector"):
                return []
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
        if self._source_chain_cancelled(cancel_event, deadline, diagnostics, "strong-sector"):
            return []
        return rows_out

    def _call_ths_market_summary_breadth(
        self,
        diagnostics: list[str],
        deadline: float | None,
        cancel_event: Event | None,
    ) -> MarketBreadth | None:
        try:
            return self._fetch_ths_market_summary_breadth(
                diagnostics=diagnostics,
                deadline=deadline,
                cancel_event=cancel_event,
            )
        except TypeError:
            return self._fetch_ths_market_summary_breadth()

    def _fetch_ths_market_summary_breadth(
        self,
        diagnostics: list[str] | None = None,
        deadline: float | None = None,
        cancel_event: Event | None = None,
    ) -> MarketBreadth | None:
        diagnostics = diagnostics if diagnostics is not None else []
        try:
            response = self._request_public_html(
                THS_MARKET_SUMMARY_URL,
                timeout=self.timeout,
                source="ths-market-summary",
                diagnostics=diagnostics,
                deadline=deadline,
                headers=THS_HEADERS,
            )
            if self._source_chain_cancelled(cancel_event, deadline, diagnostics, "market-breadth"):
                return None
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

        if self._source_chain_cancelled(cancel_event, deadline, diagnostics, "market-breadth"):
            return None
        industry_rows = self._call_ths_industry_html_rows(diagnostics, deadline, cancel_event)
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

    def _coverage_symbol_count(self) -> int:
        try:
            coverage = self.warehouse.coverage()
        except Exception:
            return 0
        for item in coverage:
            if getattr(item, "dataset", None) == "daily_bars":
                return int(getattr(item, "symbols", 0) or 0)
        return 0

    def _build_live_message(
        self,
        live_breadth: MarketBreadth | None,
        live_sectors: list[SectorMover],
        index_source: str | None = "ashare-sina",
    ) -> str:
        index_label = {
            "cls-quote-index": "财联社指数",
            "ashare-sina": "Ashare/Sina",
        }.get(index_source, "实时接口")
        breadth_label = {
            "cls-quote-breadth": "财联社涨跌分布",
            "ths-market-summary": "同花顺市场总览",
            "sina-a-share-live": "新浪实时个股",
            "tencent-a-share-live": "腾讯实时个股",
            "akshare-a-share-live": "AKShare 实时个股",
            "heavy-market-crawler": "重型公开行情爬虫",
            "browser-market-provider": "浏览器公开行情爬虫",
            "eastmoney-a-share-spot": "东方财富轻量 spot 备选",
        }.get(live_breadth.source if live_breadth else None)
        sector_label = {
            "cls-hot-plate": "财联社热门板块",
            "ths-hot-reason": "同花顺热点归因",
            "ths-concept-section": "同花顺概念题材板块",
            "ths-industry-html": "同花顺行业板块总览",
            "eastmoney-sector": "东方财富概念板块备选",
            "eastmoney-industry-sector": "东方财富行业板块备选",
            "akshare-sector": "AKShare 概念板块备选",
            "akshare-industry-sector": "AKShare 行业板块备选",
            "sina-sector": "新浪行业板块",
        }.get(live_sectors[0].source if live_sectors else None)

        if sector_label and breadth_label:
            return f"实时指数来自{index_label}，强势题材来自{sector_label}，红绿家数来自{breadth_label}。"
        if sector_label:
            return f"实时指数来自{index_label}，强势题材来自{sector_label}，红绿家数暂不可用，未展示全市场宽度。"
        if breadth_label:
            return f"实时指数来自{index_label}，红绿家数来自{breadth_label}，强势题材暂不可用。"
        return f"实时指数来自{index_label}，红绿家数与强势题材暂不可用，已保留可用的最近数据。"

    def _snapshot_from_local(
        self,
        now: datetime,
        *,
        sector_rows: list[dict] | None = None,
        skip_topic_fetch: bool = False,
        deadline: float | None = None,
        cancel_event: Event | None = None,
    ) -> RealtimeMarketSnapshot:
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
        diagnostics = [f"已使用本地最近交易日 {latest_date.date()} 作为兜底快照。"]
        coverage_symbol_count = self._coverage_symbol_count()
        if not is_valid_full_market_breadth(breadth, coverage_symbol_count):
            ratio_text = (
                f"，本地股票池={coverage_symbol_count}，比例={breadth.total / coverage_symbol_count:.1%}"
                if coverage_symbol_count > 0
                else "，本地股票池不可用"
            )
            diagnostics.append(
                f"全市场红绿家数不完整：source=local-latest total={breadth.total}{ratio_text}，已隐藏该宽度统计。"
            )
            breadth = None

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
        local_sectors = self._local_market_groups(
            latest,
            source="local-market-group",
            sector_rows=sector_rows,
            skip_topic_fetch=skip_topic_fetch,
            deadline=deadline,
            cancel_event=cancel_event,
        )
        yesterday_sectors = self._local_market_groups(
            yesterday,
            source="local-yesterday-group",
            sector_rows=sector_rows,
            skip_topic_fetch=skip_topic_fetch,
            deadline=deadline,
            cancel_event=cancel_event,
        )
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
            diagnostics=diagnostics,
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

    def _local_market_groups(
        self,
        latest: pd.DataFrame,
        source: str,
        sector_rows: list[dict] | None = None,
        *,
        skip_topic_fetch: bool = False,
        deadline: float | None = None,
        cancel_event: Event | None = None,
    ) -> list[SectorMover]:
        sector_rows = [] if sector_rows is None else sector_rows
        if latest.empty:
            return []
        if not sector_rows:
            if skip_topic_fetch:
                return []
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
                members = self._fetch_board_members(
                    board_code,
                    cancel_event=cancel_event,
                    deadline=deadline,
                )
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

    def _fetch_board_members(
        self,
        board_code: str,
        *,
        cancel_event: Event | None = None,
        deadline: float | None = None,
    ) -> list[str]:
        cached = self._sector_member_cache.get(board_code)
        if cached is not None:
            return cached
        if board_code.isdigit() and board_code.startswith("88"):
            members = self._fetch_ths_board_members(board_code)
        else:
            members = []
        # The freshly read members are always returned to the current worker,
        # but they are committed to the cross-request shared cache ONLY when the
        # request is still within budget AND the cancel event has not been set
        # (double-checked under the state lock to prevent TOCTOU races).
        if not self._context_expired(cancel_event, deadline):
            with self._state_lock:
                if cancel_event is None or not cancel_event.is_set():
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
