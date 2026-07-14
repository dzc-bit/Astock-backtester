from __future__ import annotations

import hashlib
from typing import Any, Callable

import requests


CLS_APP_PARAMS = {
    "os": "web",
    "sv": "8.7.9",
    "app": "CailianpressWeb",
}
CLS_QUOTE_BASE_URL = "https://x-quote.cls.cn"
CLS_SITE_BASE_URL = "https://www.cls.cn"
CLS_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.cls.cn/",
}


def cls_telegraph_signed_params(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the signature required by the CLS rolling-telegraph endpoint."""
    signed = {**(params or {})}
    for key, value in CLS_APP_PARAMS.items():
        signed.setdefault(key, value)
    query = "&".join(
        f"{key}={signed[key]}"
        for key in sorted(signed, key=lambda item: str(item).upper())
    )
    digest = hashlib.sha1(query.encode("utf-8")).hexdigest()
    signed["sign"] = hashlib.md5(digest.encode("ascii")).hexdigest()
    return signed


def cls_signed_params(params: dict[str, Any] | None = None) -> dict[str, Any]:
    signed = {**(params or {})}
    for key, value in CLS_APP_PARAMS.items():
        signed.setdefault(key, value)
    query = "&".join(f"{key}={signed[key]}" for key in sorted(signed, key=lambda item: str(item).upper()))
    signed["sign"] = hashlib.md5(query.encode("utf-8")).hexdigest()
    return signed


def cls_request_json(
    requester: Callable[..., requests.Response],
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float = 5.0,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    response = requester(
        url,
        params=cls_signed_params(params),
        timeout=timeout,
        headers=headers or CLS_HEADERS,
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}
