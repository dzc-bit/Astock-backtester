from __future__ import annotations

import re
from collections.abc import Callable

from astock_backtester.models import (
    ConditionNode,
    ConditionValidationError,
    ConditionValidationResult,
)


EXAMPLES = [
    "收盘价站上20日均线",
    "量比2日介于1.2到2.5",
    "流通市值10亿到300亿",
    "换手率2%到8%",
    "近5日涨幅小于12%",
    "近3日主力净流入大于300万",
    "突破20日新高",
    "MACD柱线大于0",
]

EXIT_EXAMPLES = [
    "收盘价跌破3日均线",
    "跌破20日低点",
    "突破20日最低",
    "创20日新低",
]


def condition_examples() -> list[str]:
    return list(EXAMPLES)


def exit_condition_examples() -> list[str]:
    return list(EXIT_EXAMPLES)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").strip())


def _num(value: str) -> float:
    return float(value)


def _money(value: str, unit: str) -> float:
    amount = _num(value)
    if unit == "万":
        return amount * 10_000
    if unit == "亿":
        return amount * 100_000_000
    return amount


def _percent(value: str) -> float:
    return _num(value) / 100


def _node(condition_id: str, params: dict[str, float | int], text: str) -> ConditionNode:
    return ConditionNode(
        id=f"expr-{condition_id}",
        condition_id=condition_id,
        params=params,
        data_lag_days=0,
        expression=text,
    )


Parser = Callable[[re.Match[str], str], ConditionNode]


def _close_above_ma(match: re.Match[str], text: str) -> ConditionNode:
    return _node("close_above_ma", {"window": int(match.group("window"))}, text)


def _close_below_ma(match: re.Match[str], text: str) -> ConditionNode:
    return _node("close_below_ma", {"window": int(match.group("window"))}, text)


def _market_rising_ratio(match: re.Match[str], text: str) -> ConditionNode:
    return _node("market_rising_ratio_at_least", {"min_ratio": _percent(match.group("min"))}, text)


def _volume_ratio_between(match: re.Match[str], text: str) -> ConditionNode:
    return _node(
        "volume_ratio_between",
        {
            "window": int(match.group("window")),
            "min": _num(match.group("min")),
            "max": _num(match.group("max")),
        },
        text,
    )


def _market_cap_between(match: re.Match[str], text: str) -> ConditionNode:
    return _node(
        "market_cap_between",
        {
            "min": _money(match.group("min"), match.group("min_unit")),
            "max": _money(match.group("max"), match.group("max_unit")),
        },
        text,
    )


def _turnover_between(match: re.Match[str], text: str) -> ConditionNode:
    return _node(
        "turnover_between",
        {"min": _percent(match.group("min")), "max": _percent(match.group("max"))},
        text,
    )


def _past_return_at_most(match: re.Match[str], text: str) -> ConditionNode:
    return _node(
        "past_return_at_most",
        {"window": int(match.group("window")), "max": _percent(match.group("max"))},
        text,
    )


def _past_return_between(match: re.Match[str], text: str) -> ConditionNode:
    return _node(
        "past_return_between",
        {
            "window": int(match.group("window")),
            "min": _percent(match.group("min")),
            "max": _percent(match.group("max")),
        },
        text,
    )


def _capital_flow_at_least(match: re.Match[str], text: str) -> ConditionNode:
    return _node(
        "capital_flow_n_day_sum_at_least",
        {
            "window": int(match.group("window")),
            "min": _money(match.group("min"), match.group("unit")),
        },
        text,
    )


def _breakout_high(match: re.Match[str], text: str) -> ConditionNode:
    return _node("breakout_above_n_day_high", {"window": int(match.group("window"))}, text)


def _breakdown_low(match: re.Match[str], text: str) -> ConditionNode:
    return _node("breakdown_below_n_day_low", {"window": int(match.group("window"))}, text)


def _macd_histogram_at_least(match: re.Match[str], text: str) -> ConditionNode:
    return _node("macd_histogram_at_least", {"min": _num(match.group("min"))}, text)


PATTERNS: list[tuple[re.Pattern[str], Parser]] = [
    (re.compile(r"^市场上涨家数占比(?:大于|高于|不少于|>=?)(?P<min>\d+(?:\.\d+)?)%$"), _market_rising_ratio),
    (re.compile(r"^收盘价(?:站上|高于|大于)(?P<window>\d+)日?均线$"), _close_above_ma),
    (re.compile(r"^收盘价(?:跌破|低于|小于)(?P<window>\d+)日?均线$"), _close_below_ma),
    (
        re.compile(r"^量比(?P<window>\d+)日?(?:介于|在|位于)?(?P<min>-?\d+(?:\.\d+)?)到(?P<max>-?\d+(?:\.\d+)?)$"),
        _volume_ratio_between,
    ),
    (
        re.compile(
            r"^流通市值(?P<min>\d+(?:\.\d+)?)(?P<min_unit>万|亿)?到(?P<max>\d+(?:\.\d+)?)(?P<max_unit>万|亿)?$"
        ),
        _market_cap_between,
    ),
    (
        re.compile(r"^换手率(?P<min>\d+(?:\.\d+)?)%?到(?P<max>\d+(?:\.\d+)?)%$"),
        _turnover_between,
    ),
    (
        re.compile(r"^近(?P<window>\d+)日涨幅(?:介于|在|位于)?(?P<min>-?\d+(?:\.\d+)?)%?到(?P<max>-?\d+(?:\.\d+)?)%$"),
        _past_return_between,
    ),
    (
        re.compile(r"^近(?P<window>\d+)日涨幅(?:小于|低于|不超过|<=?)(?P<max>\d+(?:\.\d+)?)%$"),
        _past_return_at_most,
    ),
    (
        re.compile(r"^近(?P<window>\d+)日主力净流入(?:大于|高于|不少于|>=?)(?P<min>\d+(?:\.\d+)?)(?P<unit>万|亿)?$"),
        _capital_flow_at_least,
    ),
    (re.compile(r"^突破(?P<window>\d+)日?(?:新高|前高)$"), _breakout_high),
    (re.compile(r"^MACD(?:柱线|红绿柱)?(?:大于|高于|>=?)(?P<min>-?\d+(?:\.\d+)?)$"), _macd_histogram_at_least),
]

EXIT_PATTERNS: list[tuple[re.Pattern[str], Parser]] = [
    (re.compile(r"^收盘价?(?:跌破|低于|小于)(?P<window>\d+)日?均线$"), _close_below_ma),
    (re.compile(r"^(?:跌破|突破)(?P<window>\d+)日?(?:低点|最低|前低)$"), _breakdown_low),
    (re.compile(r"^创(?P<window>\d+)日?新低$"), _breakdown_low),
]


def _validate_with_patterns(
    text: str,
    patterns: list[tuple[re.Pattern[str], Parser]],
    examples: list[str],
    empty_message: str,
    unrecognized_code: str,
    unrecognized_message: str,
) -> ConditionValidationResult:
    normalized = _normalize_text(text)
    if not normalized:
        return ConditionValidationResult(
            ok=False,
            normalized_text=normalized,
            errors=[
                ConditionValidationError(
                    code="empty_condition",
                    message=empty_message,
                )
            ],
            examples=examples,
        )

    for pattern, parser in patterns:
        match = pattern.match(normalized)
        if not match:
            continue
        condition = parser(match, normalized)
        return ConditionValidationResult(
            ok=True,
            normalized_text=normalized,
            condition=condition,
            examples=examples,
        )

    return ConditionValidationResult(
        ok=False,
        normalized_text=normalized,
        errors=[
            ConditionValidationError(
                code=unrecognized_code,
                message=unrecognized_message,
            )
        ],
        examples=examples,
    )


def validate_condition_text(text: str) -> ConditionValidationResult:
    return _validate_with_patterns(
        text,
        PATTERNS,
        condition_examples(),
        "条件不能为空，请参考样例输入可执行条件。",
        "unrecognized_condition",
        "无法识别条件，请参考样例改写。支持均线、量比、市值、换手率、涨幅、资金流、突破前高和 MACD。",
    )


def validate_exit_condition_text(text: str) -> ConditionValidationResult:
    return _validate_with_patterns(
        text,
        EXIT_PATTERNS,
        exit_condition_examples(),
        "离场条件不能为空，请参考样例输入可执行卖出条件。",
        "unrecognized_exit_condition",
        "无法识别离场条件，请参考样例改写。支持跌破均线、跌破N日低点/最低、创N日新低。",
    )
