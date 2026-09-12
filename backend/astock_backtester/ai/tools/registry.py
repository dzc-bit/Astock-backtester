"""Agent tool registry: JSON schema + executor + summarizer per tool.

Every tool is read-only by construction: executors may only call public
provider/warehouse read APIs.  ``summarizer`` produces the compact digest that
enters the model context; the full payload stays in :class:`ToolResultStore`.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

Executor = Callable[[dict[str, Any]], dict[str, Any]]
Summarizer = Callable[[dict[str, Any]], str]


@dataclass
class AiTool:
    name: str
    description: str
    parameters: dict[str, Any]
    executor: Executor
    summarizer: Summarizer
    read_only: bool = True

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolExecution:
    ok: bool
    payload: dict[str, Any]
    summary: str
    duration_ms: int
    diagnostics: list[str] = field(default_factory=list)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, AiTool] = {}

    def register(self, tool: AiTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def register_all(self, tools: list[AiTool]) -> None:
        for tool in tools:
            self.register(tool)

    def get(self, name: str) -> AiTool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def openai_schemas(self) -> list[dict[str, Any]]:
        return [tool.openai_schema() for tool in self._tools.values()]

    def execute(self, name: str, arguments: str) -> ToolExecution:
        started = time.monotonic()
        tool = self._tools.get(name)
        if tool is None:
            return ToolExecution(False, {"ok": False, "error": f"未知工具：{name}"}, f"未知工具 {name}", 0)
        try:
            args = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError as exc:
            return ToolExecution(False, {"ok": False, "error": f"参数不是合法 JSON：{exc}"}, "参数解析失败", 0)
        if not isinstance(args, dict):
            return ToolExecution(False, {"ok": False, "error": "工具参数必须是对象"}, "参数格式错误", 0)
        try:
            payload = tool.executor(args)
        except Exception as exc:  # noqa: BLE001 - tool failures must not kill the agent loop
            payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        duration_ms = int((time.monotonic() - started) * 1000)
        ok = bool(payload.get("ok", False))
        try:
            summary = tool.summarizer(payload) if ok else f"调用失败：{payload.get('error', '未知错误')}"
        except Exception:  # noqa: BLE001 - summarizer bugs must not kill the loop either
            summary = "工具结果摘要生成失败"
        diagnostics = [str(item) for item in payload.get("diagnostics", []) if item]
        return ToolExecution(ok, payload, summary, duration_ms, diagnostics)
