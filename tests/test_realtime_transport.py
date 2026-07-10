from __future__ import annotations

from datetime import UTC, datetime
from threading import Event, Thread

import requests
from astock_backtester.data.realtime import RealtimeMarketProvider
from astock_backtester.data.warehouse import Warehouse
from astock_backtester.models import RealtimeMarketSnapshot


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
