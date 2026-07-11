from __future__ import annotations

from collections.abc import Callable
from time import monotonic
from typing import Any

import requests

TRANSIENT_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


def _curl_get(url: str, **kwargs: Any) -> Any:
    from curl_cffi import requests as curl_requests

    return curl_requests.get(url, impersonate="chrome", **kwargs)


def _attempt_timeout(timeout: float, deadline: float | None) -> float:
    if deadline is None:
        return timeout
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError("public HTTP request budget exhausted")
    return min(timeout, remaining)


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        return response is not None and response.status_code in TRANSIENT_STATUS_CODES
    return isinstance(exc, (requests.ConnectionError, requests.Timeout, TimeoutError, OSError))


def should_allow_alternate_transport(
    requester: Callable[..., Any],
    override: bool | None = None,
) -> bool:
    """Determine whether a provider should fall back to curl_cffi transport.

    Previously this logic was duplicated as ``_allow_public_alternate_transport``
    on both ``MarketNewsProvider`` and ``RealtimeMarketProvider``.  Centralising
    it here keeps the policy in one place while leaving the per-provider
    override knob intact.
    """
    if override is not None:
        return override
    return requester is requests.get


def resilient_get(
    requester: Callable[..., Any],
    url: str,
    *,
    timeout: float,
    source: str,
    diagnostics: list[str] | None = None,
    retries: int = 1,
    deadline: float | None = None,
    alternate_requester: Callable[..., Any] | None = None,
    allow_alternate: bool = False,
    **kwargs: Any,
) -> Any:
    diagnostics = diagnostics if diagnostics is not None else []
    attempts = max(1, retries + 1)
    primary_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            response = requester(url, timeout=_attempt_timeout(timeout, deadline), **kwargs)
            response.raise_for_status()
            return response
        except Exception as exc:
            primary_error = exc
            diagnostics.append(f"{source} primary attempt {attempt}/{attempts} failed: {exc}")
            if not _is_transient(exc) or attempt == attempts:
                break

    if allow_alternate:
        alternate = alternate_requester or _curl_get
        try:
            response = alternate(url, timeout=_attempt_timeout(timeout, deadline), **kwargs)
            response.raise_for_status()
            diagnostics.append(f"{source} alternate transport used after primary failure.")
            return response
        except Exception as exc:
            diagnostics.append(f"{source} alternate transport failed: {exc}")
            raise exc from primary_error

    if primary_error is not None:
        raise primary_error
    raise RuntimeError(f"{source} request failed without an error")
