from __future__ import annotations

from datetime import UTC, datetime
from threading import Event, Thread

import pandas as pd
import pytest
import requests
from astock_backtester.data.realtime import (
    HeavyMarketCrawlerProvider,
    RealtimeMarketProvider,
    unavailable_market_snapshot,
)
from astock_backtester.data.warehouse import Warehouse
from astock_backtester.models import (
    MarketBreadth,
    MarketIndexQuote,
    RealtimeMarketSnapshot,
)


class HtmlResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code
        self.encoding = "utf-8"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(f"HTTP {self.status_code}", response=response)


def test_ths_market_breadth_uses_explicit_alternate_transport_after_403(tmp_path):
    def primary(_url: str, **_kwargs):
        return HtmlResponse("forbidden", status_code=403)

    def alternate(_url: str, **_kwargs):
        return HtmlResponse("上涨 3200 下跌 1800 平盘 120")

    diagnostics: list[str] = []
    provider = RealtimeMarketProvider(
        Warehouse(tmp_path),
        requester=primary,
        alternate_requester=alternate,
        allow_alternate_transport=True,
    )

    breadth = provider._fetch_ths_market_summary_breadth(diagnostics=diagnostics)

    assert breadth is not None
    assert (breadth.up, breadth.down, breadth.flat, breadth.total) == (3200, 1800, 120, 5120)
    assert any("alternate transport used" in item for item in diagnostics)


def test_sector_chain_stops_before_next_source_after_cancellation(tmp_path):
    cancelled = Event()
    calls: list[str] = []
    provider = RealtimeMarketProvider(Warehouse(tmp_path))

    def empty_cls(_diagnostics):
        calls.append("cls")
        cancelled.set()
        return []

    provider._fetch_cls_hot_plate_sectors = empty_cls
    provider._fetch_ths_concept_section_rows = lambda: calls.append("ths") or []

    sectors = provider._fetch_live_sectors([], cancel_event=cancelled)

    assert sectors == []
    assert calls == ["cls"]


def test_cancelled_ths_response_is_not_published_to_request_cache(tmp_path):
    cancelled = Event()
    provider = RealtimeMarketProvider(Warehouse(tmp_path))

    def late_response(*_args, **_kwargs):
        cancelled.set()
        return HtmlResponse(
            '<div id="gnSection" '
            'value=\'{"gn_1":{"platename":"算力","platecode":"301558","199112":"3.2"}}\'></div>'
        )

    provider._request_public_html = late_response

    rows = provider._fetch_ths_concept_section_rows(
        diagnostics=[],
        cancel_event=cancelled,
    )

    assert rows == []
    assert not hasattr(provider, "_ths_concept_rows_cache")


def test_sector_worker_does_not_publish_rows_after_wrapper_timeout(tmp_path):
    started = Event()
    release = Event()
    cancellation_observed = Event()
    wrapper_finished = Event()
    provider = RealtimeMarketProvider(Warehouse(tmp_path), sector_time_budget=0.2)
    provider._fetch_cls_hot_plate_sectors = lambda _diagnostics: []
    original_cancelled = provider._source_chain_cancelled

    def observe_cancellation(cancel_event, deadline, diagnostics, chain):
        cancelled = original_cancelled(cancel_event, deadline, diagnostics, chain)
        if cancelled and chain == "strong-sector":
            cancellation_observed.set()
        return cancelled

    provider._source_chain_cancelled = observe_cancellation

    def late_rows():
        started.set()
        release.wait(timeout=1)
        return [
            {
                "f12": "301558",
                "f14": "算力",
                "change_pct": "3.2",
                "_change_pct_unit": "percent",
            }
        ]

    provider._fetch_ths_concept_section_rows = late_rows

    diagnostics: list[str] = []
    rows_out: list[dict] = []
    results: list[list] = []

    def fetch_with_budget() -> None:
        results.append(provider._fetch_live_sectors_with_budget(diagnostics, rows_out))
        wrapper_finished.set()

    wrapper = Thread(target=fetch_with_budget)
    wrapper.start()
    assert started.wait(timeout=1)
    assert wrapper_finished.wait(timeout=1)
    assert results == [[]]
    release.set()
    assert cancellation_observed.wait(timeout=1)
    wrapper.join(timeout=1)

    assert rows_out == []


def test_sector_timeout_cannot_commit_rows_after_publication_check(tmp_path):
    publication_check_passed = Event()
    release_publication = Event()
    wrapper_finished = Event()
    worker_finished = Event()
    provider = RealtimeMarketProvider(Warehouse(tmp_path), sector_time_budget=0.1)
    provider._fetch_cls_hot_plate_sectors = lambda _diagnostics: []
    provider._fetch_ths_concept_section_rows = lambda: [
        {
            "f12": "301558",
            "f14": "算力",
            "change_pct": "3.2",
            "_change_pct_unit": "percent",
        }
    ]

    original_cancelled = provider._source_chain_cancelled
    strong_sector_checks = 0

    def pause_after_publication_check(cancel_event, deadline, diagnostics, chain):
        nonlocal strong_sector_checks
        cancelled = original_cancelled(cancel_event, deadline, diagnostics, chain)
        if chain == "strong-sector" and not cancelled:
            strong_sector_checks += 1
            if strong_sector_checks == 4:
                publication_check_passed.set()
                release_publication.wait(timeout=1)
        return cancelled

    original_call = provider._call_live_sectors

    def tracked_call(*args, **kwargs):
        try:
            return original_call(*args, **kwargs)
        finally:
            worker_finished.set()

    provider._source_chain_cancelled = pause_after_publication_check
    provider._call_live_sectors = tracked_call

    rows_out: list[dict] = []
    results: list[list] = []

    def fetch_with_budget() -> None:
        results.append(provider._fetch_live_sectors_with_budget([], rows_out))
        wrapper_finished.set()

    wrapper = Thread(target=fetch_with_budget)
    wrapper.start()
    assert publication_check_passed.wait(timeout=1)
    assert wrapper_finished.wait(timeout=1)
    assert results == [[]]
    release_publication.set()
    assert worker_finished.wait(timeout=1)
    wrapper.join(timeout=1)

    assert rows_out == []


def test_older_realtime_request_cannot_overwrite_newer_success_snapshot(tmp_path):
    provider = RealtimeMarketProvider(Warehouse(tmp_path))
    newer = RealtimeMarketSnapshot(
        status="live",
        source="newer",
        updated_at=datetime(2026, 7, 10, 10, 1, tzinfo=UTC),
        message="newer",
    )
    older = RealtimeMarketSnapshot(
        status="live",
        source="older",
        updated_at=datetime(2026, 7, 10, 10, 0, tzinfo=UTC),
        message="older",
    )

    provider._remember_successful_snapshot(newer)
    provider._remember_successful_snapshot(older)

    assert provider._retained_successful_snapshot().source == "newer"


def test_late_breadth_worker_cannot_publish_diagnostics_after_timeout(tmp_path):
    """P1-3: after _fetch_live_breadth_with_budget times out, the late
    worker thread must NOT be able to append diagnostics to the shared
    list.  Uses deterministic Events instead of sleep-based timing.
    """
    worker_started = Event()
    wrapper_returned = Event()
    release_worker = Event()
    provider = RealtimeMarketProvider(Warehouse(tmp_path), breadth_time_budget=0.1)

    def slow_fetcher(diagnostics, deadline=None, cancel_event=None):
        worker_started.set()
        # Wait until the wrapper has already returned before attempting
        # to write to diagnostics.
        release_worker.wait(timeout=2)
        # This append MUST be silently dropped by the guarded list.
        diagnostics.append("late-worker-diagnostic-should-be-dropped")
        return None

    provider._call_live_breadth = slow_fetcher

    diagnostics: list[str] = []

    def run_wrapper():
        provider._fetch_live_breadth_with_budget(diagnostics)
        wrapper_returned.set()

    thread = Thread(target=run_wrapper)
    thread.start()
    assert worker_started.wait(timeout=2)
    assert wrapper_returned.wait(timeout=2)

    # The wrapper has returned; now let the worker try to write.
    release_worker.set()
    thread.join(timeout=2)

    assert "late-worker-diagnostic-should-be-dropped" not in diagnostics, (
        "P1-3 regression: late worker published diagnostics after wrapper timeout"
    )
    # The timeout diagnostic from the wrapper itself must be present.
    assert any("超时" in d for d in diagnostics)


def test_late_sector_worker_cannot_publish_diagnostics_after_timeout(tmp_path):
    """P1-3: same guard for sector budget wrapper."""
    worker_started = Event()
    wrapper_returned = Event()
    release_worker = Event()
    provider = RealtimeMarketProvider(Warehouse(tmp_path), sector_time_budget=0.1)
    provider._fetch_cls_hot_plate_sectors = lambda _diagnostics: []

    def slow_sector_fetcher(diagnostics, deadline=None, cancel_event=None, sector_rows_out=None):
        worker_started.set()
        release_worker.wait(timeout=2)
        diagnostics.append("late-sector-diagnostic-should-be-dropped")
        return []

    provider._call_live_sectors = slow_sector_fetcher

    diagnostics: list[str] = []
    rows_out: list[dict] = []

    def run_wrapper():
        provider._fetch_live_sectors_with_budget(diagnostics, rows_out)
        wrapper_returned.set()

    thread = Thread(target=run_wrapper)
    thread.start()
    assert worker_started.wait(timeout=2)
    assert wrapper_returned.wait(timeout=2)
    release_worker.set()
    thread.join(timeout=2)

    assert "late-sector-diagnostic-should-be-dropped" not in diagnostics, (
        "P1-3 regression: late sector worker published diagnostics after timeout"
    )
    assert any("超时" in d for d in diagnostics)


def test_retained_snapshot_preserves_original_diagnostics(tmp_path):
    """P1-2: retained snapshot must merge current request diagnostics,
    original successful snapshot diagnostics, and the retained time hint.
    The original diagnostics must NOT be silently dropped.
    """
    provider = RealtimeMarketProvider(Warehouse(tmp_path))

    # Store a successful snapshot with its own diagnostics
    original_snapshot = RealtimeMarketSnapshot(
        status="live",
        source="cls-quote-index",
        updated_at=datetime(2026, 7, 10, 10, 0, tzinfo=UTC),
        message="live",
        indexes=[
            MarketIndexQuote(
                symbol="sh000001",
                name="上证指数",
                last=3100.0,
                previous_close=3080.0,
                change=20.0,
                change_pct=0.0065,
                source="cls-quote-index",
            )
        ],
        breadth=MarketBreadth(up=3000, down=1800, flat=200, total=5000, source="cls-quote-breadth"),
        strong_sectors=[],
        diagnostics=["原始成功快照诊断信息"],
    )
    provider._remember_successful_snapshot(original_snapshot)

    # Make all live fetchers return empty so the retained path is triggered
    provider._fetch_indexes = lambda: []
    provider._fetch_live_breadth_with_budget = lambda diagnostics: None
    provider._fetch_live_sectors_with_budget = lambda diagnostics, rows_out: []

    def empty_local(now, diagnostics, live_sector_rows, skip_topic_fetch=False):
        return unavailable_market_snapshot("本地无数据", diagnostics=[])

    provider._snapshot_from_local_with_budget = empty_local

    events = list(provider.market_snapshot_events())
    result_event = events[-1]
    assert result_event["type"] == "result"
    snapshot = result_event["snapshot"]

    # The retained snapshot must contain:
    # 1. Current request diagnostics (e.g. "实时指数接口暂不可用...")
    assert any("实时指数接口暂不可用" in d for d in snapshot.diagnostics)
    # 2. Original snapshot diagnostics (must NOT be silently dropped)
    assert "原始成功快照诊断信息" in snapshot.diagnostics, (
        "P1-2 regression: original successful snapshot diagnostics were lost"
    )
    # 3. Retained time hint
    assert any("沿用最近成功行情快照" in d for d in snapshot.diagnostics)

    # Order must be stable and no duplicates
    seen = set()
    for d in snapshot.diagnostics:
        if d in seen:
            pytest.fail(f"Duplicate diagnostic entry: {d!r}")
        seen.add(d)


def test_same_timestamp_reverse_completion_does_not_overwrite(tmp_path):
    """P1-4: when two requests have the same updated_at timestamp and
    the older-generation request completes AFTER the newer one, it must
    NOT overwrite the cached snapshot.  Uses monotonic generation.
    """
    provider = RealtimeMarketProvider(Warehouse(tmp_path))
    same_ts = datetime(2026, 7, 10, 10, 0, tzinfo=UTC)

    # Request 1 (generation=1) completes first
    first = RealtimeMarketSnapshot(
        status="live", source="gen-1", updated_at=same_ts, message="first"
    )
    provider._remember_successful_snapshot(first, generation=1)
    assert provider._retained_successful_snapshot().source == "gen-1"

    # Request 2 (generation=2) with SAME timestamp completes later
    second = RealtimeMarketSnapshot(
        status="live", source="gen-2", updated_at=same_ts, message="second"
    )
    provider._remember_successful_snapshot(second, generation=2)
    assert provider._retained_successful_snapshot().source == "gen-2"

    # Old request (generation=1) arrives late — must NOT overwrite gen-2
    late_old = RealtimeMarketSnapshot(
        status="live", source="gen-1-late", updated_at=same_ts, message="late"
    )
    provider._remember_successful_snapshot(late_old, generation=1)
    assert provider._retained_successful_snapshot().source == "gen-2", (
        "P1-4 regression: old request (gen=1) overwrote newer (gen=2)"
    )


def test_remember_without_generation_uses_strict_timestamp(tmp_path):
    """P1-4: backward-compatible calls without generation use strict
    greater-than comparison, so same-timestamp cannot overwrite.
    """
    provider = RealtimeMarketProvider(Warehouse(tmp_path))
    same_ts = datetime(2026, 7, 10, 10, 0, tzinfo=UTC)

    first = RealtimeMarketSnapshot(
        status="live", source="first", updated_at=same_ts, message="first"
    )
    provider._remember_successful_snapshot(first)

    second = RealtimeMarketSnapshot(
        status="live", source="second", updated_at=same_ts, message="second"
    )
    provider._remember_successful_snapshot(second)

    # With strict >, the first snapshot is kept (second has same ts, not >)
    assert provider._retained_successful_snapshot().source == "first", (
        "P1-4 regression: same-timestamp request overwrote existing snapshot"
    )


# ---------------------------------------------------------------------------
# Round-2 concurrency hardening: no shared cache writes after timeout.
# ---------------------------------------------------------------------------


def test_heavy_breadth_success_does_not_populate_shared_cache():
    """The breadth worker must not write any cross-request shared cache.

    ``HeavyMarketCrawlerProvider`` is cached on the provider instance and is
    invoked from the breadth worker thread.  A successful fetch must not
    mutate a shared ``_last_successful_breadth`` field, otherwise a timed-out
    worker could publish a late cache write.
    """

    def requester(_url, **_kwargs):
        return HtmlResponse("上涨 3200 下跌 1800 平盘 120")

    provider = HeavyMarketCrawlerProvider(requester=requester, timeout=0.5)

    breadth = provider.fetch_breadth()

    assert breadth is not None
    assert (breadth.up, breadth.down, breadth.flat) == (3200, 1800, 120)
    assert provider._last_successful_breadth is None, (
        "breadth worker published a cross-request shared cache write"
    )


def test_expired_board_member_context_is_not_committed_to_shared_cache(tmp_path):
    """A cancelled/expired request must not publish sector members to the
    shared ``_sector_member_cache``.  The freshly read members are still
    returned to the current worker, but they are not cached globally."""
    provider = RealtimeMarketProvider(Warehouse(tmp_path))
    provider._fetch_ths_board_members = lambda _code: ["600000", "600001"]

    cancelled = Event()
    cancelled.set()

    members = provider._fetch_board_members("881234", cancel_event=cancelled)

    assert members == ["600000", "600001"]
    assert "881234" not in provider._sector_member_cache, (
        "cancelled request published a late sector-member cache write"
    )


def test_ready_board_member_context_is_committed_to_shared_cache(tmp_path):
    """When the request is still in budget, sector members are cached so the
    optimisation keeps working."""
    provider = RealtimeMarketProvider(Warehouse(tmp_path))
    provider._fetch_ths_board_members = lambda _code: ["600000"]

    members = provider._fetch_board_members("881234")

    assert members == ["600000"]
    assert provider._sector_member_cache.get("881234") == ["600000"]


def _fake_local_bars() -> pd.DataFrame:
    rows = []
    for offset, close in ((2, 10.0), (1, 10.5), (0, 11.0)):
        trade_date = pd.Timestamp("2026-06-05") - pd.Timedelta(days=offset)
        for symbol, base in (("600000", 1.0), ("600001", 2.0)):
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "open": close * base,
                    "high": close * base * 1.02,
                    "low": close * base * 0.98,
                    "close": close * base,
                    "volume": 1000,
                }
            )
    return pd.DataFrame(rows)


def test_local_snapshot_timeout_blocks_late_sector_member_cache_write(tmp_path):
    """When the local-snapshot wrapper times out, the still-running worker
    must NOT publish a late write to the shared ``_sector_member_cache``.

    Deterministic: the board-member HTTP call blocks on an Event until after
    the wrapper has already returned its timeout fallback.
    """
    bars = _fake_local_bars()

    class FakeWarehouse:
        def read_latest_daily_bars(self, days: int = 3) -> pd.DataFrame:
            return bars

    started = Event()
    release = Event()
    snapshot_worker_done = Event()

    provider = RealtimeMarketProvider(FakeWarehouse(), local_snapshot_time_budget=0.1)
    provider._coverage_symbol_count = lambda: 2

    def blocking_members(_board_code: str) -> list[str]:
        started.set()
        release.wait(timeout=2)
        return ["600000", "600001"]

    provider._fetch_ths_board_members = blocking_members

    real_local = provider._snapshot_from_local

    def traced_local(*args, **kwargs):
        try:
            return real_local(*args, **kwargs)
        finally:
            snapshot_worker_done.set()

    provider._snapshot_from_local = traced_local

    diagnostics: list[str] = []
    sector_rows = [{"f12": "881234", "f14": "算力", "change_pct": "3.2"}]

    snapshot = provider._snapshot_from_local_with_budget(
        datetime.now(UTC),
        diagnostics,
        sector_rows,
        skip_topic_fetch=True,
    )

    assert started.wait(timeout=2)
    assert any("本地兜底行情快照超时" in item for item in diagnostics)
    assert snapshot.status == "unavailable"

    # Let the timed-out worker finish and attempt its (now-forbidden) write.
    release.set()
    assert snapshot_worker_done.wait(timeout=2)

    assert provider._sector_member_cache == {}, (
        "timed-out local snapshot worker published a late sector-member cache write"
    )


def test_late_breadth_worker_writes_only_private_diagnostics(tmp_path):
    """After the breadth wrapper times out, the worker's diagnostics list is
    private and never merged into the shared diagnostics list."""
    worker_started = Event()
    wrapper_returned = Event()
    release_worker = Event()
    worker_done = Event()
    provider = RealtimeMarketProvider(Warehouse(tmp_path), breadth_time_budget=0.1)

    def slow_fetcher(diagnostics, deadline=None, cancel_event=None):
        worker_started.set()
        release_worker.wait(timeout=2)
        diagnostics.append("late-breadth-private-diagnostic")
        worker_done.set()
        return None

    provider._call_live_breadth = slow_fetcher

    shared_diagnostics: list[str] = []

    def run_wrapper():
        provider._fetch_live_breadth_with_budget(shared_diagnostics)
        wrapper_returned.set()

    thread = Thread(target=run_wrapper)
    thread.start()
    assert worker_started.wait(timeout=2)
    assert wrapper_returned.wait(timeout=2)
    release_worker.set()
    assert worker_done.wait(timeout=2)
    thread.join(timeout=2)

    assert "late-breadth-private-diagnostic" not in shared_diagnostics
    assert any("超时" in item for item in shared_diagnostics)


def test_mixed_generation_then_timestamp_arbitration(tmp_path):
    """Mixed usage: generation-tracked writes and legacy timestamp writes must
    arbitrate consistently.  A legacy (no-generation) call must NEVER overwrite
    a generation-tracked snapshot, regardless of wall-clock timestamp.  This
    prevents the gen5→legacy新时间→gen6旧时间 rollback bug."""
    provider = RealtimeMarketProvider(Warehouse(tmp_path))
    t0 = datetime(2026, 7, 10, 10, 0, tzinfo=UTC)
    t1 = datetime(2026, 7, 10, 10, 1, tzinfo=UTC)

    provider._remember_successful_snapshot(
        RealtimeMarketSnapshot(status="live", source="gen-5", updated_at=t0, message="g5"),
        generation=5,
    )
    # Legacy with same timestamp must not overwrite
    provider._remember_successful_snapshot(
        RealtimeMarketSnapshot(
            status="live", source="no-gen-stale", updated_at=t0, message="stale"
        ),
    )
    assert provider._retained_successful_snapshot().source == "gen-5"

    # Legacy with NEWER timestamp must also NOT overwrite generation-tracked
    provider._remember_successful_snapshot(
        RealtimeMarketSnapshot(
            status="live", source="no-gen-fresh", updated_at=t1, message="fresh"
        ),
    )
    # Round-4: legacy calls can never clobber generation-tracked snapshots
    assert provider._retained_successful_snapshot().source == "gen-5", (
        "Round-4: legacy call with newer timestamp must not overwrite generation-tracked snapshot"
    )


# ---------------------------------------------------------------------------
# Round-4 tests — must fail on current implementation before fixes.
# ---------------------------------------------------------------------------


def test_gen5_legacy_newer_timestamp_must_not_overwrite_gen6_generation_tracked(tmp_path):
    """Round-4: gen=5 (no-generation legacy call) with a newer wall-clock
    timestamp (t=10:05) must NOT overwrite gen=6 (generation-tracked) with
    an older timestamp (t=10:00).  The generation-tracked snapshot is
    authoritative; a legacy call — regardless of wall clock — must not
    clobber it.
    """
    provider = RealtimeMarketProvider(Warehouse(tmp_path))
    t_old = datetime(2026, 7, 10, 10, 0, tzinfo=UTC)
    t_new = datetime(2026, 7, 10, 10, 5, tzinfo=UTC)

    # gen=6 with older timestamp arrives first
    provider._remember_successful_snapshot(
        RealtimeMarketSnapshot(
            status="live", source="gen-6", updated_at=t_old, message="gen6"
        ),
        generation=6,
    )
    assert provider._retained_successful_snapshot().source == "gen-6"

    # gen=5 legacy (no generation) with NEWER timestamp arrives late
    provider._remember_successful_snapshot(
        RealtimeMarketSnapshot(
            status="live", source="gen-5-legacy", updated_at=t_new, message="legacy-newer"
        ),
    )
    # BUG: the legacy call with newer timestamp must NOT overwrite gen-6
    assert provider._retained_successful_snapshot().source == "gen-6", (
        "Round-4 regression: gen=5 legacy (newer ts) overwrote gen=6 generation-tracked"
    )


def test_retained_diagnostics_dedup_includes_current_self_duplicates(tmp_path):
    """Round-4: when the current request diagnostics list itself contains
    duplicate entries, the deduplication must remove them.  Only then are
    the original snapshot diagnostics and the retained hint merged.
    """
    provider = RealtimeMarketProvider(Warehouse(tmp_path))

    # Store a successful snapshot with its own diagnostics
    original_snapshot = RealtimeMarketSnapshot(
        status="live",
        source="cls-quote-index",
        updated_at=datetime(2026, 7, 10, 10, 0, tzinfo=UTC),
        message="live",
        indexes=[
            MarketIndexQuote(
                symbol="sh000001",
                name="上证指数",
                last=3100.0,
                previous_close=3080.0,
                change=20.0,
                change_pct=0.0065,
                source="cls-quote-index",
            )
        ],
        breadth=MarketBreadth(up=3000, down=1800, flat=200, total=5000, source="cls-quote-breadth"),
        strong_sectors=[],
        diagnostics=["原始成功快照诊断信息"],
    )
    provider._remember_successful_snapshot(original_snapshot)

    # Make all live fetchers return empty
    provider._fetch_indexes = lambda: []
    provider._fetch_live_breadth_with_budget = lambda diagnostics: None
    provider._fetch_live_sectors_with_budget = lambda diagnostics, rows_out: []

    call_count = [0]

    def injecting_local(now, diagnostics, live_sector_rows, skip_topic_fetch=False):
        call_count[0] += 1
        # Inject a duplicate into the current diagnostics list
        diagnostics.append("dup-once")
        diagnostics.append("dup-once")
        diagnostics.append("dup-once")  # three identical copies
        diagnostics.append("unique-current")
        return unavailable_market_snapshot("本地无数据", diagnostics=[])

    provider._snapshot_from_local_with_budget = injecting_local

    events = list(provider.market_snapshot_events())
    result_event = events[-1]
    assert result_event["type"] == "result"
    snapshot = result_event["snapshot"]

    # "dup-once" must appear exactly once, not three times
    dup_count = sum(1 for item in snapshot.diagnostics if item == "dup-once")
    assert dup_count == 1, (
        f"Round-4 regression: current diagnostic 'dup-once' appears {dup_count} "
        f"times — current self-duplicates must be removed before merge"
    )

    # "unique-current" must still be present
    assert "unique-current" in snapshot.diagnostics

    # Original diagnostic must also be present
    assert "原始成功快照诊断信息" in snapshot.diagnostics


def test_single_flight_breadth_rejects_second_concurrent_request(tmp_path):
    """Round-4: when the breadth slot is already busy with a worker, a
    second concurrent request must return None immediately instead of
    creating another thread.  The in-flight lock enforces single-flight.
    """
    started = Event()
    release = Event()
    first_returned = Event()

    provider = RealtimeMarketProvider(Warehouse(tmp_path), breadth_time_budget=2.0)

    def blocking_fetcher(diagnostics, deadline=None, cancel_event=None):
        started.set()
        release.wait(timeout=2)
        return MarketBreadth(up=100, down=50, flat=10, total=160, source="test")

    provider._call_live_breadth = blocking_fetcher

    diagnostics_1: list[str] = []
    diagnostics_2: list[str] = []

    def first_call():
        provider._fetch_live_breadth_with_budget(diagnostics_1)
        first_returned.set()

    thread_1 = Thread(target=first_call)
    thread_1.start()
    assert started.wait(timeout=2)

    # Second call while first is still in-flight — must return None immediately
    result_2 = provider._fetch_live_breadth_with_budget(diagnostics_2)
    assert result_2 is None, (
        "Round-4: second concurrent breadth request must return None (single-flight)"
    )
    assert any("繁忙" in item for item in diagnostics_2), (
        "Round-4: single-flight rejection must emit a busy diagnostic"
    )

    release.set()
    assert first_returned.wait(timeout=2)
    thread_1.join(timeout=2)

    # The first call must have succeeded
    assert diagnostics_1 == [] or any(
        item not in diagnostics_1 for item in diagnostics_1
    )  # no "busy" message for first
    assert "实时红绿家数接口繁忙" not in str(diagnostics_1)


def test_single_flight_remains_busy_after_wrapper_timeout_until_worker_finishes(tmp_path):
    worker_started = Event()
    release_worker = Event()
    calls = 0
    provider = RealtimeMarketProvider(Warehouse(tmp_path), breadth_time_budget=0.02)

    def blocking_fetcher(diagnostics, deadline=None, cancel_event=None):
        nonlocal calls
        calls += 1
        worker_started.set()
        release_worker.wait(timeout=2)
        return MarketBreadth(up=100, down=50, flat=10, total=160, source="test")

    provider._call_live_breadth = blocking_fetcher
    first_diagnostics: list[str] = []
    second_diagnostics: list[str] = []

    assert provider._fetch_live_breadth_with_budget(first_diagnostics) is None
    assert worker_started.is_set()
    assert any("超时" in item for item in first_diagnostics)

    assert provider._fetch_live_breadth_with_budget(second_diagnostics) is None
    assert any("繁忙" in item for item in second_diagnostics)
    assert calls == 1, "the second request must not be queued behind the timed-out worker"

    release_worker.set()


def test_single_flight_sector_rejects_second_concurrent_request(tmp_path):
    """Round-4: single-flight for sector budget wrapper."""
    started = Event()
    release = Event()
    first_returned = Event()

    provider = RealtimeMarketProvider(Warehouse(tmp_path), sector_time_budget=2.0)
    provider._fetch_cls_hot_plate_sectors = lambda _diagnostics: []

    def blocking_fetcher(diagnostics, deadline=None, cancel_event=None, sector_rows_out=None):
        started.set()
        release.wait(timeout=2)
        return []

    provider._call_live_sectors = blocking_fetcher

    diagnostics_2: list[str] = []

    def first_call():
        provider._fetch_live_sectors_with_budget([], None)
        first_returned.set()

    thread_1 = Thread(target=first_call)
    thread_1.start()
    assert started.wait(timeout=2)

    result_2 = provider._fetch_live_sectors_with_budget(diagnostics_2, None)
    assert result_2 == [], (
        "Round-4: second concurrent sector request must return empty (single-flight)"
    )
    assert any("繁忙" in item for item in diagnostics_2)

    release.set()
    assert first_returned.wait(timeout=2)
    thread_1.join(timeout=2)


def test_single_flight_local_snapshot_rejects_second_concurrent_request(tmp_path):
    """Round-4: single-flight for local snapshot budget wrapper."""
    started = Event()
    release = Event()
    first_returned = Event()

    provider = RealtimeMarketProvider(Warehouse(tmp_path), local_snapshot_time_budget=2.0)

    def blocking_snapshot(*args, **kwargs):
        started.set()
        release.wait(timeout=2)
        return unavailable_market_snapshot("done")

    provider._call_snapshot_from_local = blocking_snapshot

    diagnostics_2: list[str] = []

    def first_call():
        provider._snapshot_from_local_with_budget(datetime.now(UTC), [])
        first_returned.set()

    thread_1 = Thread(target=first_call)
    thread_1.start()
    assert started.wait(timeout=2)

    result_2 = provider._snapshot_from_local_with_budget(datetime.now(UTC), diagnostics_2)
    assert result_2.status == "unavailable", (
        "Round-4: second concurrent local snapshot must return unavailable (single-flight)"
    )
    assert any("繁忙" in item for item in diagnostics_2)

    release.set()
    assert first_returned.wait(timeout=2)
    thread_1.join(timeout=2)


def test_breadth_submit_delay_does_not_exceed_deadline(tmp_path):
    """Round-4: when executor.submit() is delayed (e.g. under load), the
    remaining-budget calculation must shrink accordingly.  The wrapper uses
    `remaining = deadline - monotonic()` as the result timeout, so a
    delayed submit gets less (or zero) remaining time and cannot silently
    exceed the global breadth budget.
    """
    # We artificially delay the submit by using a thread that starts a
    # blocking worker and then checks that the result was NOT obtained
    # after the timeout (because remaining was already ≤ 0).
    submit_barrier = Event()
    release_submit = Event()
    worker_started = Event()
    worker_released = Event()

    provider = RealtimeMarketProvider(Warehouse(tmp_path), breadth_time_budget=0.05)

    original_submit = provider._get_breadth_executor().submit

    def delayed_submit(fn, *args, **kwargs):
        submit_barrier.set()
        release_submit.wait(timeout=2)
        return original_submit(fn, *args, **kwargs)

    provider._get_breadth_executor().submit = delayed_submit

    def slow_fetcher(diagnostics, deadline=None, cancel_event=None):
        worker_started.set()
        worker_released.wait(timeout=2)
        return MarketBreadth(up=100, down=50, flat=10, total=160, source="test")

    provider._call_live_breadth = slow_fetcher

    diagnostics: list[str] = []
    result_container: list = []

    def run_wrapper():
        result_container.append(provider._fetch_live_breadth_with_budget(diagnostics))

    thread = Thread(target=run_wrapper)
    thread.start()

    # Wait until submit is called, then hold it to simulate submit delay
    assert submit_barrier.wait(timeout=2)
    # Sleep beyond the budget so that by the time submit completes, remaining ≤ 0
    import time
    time.sleep(0.15)  # > breadth_time_budget=0.05
    release_submit.set()

    thread.join(timeout=2)
    worker_released.set()

    assert result_container == [None], (
        "Round-4: breadth must return None when submit delay exhausts budget"
    )
    assert any("超时" in item for item in diagnostics), (
        "Round-4: timeout diagnostic must be present after budget exhaustion"
    )


def test_local_snapshot_submit_delay_does_not_exceed_deadline(tmp_path):
    """Round-4: same deadline-awareness for local snapshot wrapper."""
    submit_barrier = Event()
    release_submit = Event()

    provider = RealtimeMarketProvider(Warehouse(tmp_path), local_snapshot_time_budget=0.05)

    original_submit = provider._get_local_executor().submit

    def delayed_submit(fn, *args, **kwargs):
        submit_barrier.set()
        release_submit.wait(timeout=2)
        return original_submit(fn, *args, **kwargs)

    provider._get_local_executor().submit = delayed_submit

    diagnostics: list[str] = []
    result_container: list = []

    def run_wrapper():
        result_container.append(
            provider._snapshot_from_local_with_budget(datetime.now(UTC), diagnostics)
        )

    thread = Thread(target=run_wrapper)
    thread.start()

    assert submit_barrier.wait(timeout=2)
    import time
    time.sleep(0.15)
    release_submit.set()
    thread.join(timeout=2)

    assert result_container[0].status == "unavailable", (
        "Round-4: local snapshot must return unavailable when submit delay exhausts budget"
    )
    assert any("超时" in item for item in diagnostics)


def test_cache_write_blocked_when_cancel_after_context_check(tmp_path):
    """Round-4 TOCTOU: when _context_expired passes but the cancel_event
    is set by another thread between the check and the cache write, the
    double-check under _state_lock must prevent the write.
    """
    after_check = Event()
    proceed = Event()
    write_done = Event()

    provider = RealtimeMarketProvider(Warehouse(tmp_path))
    provider._fetch_ths_board_members = lambda _code: ["600000"]

    original_expired = provider._context_expired

    def paused_expired(cancel_event, deadline):
        result = original_expired(cancel_event, deadline)
        if not result:
            after_check.set()
            proceed.wait(timeout=2)
        return result

    provider._context_expired = paused_expired
    cancelled = Event()
    members_result: list = []

    def fetch_with_toctou():
        members_result.append(
            provider._fetch_board_members("881234", cancel_event=cancelled)
        )
        write_done.set()

    import threading
    t = threading.Thread(target=fetch_with_toctou, daemon=True)
    t.start()

    # Wait until the worker passes _context_expired
    assert after_check.wait(timeout=2)

    # NOW cancel — between check and write
    cancelled.set()
    proceed.set()

    assert write_done.wait(timeout=2)
    t.join(timeout=2)

    assert members_result == [["600000"]], "Fresh members must be returned"
    assert "881234" not in provider._sector_member_cache, (
        "Round-4: TOCTOU — cache write must be blocked when cancel arrives between check and write"
    )
