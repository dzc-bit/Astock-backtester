"""Agent loop: plan -> tool -> observe -> ... -> answer, streamed as events.

The loop is a plain state machine over the OpenAI tool-call protocol and only
depends on the :class:`~astock_backtester.ai.llm_client.ChatModel` protocol,
the :class:`ToolRegistry` and the context helpers — which makes it fully unit
testable with a scripted fake model and zero network.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from astock_backtester.ai.context import (
    ContextBudget,
    ToolResult,
    ToolResultStore,
    compact_context_payload,
    wrap_untrusted,
)
from astock_backtester.ai.llm_client import ChatModel
from astock_backtester.ai.prompts import build_compaction_messages
from astock_backtester.ai.tools.registry import ToolRegistry

AgentEvent = dict[str, Any]
EventHandler = Callable[[AgentEvent], None]

SHORT_TERM_WINDOW = 10

# 摘要里含爬取正文的工具：digest 进入上下文前必须套不可信分隔符（AGENT必读 §15-8）
UNTRUSTED_DIGEST_TOOLS = frozenset(
    {"market_news", "market_briefing", "stock_research_reports", "dragon_tiger_board", "limit_up_pool"}
)


class AgentRunner:
    def __init__(self, model: ChatModel, registry: ToolRegistry, result_store: ToolResultStore, budget: ContextBudget) -> None:
        self._model = model
        self._registry = registry
        self._result_store = result_store
        self._budget = budget
        self._artifacts: dict[str, Any] = {}

    # ------------------------------------------------------------------ run
    def run(
        self,
        *,
        session: dict[str, Any],
        user_message: str,
        system_prompt: str,
        max_steps: int,
        context: dict[str, Any] | None = None,
        on_event: EventHandler,
    ) -> dict[str, Any]:
        """Run one user turn to completion; returns UI artifacts (e.g. a
        runnable strategy JSON produced by a successful backtest tool call)."""
        self._artifacts = {}
        now = datetime.now(UTC).isoformat()
        content = user_message
        if context and context.get("kind") not in (None, "none"):
            content = f"{user_message}\n\n{compact_context_payload(str(context.get('kind')), context.get('payload') or {}, self._budget)}"
        session["messages"].append({"role": "user", "content": content})
        session["display"].append({"role": "user", "content": user_message, "ts": now})
        session["updated_at"] = now

        # Layered memory: hard short-term window; overflow is archived and then
        # consolidated into the rolling summary before the first model call.
        self._archive_overflow(session, on_event)
        self._consolidate_archive(session, on_event)
        schemas = self._registry.openai_schemas()

        for step in range(1, max_steps + 1):
            on_event({"type": "phase", "phase": f"思考中（第 {step}/{max_steps} 步）"})
            messages = self._build_request_messages(session, system_prompt)
            content_parts: list[str] = []
            for event in self._model.chat(messages, tools=schemas):
                if event[0] == "text":
                    content_parts.append(event[1])
                    on_event({"type": "token", "text": event[1]})
                    continue
                turn = event[1]
            tool_calls = turn.get("tool_calls")
            assistant_message: dict[str, Any] = {"role": "assistant", "content": turn.get("content")}
            if tool_calls:
                assistant_message["tool_calls"] = tool_calls
            session["messages"].append(assistant_message)

            if not tool_calls:
                session["display"].append(
                    {"role": "assistant", "content": turn.get("content") or "", "tool_steps": [], "ts": datetime.now(UTC).isoformat()}
                )
                session["updated_at"] = datetime.now(UTC).isoformat()
                return dict(self._artifacts)

            steps = self._execute_tool_calls(session, tool_calls, on_event)
            session["display"].append(
                {
                    "role": "assistant",
                    "content": "".join(content_parts),
                    "tool_steps": steps,
                    "ts": datetime.now(UTC).isoformat(),
                }
            )

        note = "（已达到单次问题的工具调用上限，回答中止；请拆小问题后重试。）"
        session["messages"].append({"role": "assistant", "content": note})
        session["display"].append({"role": "assistant", "content": note, "tool_steps": [], "ts": datetime.now(UTC).isoformat()})
        on_event({"type": "phase", "phase": "已达工具调用上限"})
        return dict(self._artifacts)

    # --------------------------------------------------------------- tools
    def _execute_tool_calls(
        self, session: dict[str, Any], tool_calls: list[dict[str, Any]], on_event: EventHandler
    ) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = []
        for call in tool_calls:
            function = call.get("function", {})
            name = str(function.get("name", ""))
            arguments = str(function.get("arguments", ""))
            call_id = str(call.get("id", ""))
            try:
                args = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError:
                args = {}
            on_event({"type": "tool_call", "id": call_id, "name": name, "args": args})
            execution = self._registry.execute(name, arguments)
            self._result_store.put(
                ToolResult(
                    call_id=call_id,
                    name=name,
                    arguments=args,
                    payload=execution.payload,
                    summary=execution.summary,
                )
            )
            if name == "run_strategy_backtest" and execution.ok and isinstance(execution.payload.get("strategy"), dict):
                self._artifacts["strategy"] = execution.payload["strategy"]
            on_event(
                {
                    "type": "tool_result",
                    "id": call_id,
                    "name": name,
                    "ok": execution.ok,
                    "summary": execution.summary,
                    "duration_ms": execution.duration_ms,
                    "diagnostics": execution.diagnostics,
                }
            )
            steps.append(
                {
                    "id": call_id,
                    "name": name,
                    "ok": execution.ok,
                    "summary": execution.summary,
                    "duration_ms": execution.duration_ms,
                }
            )
            session_tool_content = execution.summary
            if execution.diagnostics:
                session_tool_content += "\n诊断: " + "；".join(execution.diagnostics[:3])
            if name in UNTRUSTED_DIGEST_TOOLS:
                session_tool_content = wrap_untrusted(session_tool_content)
            session_tool_content = self._budget.digest(session_tool_content)
            session_tool = {"role": "tool", "tool_call_id": call_id, "content": session_tool_content}
            self._session_messages_target(session).append(session_tool)
        return steps

    # ----------------------------------------------------------- messages
    def _build_request_messages(self, session: dict[str, Any], system_prompt: str) -> list[dict[str, Any]]:
        system = system_prompt
        rolling = str(session.get("rolling_summary") or "")
        if rolling:
            system += f"\n\n## 会话纪要（更早的对话已压缩）\n{rolling}"
        return [{"role": "system", "content": system}, *session["messages"]]

    def _archive_overflow(self, session: dict[str, Any], on_event: EventHandler) -> None:
        """Keep at most SHORT_TERM_WINDOW protocol messages in the live window.

        The cut point is extended to the next user-message boundary so a
        assistant(tool_calls)/tool pair is never split across the window edge.
        """
        messages = session["messages"]
        overflow = len(messages) - SHORT_TERM_WINDOW
        if overflow <= 0:
            return
        while overflow < len(messages) and messages[overflow].get("role") != "user":
            overflow += 1
        if overflow >= len(messages):
            return
        dropped = messages[:overflow]
        session["messages"] = messages[overflow:]
        archive = session.setdefault("pending_archive", [])
        for message in dropped:
            text = str(message.get("content") or "")
            calls = message.get("tool_calls") or []
            if calls:
                text += " " + ", ".join(call.get("function", {}).get("name", "") for call in calls)
            archive.append(f"{message.get('role')}: {text}")
        on_event({"type": "phase", "phase": "归档短期窗口之外的对话"})

    def _consolidate_archive(self, session: dict[str, Any], on_event: EventHandler) -> None:
        """Fold archived dialogue into the rolling summary (one model call)."""
        archive = session.get("pending_archive") or []
        if not archive:
            return
        session["pending_archive"] = []
        on_event({"type": "phase", "phase": "压缩进长期会话纪要"})
        existing = str(session.get("rolling_summary") or "")
        lines = [f"（既有纪要）{existing}"] if existing else []
        lines.extend(archive)
        summary = self._summarize_history_text("\n".join(lines))
        if summary:
            session["rolling_summary"] = summary[:4000]

    def _summarize_history_text(self, history_text: str) -> str:
        final_content = ""
        for event in self._model.chat(build_compaction_messages(history_text), tools=None):
            if event[0] == "final":
                final_content = str(event[1].get("content") or "")
        return final_content[:4000]

    def _session_messages_target(self, session: dict[str, Any]) -> list[dict[str, Any]]:
        return session["messages"]
