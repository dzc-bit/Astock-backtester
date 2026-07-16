from __future__ import annotations

import sys

import pytest

from astock_backtester.data.cls_finance import (
    ClsFinanceProvider,
    _resolve_node_executable,
    _resolve_ths_cookie_worker,
    _subprocess_startup_kwargs,
)


def test_resolves_ths_cookie_runtime_next_to_frozen_sidecar(tmp_path, monkeypatch):
    sidecar = tmp_path / "astock-data-service.exe"
    node = tmp_path / "node.exe"
    worker = tmp_path / "ths-cookie-worker.cjs"
    sidecar.write_text("", encoding="utf-8")
    node.write_text("", encoding="utf-8")
    worker.write_text("", encoding="utf-8")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(sidecar))

    assert _resolve_node_executable() == str(node)
    assert _resolve_ths_cookie_worker() == worker


def test_ths_cookie_worker_hides_console_on_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")

    kwargs = _subprocess_startup_kwargs()

    assert kwargs["creationflags"] == 0x08000000
    assert kwargs["startupinfo"].dwFlags & 1
    assert kwargs["startupinfo"].wShowWindow == 0


class _FakeResponse:
    encoding = "utf-8"

    def __init__(self, payload=None, text=""):
        self._payload = payload or {}
        self.text = text

    def raise_for_status(self):
        return

    def json(self):
        return self._payload


def _finance_payloads():
    return {
        "tline": {"code": 200, "data": [{"date": 20260714, "minute": 930, "last_px": 3960, "change": 0.01}]},
        "anchor": {"errno": 0, "data": []},
        "basic": {"code": 200, "data": {"preclose_px": 3950}},
        "emotion": {
            "code": 200,
            "data": {
                "market_degree": "56",
                "up_ratio_num": "85",
                "up_open_num": "12",
                "up_down_dis": {"rise_num": 3919, "fall_num": 1215, "flat_num": 67},
            },
        },
        "up_pool": {"code": 200, "data": []},
        "home": {
            "code": 200,
            "data": {
                "up_down_dis": {"rise_num": 3919, "fall_num": 1215, "flat_num": 67, "up_num": 85},
            },
        },
    }


def test_cls_finance_tline_explicitly_requests_the_shanghai_index():
    requested_params = {}

    def requester(_url, **kwargs):
        requested_params.update(kwargs["params"])
        return _FakeResponse(
            {"code": 200, "data": [{"date": 20260714, "minute": 930, "last_px": 3960}]}
        )

    points = ClsFinanceProvider(requester=requester)._read_tline([])

    assert points
    assert requested_params["secu_code"] == "sh000001"


def test_cls_finance_tline_sorts_points_by_date_and_minute():
    def requester(_url, **_kwargs):
        return _FakeResponse(
            {
                "code": 200,
                "data": [
                    {"date": 20260715, "minute": 1300, "last_px": 3970},
                    {"date": 20260714, "minute": 1500, "last_px": 3960},
                    {"date": 20260715, "minute": 930, "last_px": 3950},
                    {"date": 20260714, "minute": 930, "last_px": 3940},
                    {"date": 20260715, "minute": 930, "last_px": 3951},
                ],
            }
        )

    points = ClsFinanceProvider(requester=requester)._read_tline([])

    assert [(point.date, point.minute, point.last_px) for point in points] == [
        (20260714, 930, 3940),
        (20260714, 1500, 3960),
        (20260715, 930, 3950),
        (20260715, 930, 3951),
        (20260715, 1300, 3970),
    ]


def test_cls_finance_reuses_recent_success_after_transient_source_failure():
    payloads = _finance_payloads()
    should_fail = False

    def requester(url, **kwargs):
        if should_fail:
            raise TimeoutError("CLS temporary timeout")
        if "quote/index/tline" in url:
            return _FakeResponse(payloads["tline"])
        if "v3/transaction/anchor" in url:
            return _FakeResponse(payloads["anchor"])
        if "quote/index/basic" in url:
            return _FakeResponse(payloads["basic"])
        if "v2/quote/a/stock/emotion" in url:
            return _FakeResponse(payloads["emotion"])
        if "quote/index/up_down_analysis" in url:
            return _FakeResponse(payloads["up_pool"])
        if "q.10jqka.com.cn" in url:
            return _FakeResponse(text="<html><body></body></html>")
        raise AssertionError(url)

    provider = ClsFinanceProvider(requester=requester, cache_ttl=0, recent_success_ttl=60)
    provider.browser_cookie_getter = lambda: None

    first = provider.current_board()
    should_fail = True
    second = provider.current_board()

    assert first.tline
    assert second.source.endswith("+recent-success-cache")
    assert second.tline == first.tline
    assert any("recent_success_cache_used" in item for item in second.diagnostics)


def test_cls_finance_preserves_recent_complete_fields_when_refresh_is_partial():
    payloads = _finance_payloads()
    partial = False

    def requester(url, **kwargs):
        if partial:
            if "quote/index/tline" in url:
                return _FakeResponse(payloads["tline"])
            if "v3/transaction/anchor" in url:
                return _FakeResponse(payloads["anchor"])
            if "q.10jqka.com.cn" in url:
                return _FakeResponse(text="<html><body></body></html>")
            raise TimeoutError("CLS partial refresh timeout")
        if "quote/index/tline" in url:
            return _FakeResponse(payloads["tline"])
        if "v3/transaction/anchor" in url:
            return _FakeResponse(payloads["anchor"])
        if "quote/index/basic" in url:
            return _FakeResponse(payloads["basic"])
        if "v2/quote/a/stock/emotion" in url:
            return _FakeResponse(payloads["emotion"])
        if "quote/index/up_down_analysis" in url:
            return _FakeResponse(payloads["up_pool"])
        if "q.10jqka.com.cn" in url:
            return _FakeResponse(text="<html><body></body></html>")
        raise AssertionError(url)

    provider = ClsFinanceProvider(requester=requester, cache_ttl=0, recent_success_ttl=60)
    provider.browser_cookie_getter = lambda: None

    first = provider.current_board()
    partial = True
    second = provider.current_board()

    assert first.emotion is not None
    assert first.emotion.breadth is not None
    assert second.emotion is not None
    assert second.emotion.breadth == first.emotion.breadth
    assert second.source.endswith("+recent-success-cache")
    assert any("recent_success_cache_used" in item for item in second.diagnostics)


def test_cls_finance_preserves_a_valid_empty_up_pool_over_recent_success():
    payloads = _finance_payloads()
    payloads["up_pool"] = {
        "code": 200,
        "data": [{"secu_code": "sh600001", "secu_name": "Prior limit-up"}],
    }
    use_empty_pool = False

    def requester(url, **_kwargs):
        if "quote/index/tline" in url:
            return _FakeResponse(payloads["tline"])
        if "v3/transaction/anchor" in url:
            return _FakeResponse(payloads["anchor"])
        if "quote/index/basic" in url:
            return _FakeResponse(payloads["basic"])
        if "v2/quote/a/stock/emotion" in url:
            return _FakeResponse(payloads["emotion"])
        if "quote/index/up_down_analysis" in url:
            if use_empty_pool:
                return _FakeResponse({"code": 200, "data": []})
            return _FakeResponse(payloads["up_pool"])
        if "q.10jqka.com.cn" in url:
            return _FakeResponse(text="<html><body></body></html>")
        raise AssertionError(url)

    provider = ClsFinanceProvider(requester=requester, cache_ttl=0, recent_success_ttl=60)
    provider.browser_cookie_getter = lambda: None

    first = provider.current_board()
    use_empty_pool = True
    second = provider.current_board()

    assert first.up_pool
    assert second.up_pool == []
    assert not second.source.endswith("+recent-success-cache")


@pytest.mark.parametrize(
    ("field_name", "url_fragment"),
    [
        ("tline", "quote/index/tline"),
        ("anchors", "v3/transaction/anchor"),
        ("up_pool", "quote/index/up_down_analysis"),
    ],
)
def test_cls_finance_reuses_recent_list_field_when_nonempty_rows_are_unparseable(
    field_name,
    url_fragment,
):
    payloads = _finance_payloads()
    payloads["anchor"] = {
        "errno": 0,
        "data": [{"symbol_code": "cls123", "symbol_name": "Prior anchor"}],
    }
    payloads["up_pool"] = {
        "code": 200,
        "data": [{"secu_code": "sh600001", "secu_name": "Prior limit-up"}],
    }
    malformed = False

    def requester(url, **_kwargs):
        if url_fragment in url and malformed:
            return _FakeResponse({"code": 200, "data": [{}]})
        if "quote/index/tline" in url:
            return _FakeResponse(payloads["tline"])
        if "v3/transaction/anchor" in url:
            return _FakeResponse(payloads["anchor"])
        if "quote/index/basic" in url:
            return _FakeResponse(payloads["basic"])
        if "v2/quote/a/stock/emotion" in url:
            return _FakeResponse(payloads["emotion"])
        if "quote/index/up_down_analysis" in url:
            return _FakeResponse(payloads["up_pool"])
        if "q.10jqka.com.cn" in url:
            return _FakeResponse(text="<html><body></body></html>")
        raise AssertionError(url)

    provider = ClsFinanceProvider(requester=requester, cache_ttl=0, recent_success_ttl=60)
    provider.browser_cookie_getter = lambda: None

    first = provider.current_board()
    malformed = True
    second = provider.current_board()

    assert getattr(first, field_name)
    assert getattr(second, field_name) == getattr(first, field_name)
    assert second.source.endswith("+recent-success-cache")
    assert any("no parseable rows" in item for item in second.diagnostics)


def test_cls_finance_uses_home_distribution_when_emotion_endpoint_fails():
    payloads = _finance_payloads()

    def requester(url, **kwargs):
        if "quote/index/tline" in url:
            return _FakeResponse(payloads["tline"])
        if "v3/transaction/anchor" in url:
            return _FakeResponse(payloads["anchor"])
        if "quote/index/basic" in url:
            return _FakeResponse(payloads["basic"])
        if "v2/quote/a/stock/emotion" in url:
            raise TimeoutError("emotion timeout")
        if "quote/index/home" in url:
            return _FakeResponse(payloads["home"])
        if "quote/index/up_down_analysis" in url:
            return _FakeResponse(payloads["up_pool"])
        if "q.10jqka.com.cn" in url:
            return _FakeResponse(text="<html><body></body></html>")
        raise AssertionError(url)

    provider = ClsFinanceProvider(requester=requester, cache_ttl=0)
    provider.browser_cookie_getter = lambda: None

    response = provider.current_board()

    assert response.emotion is not None
    assert response.emotion.breadth is not None
    assert response.emotion.breadth.total == 5201
    assert response.emotion.up_limit == 85
    assert any("CLS homepage distribution fallback used" in item for item in response.diagnostics)


def test_cls_finance_emotion_keeps_primary_zero_counts_over_home_fallback():
    def requester(url, **_kwargs):
        if "v2/quote/a/stock/emotion" in url:
            return _FakeResponse(
                {
                    "code": 200,
                    "data": {
                        "up_ratio_num": 0,
                        "up_open_num": 0,
                        "up_down_dis": {},
                    },
                }
            )
        if "quote/index/home" in url:
            return _FakeResponse(
                {
                    "code": 200,
                    "data": {
                        "up_down_dis": {
                            "rise_num": 3919,
                            "fall_num": 1215,
                            "flat_num": 67,
                            "up_num": 85,
                            "up_open_num": 12,
                        }
                    },
                }
            )
        raise AssertionError(url)

    emotion = ClsFinanceProvider(requester=requester)._read_emotion([])

    assert emotion is not None
    assert emotion.up_limit == 0
    assert emotion.open_limit == 0


def test_cls_finance_does_not_cache_logical_error_responses():
    calls = 0

    def requester(_url, **_kwargs):
        nonlocal calls
        calls += 1
        return _FakeResponse({"code": 500, "message": "signature invalid", "data": {}})

    provider = ClsFinanceProvider(requester=requester, cache_ttl=60, recent_success_ttl=60)
    provider._read_ths_market_degree = lambda _diagnostics: None

    first = provider.current_board()
    calls_after_first = calls
    second = provider.current_board()

    assert calls_after_first > 0
    assert calls > calls_after_first
    assert first.emotion is None
    assert second.emotion is None
    assert provider._cached_response is None
    assert provider._last_successful_response is None
    assert any("code=500" in item for item in first.diagnostics)
