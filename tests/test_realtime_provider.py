from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event, Lock
from time import monotonic, sleep

import astock_backtester.data.realtime as realtime_module
import pytest
from astock_backtester.data.realtime import RealtimeMarketProvider
from astock_backtester.data.realtime_parsers import BEIJING_TZ
from astock_backtester.models import (
    MarketBreadth,
    MarketIndexQuote,
    RealtimeMarketSnapshot,
    SectorMover,
)


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Warehouse:
    pass


def test_realtime_provider_single_flights_cls_home_payload():
    entered = Event()
    release = Event()
    calls = 0
    calls_lock = Lock()
    payload = {
        "code": 200,
        "data": {"index_quote": [], "up_down_dis": {"rise_num": 4, "fall_num": 0}},
    }

    def requester(_url, **_kwargs):
        nonlocal calls
        with calls_lock:
            calls += 1
        entered.set()
        assert release.wait(timeout=2)
        return _Response(payload)

    provider = RealtimeMarketProvider(warehouse=_Warehouse(), requester=requester, timeout=2.0)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(provider._fetch_cls_home_payload)
        assert entered.wait(timeout=2)
        second = executor.submit(provider._fetch_cls_home_payload)
        release.set()
        assert first.result(timeout=2) == payload
        assert second.result(timeout=2) == payload

    assert calls == 1


def test_realtime_provider_records_market_summary_failure_in_diagnostics():
    provider = RealtimeMarketProvider(warehouse=_Warehouse())

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("upstream unavailable")

    provider._request_public_html = unavailable
    provider._call_ths_industry_html_rows = lambda *_args, **_kwargs: []
    diagnostics: list[str] = []

    assert provider._fetch_ths_market_summary_breadth(diagnostics) is None
    assert any("同花顺市场总览" in item and "upstream unavailable" in item for item in diagnostics)


def test_realtime_provider_uses_bounded_ths_indexflash_breadth_before_bulk_fallbacks():
    requested_headers = {}
    cookie_timeouts = []

    def requester(url, **kwargs):
        assert "indexflash" in url
        requested_headers.update(kwargs["headers"])
        return _Response({"result": {"zdfb_data": {"znum": 3351, "dnum": 2098}}})

    provider = RealtimeMarketProvider(
        warehouse=_Warehouse(),
        requester=requester,
        breadth_time_budget=2.0,
        breadth_source_timeout=0.8,
        ths_cookie_getter=lambda timeout: cookie_timeouts.append(timeout) or "v=fresh-request",
    )
    provider._fetch_cls_breadth = lambda *_args, **_kwargs: None
    provider._fetch_sina_breadth = lambda: pytest.fail("bulk Sina fallback should not run")
    provider._fetch_tencent_breadth = lambda _diagnostics: pytest.fail("bulk Tencent fallback should not run")
    provider._fetch_akshare_breadth_with_timeout = lambda _diagnostics: pytest.fail("AKShare fallback should not run")
    provider._fetch_heavy_breadth = lambda _diagnostics: pytest.fail("heavy crawler should not run")
    provider._latest_local_symbol_count = lambda: pytest.fail("full-market symbol scan should not run")
    provider._coverage_symbol_count = lambda: pytest.fail("warehouse coverage scan should not run")

    breadth = provider._fetch_live_breadth([], deadline=monotonic() + 2.0, cancel_event=Event())

    assert breadth is not None
    assert breadth.source == "ths-indexflash-breadth"
    assert (breadth.up, breadth.down, breadth.flat, breadth.total) == (3351, 2098, 0, 5449)
    assert requested_headers["Cookie"] == "v=fresh-request"
    assert cookie_timeouts and cookie_timeouts[0] <= 0.8


def test_realtime_provider_single_flight_waiter_rejects_expired_cache_after_owner_failure(monkeypatch):
    entered = Event()
    release = Event()
    calls = 0

    class TrackingEvent(Event):
        waiter_entered = Event()

        def wait(self, timeout=None):
            TrackingEvent.waiter_entered.set()
            return super().wait(timeout)

    monkeypatch.setattr(realtime_module, "Event", TrackingEvent)

    def requester(_url, **_kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(timeout=2)
        raise RuntimeError("CLS refresh failed")

    provider = RealtimeMarketProvider(warehouse=_Warehouse(), requester=requester, timeout=2.0)
    provider._cls_home_cache = {"code": 200, "data": {"stale": True}}
    provider._cls_home_cached_at = monotonic() - provider.cls_home_cache_ttl - 1

    with ThreadPoolExecutor(max_workers=2) as executor:
        owner = executor.submit(provider._fetch_cls_home_payload)
        assert entered.wait(timeout=2)
        waiter = executor.submit(provider._fetch_cls_home_payload)
        assert TrackingEvent.waiter_entered.wait(timeout=2)
        release.set()

        with pytest.raises(RuntimeError, match="CLS refresh failed"):
            owner.result(timeout=2)
        with pytest.raises(RuntimeError, match="single-flight request failed"):
            waiter.result(timeout=2)

    assert calls == 1


def test_realtime_provider_single_flight_waiter_survives_completed_cache_clear(monkeypatch):
    entered = Event()
    release = Event()
    wait_started = Event()
    waiter_awake = Event()
    allow_waiter_to_read = Event()
    payload = {
        "code": 200,
        "data": {"index_quote": [], "up_down_dis": {"rise_num": 4, "fall_num": 0}},
    }

    class TrackingEvent(Event):
        def wait(self, timeout=None):
            wait_started.set()
            result = super().wait(timeout)
            if result:
                waiter_awake.set()
                assert allow_waiter_to_read.wait(timeout=2)
            return result

    monkeypatch.setattr(realtime_module, "Event", TrackingEvent)

    def requester(_url, **_kwargs):
        entered.set()
        assert release.wait(timeout=2)
        return _Response(payload)

    provider = RealtimeMarketProvider(warehouse=_Warehouse(), requester=requester, timeout=2.0)
    with ThreadPoolExecutor(max_workers=2) as executor:
        owner = executor.submit(provider._fetch_cls_home_payload)
        assert entered.wait(timeout=2)
        waiter = executor.submit(provider._fetch_cls_home_payload)
        assert wait_started.wait(timeout=2)
        release.set()
        assert waiter_awake.wait(timeout=2)
        provider._clear_cls_home_completed_cache()
        allow_waiter_to_read.set()

        assert owner.result(timeout=2) == payload
        assert waiter.result(timeout=2) == payload


def test_realtime_provider_finds_previous_trade_date_before_long_holiday(monkeypatch):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 2, 24, 12, tzinfo=tz)

    monkeypatch.setattr(realtime_module, "datetime", FixedDatetime)

    provider = RealtimeMarketProvider(warehouse=_Warehouse())

    assert provider._previous_trade_date() == "2026-02-13"


def test_realtime_provider_uses_beijing_dates_at_non_cn_host_midnight_boundary(monkeypatch):
    beijing_now = datetime(2026, 7, 14, 0, 30, tzinfo=BEIJING_TZ)
    non_cn_host_now = datetime(2026, 7, 13, 9, 30, tzinfo=timezone(-timedelta(hours=7)))

    class NonCnHostClock:
        def astimezone(self, tz=None):
            return beijing_now if tz == BEIJING_TZ else non_cn_host_now

    class FixedDatetime:
        @classmethod
        def now(cls, tz=None):
            assert tz == timezone.utc
            return NonCnHostClock()

    monkeypatch.setattr(realtime_module, "datetime", FixedDatetime)
    provider = RealtimeMarketProvider(warehouse=_Warehouse())

    assert provider._latest_trade_date() == "2026-07-14"
    assert provider._previous_trade_date() == "2026-07-13"
    assert provider._yesterday_pool_dates() == ("2026-07-14", "2026-07-13")


def test_realtime_provider_keeps_zero_zdp_before_secondary_pct():
    def requester(_url, **_kwargs):
        return _Response(
            {
                "rc": 0,
                "data": {
                    "pool": [
                        {
                            "c": "000001",
                            "n": "Zero move",
                            "hybk": "Zero sector",
                            "zdp": 0,
                            "pct": "7.00",
                        }
                    ]
                },
            }
        )

    diagnostics = []
    provider = RealtimeMarketProvider(warehouse=_Warehouse(), requester=requester, timeout=2.0)
    provider._latest_trade_date = lambda: "2026-07-14"

    result = provider._fetch_yesterday_strong_sectors(diagnostics)

    assert result[0].change_pct == 0.0


def test_realtime_provider_keeps_one_point_zdp_as_one_percent():
    def requester(_url, **_kwargs):
        return _Response(
            {
                "rc": 0,
                "data": {
                    "pool": [
                        {"c": "000001", "n": "One up", "hybk": "Up sector", "zdp": "1.00"},
                        {"c": "000002", "n": "One down", "hybk": "Down sector", "zdp": "-1.00"},
                    ]
                },
            }
        )

    diagnostics = []
    provider = RealtimeMarketProvider(warehouse=_Warehouse(), requester=requester, timeout=2.0)
    provider._latest_trade_date = lambda: "2026-07-14"

    result = provider._fetch_yesterday_strong_sectors(diagnostics)

    changes = {sector.name: sector.change_pct for sector in result}
    assert changes == {"Up sector": 0.01, "Down sector": -0.01}


def test_realtime_provider_uses_public_yesterday_limit_up_request_contract():
    requested = []

    def requester(url, **kwargs):
        requested.append((url, kwargs["params"]))
        return _Response(
            {
                "rc": 0,
                "data": {
                    "pool": [
                        {"c": "000001", "n": "Power", "hybk": "Power sector", "zdp": "2.00"}
                    ]
                },
            }
        )

    provider = RealtimeMarketProvider(warehouse=_Warehouse(), requester=requester, timeout=2.0)
    provider._latest_trade_date = lambda: "2026-07-14"

    provider._fetch_yesterday_strong_sectors([])

    params = requested[0][1]
    assert params["date"] == "20260714"
    assert params["sort"] == "zs:desc"
    assert params["ft"] == "1"
    assert params["l"] == "0"
    assert provider._yesterday_sector_cache_date == "2026-07-13"


def test_realtime_provider_uses_tc_to_complete_an_exact_full_yesterday_pool_page():
    requested_pages = []
    pool = [
        {"c": f"{index:06d}", "n": f"Stock {index}", "hybk": "Complete sector", "zdp": "2.00"}
        for index in range(100)
    ]

    def requester(_url, **kwargs):
        page = int(kwargs["params"]["Pageindex"])
        requested_pages.append(page)
        return _Response({"rc": 0, "data": {"tc": 100, "pool": pool if page == 0 else []}})

    diagnostics = []
    provider = RealtimeMarketProvider(warehouse=_Warehouse(), requester=requester, timeout=2.0)
    provider._latest_trade_date = lambda: "2026-07-14"

    provider._fetch_yesterday_strong_sectors(diagnostics)

    assert requested_pages == [0]
    assert provider._yesterday_sector_cache_date == "2026-07-13"
    assert provider._yesterday_sector_cache
    assert not any("partial" in item for item in diagnostics)


def test_realtime_provider_caches_and_reuses_an_empty_complete_yesterday_pool():
    requested = []

    def requester(_url, **kwargs):
        requested.append(kwargs["params"])
        return _Response({"rc": 0, "data": {"tc": 0, "pool": []}})

    diagnostics = []
    provider = RealtimeMarketProvider(warehouse=_Warehouse(), requester=requester, timeout=2.0)
    provider._latest_trade_date = lambda: "2026-07-14"

    assert provider._fetch_yesterday_strong_sectors(diagnostics) == []
    assert provider._yesterday_sector_cache_date == "2026-07-13"
    assert provider._yesterday_sector_cache == []
    assert any("sectors=0" in item for item in diagnostics)

    scheduler_diagnostics = []
    assert provider._yesterday_sector_snapshot_or_schedule(scheduler_diagnostics) == []
    assert len(requested) == 1


def test_realtime_provider_fetches_all_yesterday_limit_up_pages():
    requested_pages = []
    first_page = [
        {"c": f"{index:06d}", "n": f"First {index}", "hybk": "First sector", "zdp": "1.00"}
        for index in range(1, 101)
    ]
    second_page = [
        {"c": "600000", "n": "Beyond first page", "hybk": "Second sector", "zdp": "2.00"}
    ]

    def requester(_url, **kwargs):
        page = int(kwargs["params"]["Pageindex"])
        requested_pages.append(page)
        return _Response({"rc": 0, "data": {"count": 101, "pool": first_page if page == 0 else second_page}})

    diagnostics = []
    provider = RealtimeMarketProvider(warehouse=_Warehouse(), requester=requester, timeout=2.0)
    provider._latest_trade_date = lambda: "2026-07-14"

    result = provider._fetch_yesterday_strong_sectors(diagnostics)

    assert requested_pages == [0, 1]
    assert [sector.name for sector in result] == ["First sector", "Second sector"]


def test_realtime_provider_reports_partial_yesterday_limit_up_pool_after_request_budget():
    requested_pages = []

    def requester(_url, **kwargs):
        page = int(kwargs["params"]["Pageindex"])
        requested_pages.append(page)
        pool = [
            {
                "c": f"{page * 100 + index:06d}",
                "n": f"Stock {page}-{index}",
                "hybk": f"Sector {page}",
                "zdp": "1.00",
            }
            for index in range(100)
        ]
        return _Response({"rc": 0, "data": {"count": 301, "pool": pool}})

    diagnostics = []
    provider = RealtimeMarketProvider(warehouse=_Warehouse(), requester=requester, timeout=2.0)
    provider._latest_trade_date = lambda: "2026-07-14"

    provider._fetch_yesterday_strong_sectors(diagnostics)

    assert requested_pages == [0, 1, 2]
    assert any("partial" in item and "300" in item and "301" in item for item in diagnostics)


def test_realtime_provider_does_not_replace_complete_yesterday_cache_with_partial_pool():
    complete_cache = [
        SectorMover(name="Complete sector", change_pct=0.08, source="eastmoney-yesterday-limit-up")
    ]
    requested_pages = []

    def requester(_url, **kwargs):
        page = int(kwargs["params"]["Pageindex"])
        requested_pages.append(page)
        pool = [
            {
                "c": f"{page * 100 + index:06d}",
                "n": f"Partial {page}-{index}",
                "hybk": "Partial sector",
                "zdp": "2.00",
            }
            for index in range(100)
        ]
        return _Response({"rc": 0, "data": {"count": 301, "pool": pool}})

    provider = RealtimeMarketProvider(warehouse=_Warehouse(), requester=requester, timeout=2.0)
    provider._latest_trade_date = lambda: "2026-07-14"
    provider._yesterday_sector_cache_date = "2026-07-13"
    provider._yesterday_sector_cache = complete_cache
    provider._yesterday_sector_cached_at = monotonic() - provider.yesterday_sector_cache_ttl - 1
    cached_at = provider._yesterday_sector_cached_at
    diagnostics = []

    result = provider._fetch_yesterday_strong_sectors(diagnostics)

    assert requested_pages == [0, 1, 2]
    assert result[0].name == "Partial sector"
    assert provider._yesterday_sector_cache == complete_cache
    assert provider._yesterday_sector_cached_at == cached_at
    assert any("partial" in item for item in diagnostics)


def test_realtime_provider_fetches_yesterday_limit_up_sector_tracking():
    requested = []

    def requester(url, **kwargs):
        requested.append((url, kwargs.get("params", {})))
        return _Response(
            {
                "rc": 0,
                "data": {
                    "pool": [
                        {"c": "000001", "n": "Power A", "hybk": "Communication", "zdp": "8.00"},
                        {"c": "000002", "n": "Power B", "hybk": "Communication", "zdp": "2.00"},
                        {"c": "000003", "n": "Gold A", "hybk": "Precious Metals", "zdp": "-1.00"},
                    ]
                },
            }
        )

    diagnostics = []
    provider = RealtimeMarketProvider(warehouse=_Warehouse(), requester=requester, timeout=2.0)

    result = provider._fetch_yesterday_strong_sectors(diagnostics)

    assert [item.name for item in result] == ["Communication", "Precious Metals"]
    assert result[0].change_pct == 0.05
    assert result[0].leading_symbol == "000001"
    assert requested[0][0].endswith("getYesterdayZTPool")
    assert requested[0][1]["date"].isdigit()
    assert result[0].source == "eastmoney-yesterday-limit-up"


def test_realtime_provider_keeps_yesterday_sector_source_in_snapshot():
    provider = RealtimeMarketProvider(
        warehouse=_Warehouse(),
        requester=lambda _url, **_kwargs: _Response({}),
        breadth_time_budget=None,
        sector_time_budget=None,
    )
    provider._latest_trade_date = lambda: "2026-07-14"
    provider._yesterday_sector_cache_date = "2026-07-13"
    provider._yesterday_sector_cached_at = monotonic()
    provider._yesterday_sector_cache = [
        SectorMover(
            name="Communication",
            change_pct=0.05,
            leading_symbol="000001",
            source="eastmoney-yesterday-limit-up",
        )
    ]
    provider._fetch_indexes = lambda: [
        MarketIndexQuote(
            symbol="sh000001",
            name="SSE",
            last=3000,
            previous_close=2990,
            change=10,
            change_pct=10 / 2990,
            source="test-index",
        )
    ]
    provider._fetch_live_breadth = lambda: MarketBreadth(
        up=3500,
        down=1200,
        flat=300,
        total=5000,
        source="test-breadth",
    )
    provider._fetch_live_sectors = lambda: [
        SectorMover(name="AI", change_pct=0.03, source="test-sector")
    ]

    snapshot = provider.market_snapshot()

    assert "eastmoney-yesterday-limit-up" in snapshot.source


def test_realtime_provider_replaces_local_yesterday_note_when_eastmoney_cache_wins():
    provider = RealtimeMarketProvider(warehouse=_Warehouse(), requester=lambda _url, **_kwargs: _Response({}))
    provider._latest_trade_date = lambda: "2026-07-14"
    provider._yesterday_sector_cache_date = "2026-07-13"
    provider._yesterday_sector_cached_at = monotonic()
    provider._yesterday_sector_cache = [
        SectorMover(
            name="Eastmoney sector",
            change_pct=0.05,
            source="eastmoney-yesterday-limit-up",
        )
    ]
    provider._fetch_indexes = lambda: []
    provider._fetch_live_breadth_with_budget = lambda *_args, **_kwargs: None
    provider._fetch_live_sectors_with_budget = lambda *_args, **_kwargs: []
    provider._snapshot_from_local_with_budget = lambda *_args, **_kwargs: RealtimeMarketSnapshot(
        status="stale",
        source="local-latest",
        updated_at=datetime.now(timezone.utc),
        market_phase="trading",
        yesterday_strong_sectors=[
            SectorMover(name="Local sector", change_pct=0.01, source="local-yesterday-group")
        ],
        message="Local fallback. 昨日强势板块追踪来自本地历史。",
    )

    snapshot = provider.market_snapshot()

    assert snapshot.yesterday_strong_sectors[0].source == "eastmoney-yesterday-limit-up"
    assert "昨日强势板块追踪来自东方财富昨日涨停池。" in snapshot.message
    assert "昨日强势板块追踪来自本地历史。" not in snapshot.message
    assert snapshot.message.count("昨日强势板块追踪") == 1


def test_realtime_provider_keeps_valid_empty_eastmoney_cache_over_local_yesterday_sectors():
    provider = RealtimeMarketProvider(warehouse=_Warehouse(), requester=lambda _url, **_kwargs: _Response({}))
    provider._latest_trade_date = lambda: "2026-07-14"
    provider._yesterday_sector_cache_date = "2026-07-13"
    provider._yesterday_sector_cached_at = monotonic()
    provider._yesterday_sector_cache = []
    provider._fetch_indexes = lambda: []
    provider._fetch_live_breadth_with_budget = lambda *_args, **_kwargs: None
    provider._fetch_live_sectors_with_budget = lambda *_args, **_kwargs: []
    provider._snapshot_from_local_with_budget = lambda *_args, **_kwargs: RealtimeMarketSnapshot(
        status="stale",
        source="local-latest",
        updated_at=datetime.now(timezone.utc),
        market_phase="trading",
        yesterday_strong_sectors=[
            SectorMover(name="Local sector", change_pct=0.01, source="local-yesterday-group")
        ],
        message="Local fallback. 昨日强势板块追踪来自本地历史。",
    )

    snapshot = provider.market_snapshot()

    assert snapshot.yesterday_strong_sectors == []
    assert "昨日强势板块追踪" not in snapshot.message


def test_realtime_provider_returns_expired_eastmoney_cache_while_refresh_runs():
    entered = Event()
    release = Event()
    provider = RealtimeMarketProvider(warehouse=_Warehouse(), requester=lambda _url, **_kwargs: _Response({}))
    provider._latest_trade_date = lambda: "2026-07-14"
    provider._yesterday_sector_cache_date = "2026-07-13"
    provider._yesterday_sector_cache = [
        SectorMover(name="Cached sector", change_pct=0.05, source="eastmoney-yesterday-limit-up")
    ]
    provider._yesterday_sector_cached_at = monotonic() - provider.yesterday_sector_cache_ttl - 1

    def refresh(_diagnostics):
        entered.set()
        assert release.wait(timeout=2)
        return []

    provider._fetch_yesterday_strong_sectors = refresh
    diagnostics = []
    try:
        result = provider._yesterday_sector_snapshot_or_schedule(diagnostics)
        assert entered.wait(timeout=2)
        assert result[0].source == "eastmoney-yesterday-limit-up"
        assert any("stale" in item and "cache" in item for item in diagnostics)
    finally:
        release.set()
        for _ in range(20):
            with provider._yesterday_sector_lock:
                if not provider._yesterday_sector_in_flight:
                    break
            sleep(0.01)


def test_realtime_provider_surfaces_background_yesterday_sector_diagnostics():
    completed = Event()
    provider = RealtimeMarketProvider(warehouse=_Warehouse(), requester=lambda _url, **_kwargs: _Response({}))
    provider._latest_trade_date = lambda: "2026-07-14"

    def failed_fetch(diagnostics):
        diagnostics.append("yesterday pool worker failed")
        completed.set()
        return []

    provider._fetch_yesterday_strong_sectors = failed_fetch
    first_diagnostics = []
    provider._yesterday_sector_snapshot_or_schedule(first_diagnostics)
    assert completed.wait(timeout=2)
    for _ in range(20):
        with provider._yesterday_sector_lock:
            if not provider._yesterday_sector_in_flight:
                break
        sleep(0.01)

    second_diagnostics = []
    provider._yesterday_sector_snapshot_or_schedule(second_diagnostics)

    assert "yesterday pool worker failed" in second_diagnostics


def test_realtime_provider_refreshes_cls_home_for_each_market_snapshot():
    calls = 0
    payload = {
        "code": 200,
        "data": {
            "index_quote": [
                {
                    "secu_code": "sh000001",
                    "secu_name": "SSE",
                    "last_px": 3000,
                    "preclose_px": 2990,
                    "change": 0.33,
                }
            ],
            "up_down_dis": {"rise_num": 3200, "fall_num": 1400, "flat_num": 100},
        },
    }

    def requester(_url, **_kwargs):
        nonlocal calls
        calls += 1
        return _Response(payload)

    provider = RealtimeMarketProvider(
        warehouse=_Warehouse(),
        requester=requester,
        breadth_time_budget=None,
        sector_time_budget=None,
    )
    provider._latest_trade_date = lambda: "2026-07-14"
    provider._yesterday_sector_cache_date = "2026-07-13"
    provider._yesterday_sector_cached_at = monotonic()
    provider._yesterday_sector_cache = []
    provider._fetch_live_sectors = lambda _diagnostics: [
        SectorMover(name="Current sector", change_pct=0.01, source="test-sector")
    ]

    first = provider.market_snapshot()
    second = provider.market_snapshot()

    assert first.status == "live"
    assert second.status == "live"
    assert calls >= 2


def test_realtime_provider_does_not_cache_cls_home_error_payload_and_reports_it():
    calls = 0

    def requester(_url, **_kwargs):
        nonlocal calls
        calls += 1
        return _Response({"code": 401, "message": "signature invalid"})

    provider = RealtimeMarketProvider(warehouse=_Warehouse(), requester=requester)
    provider._call_ths_market_summary_breadth = lambda *_args, **_kwargs: None
    provider._fetch_sina_breadth = lambda: None
    provider._fetch_tencent_breadth = lambda _diagnostics: None
    provider._fetch_akshare_breadth_with_timeout = lambda _diagnostics: None
    provider._fetch_heavy_breadth = lambda _diagnostics: None
    diagnostics: list[str] = []

    assert provider._fetch_live_breadth(diagnostics) is None
    assert provider._fetch_live_breadth(diagnostics) is None

    assert calls >= 2
    assert any("cls" in item.lower() and "signature invalid" in item for item in diagnostics)


def test_realtime_provider_merges_retained_breadth_without_replacing_current_fields():
    provider = RealtimeMarketProvider(warehouse=_Warehouse())
    provider._latest_trade_date = lambda: "2026-07-14"
    provider._yesterday_sector_cache_date = "2026-07-13"
    provider._yesterday_sector_cached_at = monotonic()
    provider._yesterday_sector_cache = []
    provider._remember_successful_snapshot(
        RealtimeMarketSnapshot(
            status="live",
            source="retained-snapshot",
            updated_at=datetime.now(timezone.utc),
            market_phase="trading",
            indexes=[MarketIndexQuote(symbol="sh000001", name="Retained index", last=1, source="retained")],
            breadth=MarketBreadth(up=3000, down=1000, flat=100, total=4100, source="retained-breadth"),
            strong_sectors=[SectorMover(name="Retained sector", change_pct=0.01, source="retained")],
            message="retained",
        )
    )
    provider._fetch_indexes = lambda: [
        MarketIndexQuote(symbol="sh000001", name="Current index", last=2, source="current-index")
    ]
    provider._fetch_live_breadth_with_budget = lambda _diagnostics: None
    provider._fetch_live_sectors_with_budget = lambda _diagnostics, _rows: [
        SectorMover(name="Current sector", change_pct=0.02, source="current-sector")
    ]
    provider._snapshot_from_local_with_budget = lambda *_args, **_kwargs: RealtimeMarketSnapshot(
        status="stale",
        source="local-snapshot",
        updated_at=datetime.now(timezone.utc),
        market_phase="trading",
        breadth=MarketBreadth(up=1, down=1, flat=0, total=2, source="local-breadth"),
        message="local",
    )

    snapshot = provider.market_snapshot()

    assert snapshot.status == "stale"
    assert snapshot.indexes[0].name == "Current index"
    assert snapshot.breadth is not None
    assert snapshot.breadth.source == "retained-breadth"
    assert snapshot.strong_sectors[0].name == "Current sector"
    assert snapshot.source.endswith("+retained-last-success")
    assert any("沿用最近成功行情快照" in item for item in snapshot.diagnostics)


def test_realtime_provider_merges_retained_indexes_without_replacing_current_fields():
    provider = RealtimeMarketProvider(warehouse=_Warehouse())
    provider._latest_trade_date = lambda: "2026-07-14"
    provider._yesterday_sector_cache_date = "2026-07-13"
    provider._yesterday_sector_cached_at = monotonic()
    provider._yesterday_sector_cache = []
    provider._remember_successful_snapshot(
        RealtimeMarketSnapshot(
            status="live",
            source="retained-snapshot",
            updated_at=datetime.now(timezone.utc),
            market_phase="trading",
            indexes=[MarketIndexQuote(symbol="sh000001", name="Retained index", last=1, source="retained")],
            breadth=MarketBreadth(up=3000, down=1000, flat=100, total=4100, source="retained-breadth"),
            strong_sectors=[SectorMover(name="Retained sector", change_pct=0.01, source="retained")],
            message="retained",
        )
    )
    provider._fetch_indexes = lambda: []
    provider._fetch_live_breadth_with_budget = lambda _diagnostics: MarketBreadth(
        up=3200,
        down=1100,
        flat=100,
        total=4400,
        source="current-breadth",
    )
    provider._fetch_live_sectors_with_budget = lambda _diagnostics, _rows: [
        SectorMover(name="Current sector", change_pct=0.02, source="current-sector")
    ]
    provider._snapshot_from_local_with_budget = lambda *_args, **_kwargs: RealtimeMarketSnapshot(
        status="stale",
        source="local-snapshot",
        updated_at=datetime.now(timezone.utc),
        market_phase="trading",
        indexes=[MarketIndexQuote(symbol="sh000001", name="Local index", last=3, source="local")],
        breadth=MarketBreadth(up=1, down=1, flat=0, total=2, source="local-breadth"),
        strong_sectors=[SectorMover(name="Local sector", change_pct=0.01, source="local")],
        message="local",
    )

    snapshot = provider.market_snapshot()

    assert snapshot.status == "stale"
    assert snapshot.indexes[0].name == "Retained index"
    assert snapshot.breadth is not None
    assert snapshot.breadth.source == "current-breadth"
    assert snapshot.strong_sectors[0].name == "Current sector"
    assert snapshot.source.endswith("+retained-last-success")
    assert any("沿用最近成功行情快照" in item for item in snapshot.diagnostics)


def test_realtime_provider_reads_yesterday_cache_atomically_after_scheduling_refresh():
    provider = RealtimeMarketProvider(
        warehouse=_Warehouse(),
        breadth_time_budget=None,
        sector_time_budget=None,
    )
    provider._latest_trade_date = lambda: "2026-07-14"
    fresh_yesterday_sectors = [
        SectorMover(
            name="Fresh Eastmoney sector",
            change_pct=0.02,
            source="eastmoney-yesterday-limit-up",
        )
    ]

    def schedule_refresh(_diagnostics):
        with provider._yesterday_sector_lock:
            provider._yesterday_sector_cache_date = "2026-07-13"
            provider._yesterday_sector_cache = fresh_yesterday_sectors
            provider._yesterday_sector_cached_at = monotonic()
        return []

    provider._yesterday_sector_snapshot_or_schedule = schedule_refresh
    provider._fetch_indexes = lambda: [
        MarketIndexQuote(symbol="sh000001", name="Current index", last=2, source="current-index")
    ]
    provider._fetch_live_breadth_with_budget = lambda _diagnostics: MarketBreadth(
        up=3200,
        down=1100,
        flat=100,
        total=4400,
        source="current-breadth",
    )
    provider._fetch_live_sectors_with_budget = lambda _diagnostics, _rows: [
        SectorMover(name="Current sector", change_pct=0.02, source="current-sector")
    ]

    snapshot = provider.market_snapshot()

    assert snapshot.yesterday_strong_sectors == fresh_yesterday_sectors


def test_realtime_provider_does_not_cache_unusable_cls_home_payload_and_reports_diagnostics():
    calls = 0

    def requester(_url, **_kwargs):
        nonlocal calls
        calls += 1
        return _Response({"code": 200, "data": {"index_quote": [], "up_down_dis": {}}})

    provider = RealtimeMarketProvider(warehouse=_Warehouse(), requester=requester)
    provider._call_ths_market_summary_breadth = lambda *_args, **_kwargs: None
    provider._fetch_sina_breadth = lambda: None
    provider._fetch_tencent_breadth = lambda _diagnostics: None
    provider._fetch_akshare_breadth_with_timeout = lambda _diagnostics: None
    provider._fetch_heavy_breadth = lambda _diagnostics: None
    diagnostics: list[str] = []

    assert provider._fetch_live_breadth(diagnostics) is None
    assert provider._fetch_live_breadth(diagnostics) is None

    assert calls >= 2
    assert any("cls" in item.lower() and "no usable" in item.lower() for item in diagnostics)


@pytest.mark.parametrize(
    "data",
    [
        {
            "index_quote": [
                {
                    "secu_code": "sh000001",
                    "secu_name": "SSE",
                    "last_px": 3000,
                    "preclose_px": 2990,
                    "change": 0.33,
                }
            ],
            "up_down_dis": {},
        },
        {"index_quote": [], "up_down_dis": {"rise_num": 0, "fall_num": 0, "flat_num": 8}},
    ],
)
def test_realtime_provider_caches_usable_partial_cls_home_payload(data):
    calls = 0

    def requester(_url, **_kwargs):
        nonlocal calls
        calls += 1
        return _Response({"code": 200, "data": data})

    provider = RealtimeMarketProvider(warehouse=_Warehouse(), requester=requester)

    assert provider._fetch_cls_home_payload()["data"] == data
    assert provider._fetch_cls_home_payload()["data"] == data
    assert calls == 1


def test_realtime_provider_does_not_cache_yesterday_limit_up_logical_failure():
    calls = 0

    def requester(_url, **_kwargs):
        nonlocal calls
        calls += 1
        return _Response({"rc": 1, "message": "upstream rejected request", "data": {"tc": 0, "pool": []}})

    provider = RealtimeMarketProvider(warehouse=_Warehouse(), requester=requester, timeout=2.0)
    provider._latest_trade_date = lambda: "2026-07-14"
    diagnostics: list[str] = []

    assert provider._fetch_yesterday_strong_sectors(diagnostics) == []
    assert provider._fetch_yesterday_strong_sectors(diagnostics) == []

    assert calls == 2
    assert provider._yesterday_sector_cache_date is None
    assert any("rc=1" in item for item in diagnostics)
