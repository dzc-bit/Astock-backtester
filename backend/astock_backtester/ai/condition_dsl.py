"""Natural-language → condition-DSL parsing with self-healing validation.

The LLM proposes candidate DSL lines (entry/exit), every line is validated
against the local condition registry, and validation failures are fed back to
the model for at most two correction rounds. Anything that still fails is
returned as ``dropped`` so the UI can show what was not understood instead of
silently losing it.
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from astock_backtester.ai.prompts import (
    build_condition_parse_messages,
    build_condition_parse_retry_messages,
)
from astock_backtester.condition_parser import validate_condition_text, validate_exit_condition_text
from astock_backtester.models import ConditionNode

MAX_PARSE_ATTEMPTS = 3  # 1 initial proposal + 2 self-healing retries
MAX_CONDITIONS_PER_SIDE = 6
MAX_APPROXIMATIONS = 8


class ParseChatModel(Protocol):
    def chat(
        self, messages: list[dict[str, str]], *, tools: list[dict[str, Any]] | None = None
    ) -> Any: ...


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Best-effort extraction of the first JSON object from an LLM reply."""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []
    start = text.find("{")
    if start >= 0:
        depth = 0
        for index in range(start, len(text)):
            char = text[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : index + 1])
                    break
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _string_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out = [str(item).strip() for item in value if str(item).strip()]
    return out[:limit]


def _validate_side(
    expressions: list[str], *, mode: str, run_id: str
) -> tuple[list[ConditionNode], list[dict[str, str]]]:
    valid: list[ConditionNode] = []
    failures: list[dict[str, str]] = []
    for index, expression in enumerate(expressions):
        result = validate_exit_condition_text(expression) if mode == "exit" else validate_condition_text(expression)
        if result.ok and result.condition is not None:
            source = result.condition
            valid.append(
                ConditionNode(
                    id=f"ai-{run_id}-{mode}-{index}",
                    condition_id=source.condition_id,
                    params=source.params,
                    data_lag_days=source.data_lag_days,
                    expression=source.expression or expression,
                )
            )
        else:
            failures.append(
                {
                    "kind": mode,
                    "expression": expression,
                    "error": result.errors[0].message if result.errors else "无法识别条件",
                    "examples": "；".join(result.examples[:3]),
                }
            )
    return valid, failures


def _format_failures(entry_failures: list[dict[str, str]], exit_failures: list[dict[str, str]]) -> str:
    lines = []
    for failure in entry_failures:
        lines.append(f"- 入场『{failure['expression']}』：{failure['error']}（示例：{failure['examples']}）")
    for failure in exit_failures:
        lines.append(f"- 离场『{failure['expression']}』：{failure['error']}（示例：{failure['examples']}）")
    return "\n".join(lines)


def parse_conditions_with_llm(model: ParseChatModel, text: str, *, run_id: str = "parse") -> dict[str, Any]:
    """Translate free-form Chinese rules into validated entry/exit DSL nodes."""
    entry: list[ConditionNode] = []
    exit_rules: list[ConditionNode] = []
    approximations: list[str] = []
    entry_failures: list[dict[str, str]] = []
    exit_failures: list[dict[str, str]] = []

    for attempt in range(MAX_PARSE_ATTEMPTS):
        if attempt == 0:
            messages = build_condition_parse_messages(text)
        else:
            messages = build_condition_parse_retry_messages(text, _format_failures(entry_failures, exit_failures))
        content = ""
        for event in model.chat(messages, tools=None):
            if event[0] == "final":
                content = str((event[1] or {}).get("content") or "")
        parsed = _extract_json_object(content)
        if parsed is None:
            # No parsable JSON: retrying with failure context cannot help if we
            # have nothing to report; stop after one retry round.
            if attempt >= 1:
                break
            entry_failures = [{"kind": "entry", "expression": text, "error": "模型未返回可解析的 JSON", "examples": ""}]
            exit_failures = []
            continue
        entry, entry_failures = _validate_side(
            _string_list(parsed.get("entry_expressions"), limit=MAX_CONDITIONS_PER_SIDE),
            mode="entry",
            run_id=run_id,
        )
        exit_rules, exit_failures = _validate_side(
            _string_list(parsed.get("exit_expressions"), limit=MAX_CONDITIONS_PER_SIDE),
            mode="exit",
            run_id=run_id,
        )
        approximations = _string_list(parsed.get("approximations"), limit=MAX_APPROXIMATIONS)
        if not entry_failures and not exit_failures:
            break

    return {
        "entry": [node.model_dump(mode="json") for node in entry],
        "exit": [node.model_dump(mode="json") for node in exit_rules],
        "approximations": approximations,
        "dropped": [*entry_failures, *exit_failures],
    }
