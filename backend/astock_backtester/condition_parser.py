from __future__ import annotations

import re
from collections.abc import Callable

from astock_backtester.models import (
    ConditionNode,
    ConditionValidationError,
    ConditionValidationResult,
)

EXAMPLES = [
    "市场上涨家数占比大于55%",
    "收盘价站上20日均线",
    "量比2日介于1.2到2.5",
    "流通市值10亿到300亿",
    "换手率2%到8%",
    "近5日涨幅0%到12%",
    "近5日涨幅小于12%",
    "近3日主力净流入大于300万",
    "突破20日新高",
    "MACD柱线大于0",
]

EXIT_EXAMPLES = [
    "收盘价跌破3日均线",
    "跌破20日低点",
    "近5日涨幅小于3%",
    "MACD死叉",
    "资金流出",
    "近3日主力净流出",
]

ENTRY_TEMPLATES = [
    "收盘价站上N日均线",
    "量比N日介于A到B",
    "流通市值X亿到Y亿",
    "换手率A%到B%",
    "近N日涨幅小于X%",
    "近N日主力净流入大于X万/亿",
    "突破N日新高",
    "MACD柱线大于X",
]

EXIT_TEMPLATES = [
    "收盘价跌破N日均线",
    "近N日涨幅小于X%",
    "MACD死叉",
    "资金流出",
    "近N日主力净流出",
    "跌破N日低点",
    "创N日新低",
]


def condition_examples() -> list[str]:
    return list(EXAMPLES)


def exit_condition_examples() -> list[str]:
    return list(EXIT_EXAMPLES)


def _template_message(prefix: str, templates: list[str]) -> str:
    rendered = "、".join(f"“{template}”" for template in templates)
    return f"{prefix}，请改写成类似{rendered}的模板。"


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").strip())


def _num(value: str) -> float:
    return float(value)


_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _parse_window(value: str) -> int:
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    text = text.replace("两", "二").replace("〇", "零")
    if text == "十":
        return 10
    if "十" in text:
        left, right = text.split("十", 1)
        tens = 1 if not left else _CHINESE_DIGITS.get(left, 0)
        ones = 0 if not right else _CHINESE_DIGITS.get(right, 0)
        return tens * 10 + ones
    try:
        return int(text)
    except ValueError:
        return _CHINESE_DIGITS.get(text, 0)


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
    return _node("close_above_ma", {"window": _parse_window(match.group("window"))}, text)


def _close_below_ma(match: re.Match[str], text: str) -> ConditionNode:
    return _node("close_below_ma", {"window": _parse_window(match.group("window"))}, text)


def _market_rising_ratio(match: re.Match[str], text: str) -> ConditionNode:
    return _node("market_rising_ratio_at_least", {"min_ratio": _percent(match.group("min"))}, text)


def _volume_ratio_between(match: re.Match[str], text: str) -> ConditionNode:
    return _node(
        "volume_ratio_between",
        {
            "window": _parse_window(match.group("window")),
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
        {"window": _parse_window(match.group("window")), "max": _percent(match.group("max"))},
        text,
    )


def _past_return_between(match: re.Match[str], text: str) -> ConditionNode:
    return _node(
        "past_return_between",
        {
            "window": _parse_window(match.group("window")),
            "min": _percent(match.group("min")),
            "max": _percent(match.group("max")),
        },
        text,
    )


def _capital_flow_at_least(match: re.Match[str], text: str) -> ConditionNode:
    return _node(
        "capital_flow_n_day_sum_at_least",
        {
            "window": _parse_window(match.group("window")),
            "min": _money(match.group("min"), match.group("unit")),
        },
        text,
    )


def _capital_flow_at_most(match: re.Match[str], text: str) -> ConditionNode:
    max_value = 0.0
    if match.groupdict().get("max"):
        max_value = -_money(match.group("max"), match.group("unit"))
    return _node(
        "capital_flow_n_day_sum_at_most",
        {
            "window": _parse_window(match.group("window")),
            "max": max_value,
        },
        text,
    )


def _capital_flow_today_at_most(_: re.Match[str], text: str) -> ConditionNode:
    return _node("capital_flow_today_at_most", {"max": 0.0}, text)


def _breakout_high(match: re.Match[str], text: str) -> ConditionNode:
    return _node("breakout_above_n_day_high", {"window": _parse_window(match.group("window"))}, text)


def _breakdown_low(match: re.Match[str], text: str) -> ConditionNode:
    return _node("breakdown_below_n_day_low", {"window": _parse_window(match.group("window"))}, text)


def _macd_histogram_at_least(match: re.Match[str], text: str) -> ConditionNode:
    return _node("macd_histogram_at_least", {"min": _num(match.group("min"))}, text)


def _macd_dead_cross(_: re.Match[str], text: str) -> ConditionNode:
    return _node("macd_dead_cross", {}, text)


PATTERNS: list[tuple[re.Pattern[str], Parser]] = [
    (re.compile(r"^市场上涨家数占比(?:大于|高于|不少于|>=?)(?P<min>\d+(?:\.\d+)?)%$"), _market_rising_ratio),
    (re.compile(r"^收盘价(?:站上|高于|大于)(?P<window>[\d一二三四五六七八九十两〇零]+)日?均线$"), _close_above_ma),
    (re.compile(r"^收盘价(?:跌破|低于|小于)(?P<window>[\d一二三四五六七八九十两〇零]+)日?均线$"), _close_below_ma),
    (
        re.compile(r"^量比(?P<window>[\d一二三四五六七八九十两〇零]+)日?(?:介于|在|位于)?(?P<min>-?\d+(?:\.\d+)?)到(?P<max>-?\d+(?:\.\d+)?)$"),
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
        re.compile(r"^近(?P<window>[\d一二三四五六七八九十两〇零]+)日涨幅(?:介于|在|位于)?(?P<min>-?\d+(?:\.\d+)?)%?到(?P<max>-?\d+(?:\.\d+)?)%$"),
        _past_return_between,
    ),
    (
        re.compile(r"^近(?P<window>[\d一二三四五六七八九十两〇零]+)日涨幅(?:小于|低于|不超过|<=?)(?P<max>\d+(?:\.\d+)?)%$"),
        _past_return_at_most,
    ),
    (
        re.compile(r"^近(?P<window>[\d一二三四五六七八九十两〇零]+)日主力净流入(?:大于|高于|不少于|>=?)(?P<min>\d+(?:\.\d+)?)(?P<unit>万|亿)?$"),
        _capital_flow_at_least,
    ),
    (
        re.compile(r"^近(?P<window>[\d一二三四五六七八九十两〇零]+)日主力净流出(?:大于|高于|不少于|>=?)(?P<max>\d+(?:\.\d+)?)(?P<unit>万|亿)?$"),
        _capital_flow_at_most,
    ),
    (re.compile(r"^突破(?P<window>[\d一二三四五六七八九十两〇零]+)日?(?:新高|前高)$"), _breakout_high),
    (re.compile(r"^MACD(?:柱线|红绿柱)?(?:大于|高于|>=?)(?P<min>-?\d+(?:\.\d+)?)$"), _macd_histogram_at_least),
]

EXIT_PATTERNS: list[tuple[re.Pattern[str], Parser]] = [
    (re.compile(r"^收盘价?(?:跌破|低于|小于)(?P<window>[\d一二三四五六七八九十两〇零]+)日?均线$"), _close_below_ma),
    (
        re.compile(r"^近(?P<window>[\d一二三四五六七八九十两〇零]+)日涨幅(?:小于|低于|不超过|<=?)(?P<max>\d+(?:\.\d+)?)%$"),
        _past_return_at_most,
    ),
    (re.compile(r"^(?:MACD死叉|MACD下穿|MACD向下死叉)$"), _macd_dead_cross),
    (re.compile(r"^(?:资金流出|主力净流出|当日主力净流出)$"), _capital_flow_today_at_most),
    (
        re.compile(r"^近(?P<window>[\d一二三四五六七八九十两〇零]+)日主力净流出(?:大于|高于|不少于|>=?)(?P<max>\d+(?:\.\d+)?)(?P<unit>万|亿)?$"),
        _capital_flow_at_most,
    ),
    (re.compile(r"^近(?P<window>[\d一二三四五六七八九十两〇零]+)日主力净流出$"), _capital_flow_at_most),
    (re.compile(r"^(?:跌破|突破)(?P<window>[\d一二三四五六七八九十两〇零]+)日?(?:低点|最低|前低)$"), _breakdown_low),
    (re.compile(r"^创(?P<window>[\d一二三四五六七八九十两〇零]+)日?新低$"), _breakdown_low),
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
        _template_message(
            "无法识别条件",
            ENTRY_TEMPLATES,
        ),
    )


def validate_exit_condition_text(text: str) -> ConditionValidationResult:
    return _validate_with_patterns(
        text,
        EXIT_PATTERNS,
        exit_condition_examples(),
        "离场条件不能为空，请参考样例输入可执行卖出条件。",
        "unrecognized_exit_condition",
        _template_message(
            "无法识别离场条件",
            EXIT_TEMPLATES,
        ),
    )
