"""Shared numeric parsing helpers for upstream crawler payloads.

Consolidates the float-parsing variants that were previously duplicated across
``realtime_parsers``, ``capital_flow_crawler`` and ``briefing``.
"""

from __future__ import annotations

from typing import Any

_BLANK_PLACEHOLDERS = (None, "", "-", "--")


def parse_float(value: Any) -> float | None:
    """Parse a numeric payload value leniently.

    Strips ``+``/``%``/thousand separators; blank placeholders (``None``, ``""``,
    ``-``, ``--``) and non-numeric text return ``None``.
    """
    if value in _BLANK_PLACEHOLDERS:
        return None
    text = str(value).strip().replace(",", "").replace("+", "").replace("%", "")
    if not text or text in ("-", "--"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def is_blank_numeric(value: Any) -> bool:
    """Return ``True`` for placeholder values that mean "no number supplied"."""
    if value in _BLANK_PLACEHOLDERS:
        return True
    text = str(value).strip().replace(",", "").replace("+", "").replace("%", "")
    return text in ("", "-", "--")
