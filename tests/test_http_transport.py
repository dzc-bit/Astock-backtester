from __future__ import annotations

from time import monotonic

import pytest
import requests
from astock_backtester.data.http_transport import resilient_get


class FakeResponse:
    def __init__(self, status_code: int = 200):
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(f"HTTP {self.status_code}", response=response)


def test_resilient_get_retries_one_transient_connection_failure():
    attempts: list[float] = []

    def requester(_url: str, **kwargs):
        attempts.append(kwargs["timeout"])
        if len(attempts) == 1:
            raise requests.ConnectionError("connection reset")
        return FakeResponse()

    diagnostics: list[str] = []
    response = resilient_get(
        requester,
        "https://example.test/market",
        timeout=2.0,
        source="test-market",
        diagnostics=diagnostics,
        retries=1,
    )

    assert response.status_code == 200
    assert len(attempts) == 2
    assert any("primary attempt 1/2 failed" in item for item in diagnostics)


def test_resilient_get_does_not_retry_terminal_client_error():
    attempts = 0

    def requester(_url: str, **_kwargs):
        nonlocal attempts
        attempts += 1
        return FakeResponse(404)

    with pytest.raises(requests.HTTPError):
        resilient_get(
            requester,
            "https://example.test/missing",
            timeout=2.0,
            source="test-market",
            retries=1,
        )

    assert attempts == 1


def test_resilient_get_uses_explicit_alternate_transport_after_403():
    alternate_attempts = 0

    def primary(_url: str, **_kwargs):
        return FakeResponse(403)

    def alternate(_url: str, **_kwargs):
        nonlocal alternate_attempts
        alternate_attempts += 1
        return FakeResponse()

    diagnostics: list[str] = []
    response = resilient_get(
        primary,
        "https://example.test/protected",
        timeout=2.0,
        source="test-market",
        diagnostics=diagnostics,
        alternate_requester=alternate,
        allow_alternate=True,
    )

    assert response.status_code == 200
    assert alternate_attempts == 1
    assert any("alternate transport used" in item for item in diagnostics)


def test_resilient_get_clamps_each_attempt_to_remaining_budget():
    observed_timeout = 0.0

    def requester(_url: str, **kwargs):
        nonlocal observed_timeout
        observed_timeout = kwargs["timeout"]
        return FakeResponse()

    resilient_get(
        requester,
        "https://example.test/market",
        timeout=10.0,
        source="test-market",
        deadline=monotonic() + 0.25,
    )

    assert 0 < observed_timeout <= 0.25
