"""Unit tests for the v1.5.0 AI light-route modules (no HTTP, no network)."""

from __future__ import annotations

import pytest
from astock_backtester.ai.condition_dsl import _extract_json_object, parse_conditions_with_llm
from astock_backtester.ai.oneshot import compact_context
from astock_backtester.ai.optimizer import GridTooLargeError, iter_grid, normalize_grid
from astock_backtester.data.warehouse import lifecycle_bound


class ScriptedModel:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls = 0

    def chat(self, messages, *, tools=None):
        self.calls += 1
        content = self.replies.pop(0) if self.replies else ""
        yield ("final", {"content": content, "tool_calls": None})

    def embed(self, texts):
        return [[0.0] for _ in texts]


def test_extract_json_object_handles_plain_fenced_and_embedded_payloads():
    assert _extract_json_object('{"entry_expressions": []}') == {"entry_expressions": []}
    assert _extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json_object('前置说明 {"a": {"b": 2}} 后置说明') == {"a": {"b": 2}}
    assert _extract_json_object("完全不是 JSON") is None
    assert _extract_json_object('{"a": 1') is None  # 截断的 JSON


def test_parse_conditions_reports_unsupported_indicator_as_dropped():
    import json

    broken = json.dumps(
        {"entry_expressions": ["KDJ金叉"], "exit_expressions": [], "approximations": []},
        ensure_ascii=False,
    )
    model = ScriptedModel([broken, broken, broken])

    result = parse_conditions_with_llm(model, "KDJ金叉买入")

    assert result["entry"] == []
    assert len(result["dropped"]) == 1
    assert result["dropped"][0]["kind"] == "entry"
    assert model.calls == 3  # 1 initial + 2 self-healing retries


def test_parse_conditions_accepts_valid_dsl_without_retry():
    import json

    model = ScriptedModel(
        [
            json.dumps(
                {
                    "entry_expressions": ["收盘价站上20日均线"],
                    "exit_expressions": ["MACD死叉"],
                    "approximations": [],
                },
                ensure_ascii=False,
            )
        ]
    )

    result = parse_conditions_with_llm(model, "站上20日线买，死叉卖")

    assert [node["condition_id"] for node in result["entry"]] == ["close_above_ma"]
    assert [node["condition_id"] for node in result["exit"]] == ["macd_dead_cross"]
    assert result["dropped"] == []
    assert model.calls == 1


def test_compact_context_truncates_and_scene_validation_rejects_unknown():
    from astock_backtester.ai.oneshot import ONESHOT_SCENES, insight_oneshot

    assert len(compact_context({"k": "x" * 5000})) <= 3000
    with pytest.raises(ValueError, match="未知点评场景"):
        insight_oneshot(ScriptedModel([]), "nope", {})
    assert set(ONESHOT_SCENES) == {"results_overview", "data_coverage", "risk_alerts"}


def test_normalize_grid_enforces_whitelist_bounds_and_finiteness():
    assert normalize_grid({"fixed_holding_days": [3, 5]}) == {"fixed_holding_days": [3.0, 5.0]}
    with pytest.raises(ValueError, match="不支持寻优的参数"):
        normalize_grid({"entry_window": [3, 5]})
    with pytest.raises(ValueError, match="非空数组"):
        normalize_grid({"fixed_holding_days": []})
    with pytest.raises(ValueError, match="有限数字"):
        normalize_grid({"max_positions": [float("nan")]})
    with pytest.raises(GridTooLargeError):
        normalize_grid({"fixed_holding_days": [1] * 7, "max_positions": [2] * 7})


def test_iter_grid_yields_the_full_cartesian_product():
    combos = list(iter_grid({"a": [1, 2], "b": [3, 4]}))

    assert combos == [
        {"a": 1.0, "b": 3.0},
        {"a": 1.0, "b": 4.0},
        {"a": 2.0, "b": 3.0},
        {"a": 2.0, "b": 4.0},
    ]


def test_lifecycle_bound_parses_iso_and_ignores_garbage():
    import pandas as pd

    assert lifecycle_bound({"listing_date": "2024-01-03"}, "listing_date") == pd.Timestamp("2024-01-03")
    assert lifecycle_bound({"listing_date": "not-a-date"}, "listing_date") is None
    assert lifecycle_bound({"listing_date": None}, "listing_date") is None
    assert lifecycle_bound(None, "listing_date") is None
