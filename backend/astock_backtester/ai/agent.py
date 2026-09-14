"""Agent loop: plan -> tool -> observe -> ... -> answer, streamed as events.

The loop is a plain state machine over the OpenAI tool-call protocol and only
depends on the :class:`~astock_backtester.ai.llm_client.ChatModel` protocol,
the :class:`ToolRegistry` and the context helpers — which makes it fully unit
testable with a scripted fake model and zero network.
"""

from __future__ import annotations

import json
import logging
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
from astock_backtester.ai.prompts import build_compaction_messages, build_final_answer_messages
from astock_backtester.ai.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

AgentEvent = dict[str, Any]
EventHandler = Callable[[AgentEvent], None]

# 短期窗口按“条数”与“字符数”双阈值控制：只有两者都未超限时才不压缩，
# 避免每轮工具对话（assistant+tool 消息膨胀很快）都在新问题开始时触发压缩。
SHORT_TERM_WINDOW = 24
SHORT_TERM_MAX_CHARS = 36_000
# 归档攒批：攒够足够多的待压缩内容才调用一次纪要模型，避免频繁压缩。
CONSOLIDATE_MIN_ENTRIES = 12
CONSOLIDATE_MIN_CHARS = 6_000
# 归档条目上限：压缩持续失败（模型不可用等）时 pending_archive 只增不减，
# 这是长久的内存/落盘膨胀风险，按条数兜底裁剪。
ARCHIVE_MAX_ENTRIES = 400

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
        # 上一次运行可能被中断（客户端断开/进程退出/模型异常），先修复悬空的
        # tool_calls——否则下次请求会被上游 API 以协议错误拒绝，表现为“失忆”。
        self._repair_interrupted_turn(session)
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

        # 步数耗尽时绝不“空手中断”：强制做一次不带工具的收尾回答，
        # 把已收集的工具结果整理成结论交给用户。
        if self._forced_final_answer(session, system_prompt, on_event):
            return dict(self._artifacts)
        note = "（已达到单次问题的工具调用上限，且收尾回答生成失败；请拆小问题后重试。）"
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
            if name == "run_strategy_backtest" and execution.ok:
                if isinstance(execution.payload.get("strategy"), dict):
                    self._artifacts["strategy"] = execution.payload["strategy"]
                curve = execution.payload.get("equity_curve_downsampled")
                if curve:
                    self._artifacts["chart"] = {
                        "type": "equity_curve",
                        "title": "回测权益曲线",
                        "points": curve,
                    }
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

    def _repair_interrupted_turn(self, session: dict[str, Any]) -> None:
        """Heal a session interrupted mid-tool-call.

        If the previous run died between an assistant ``tool_calls`` message and
        its tool results, the OpenAI-protocol history is invalid and every
        following request in this session would be rejected upstream — the user
        experiences this as the session "losing its memory".  Insert synthetic
        tool results for unanswered call ids so the next turn can proceed with
        the full history intact.
        """
        messages = session.get("messages") or []
        repaired: list[dict[str, Any]] = []
        index = 0
        changed = False
        while index < len(messages):
            message = messages[index]
            repaired.append(message)
            index += 1
            calls = message.get("tool_calls") or []
            if not calls:
                continue
            # 吃掉紧随其后的既有 tool 结果。
            while index < len(messages) and messages[index].get("role") == "tool":
                repaired.append(messages[index])
                index += 1
            answered = {
                str(item.get("tool_call_id")) for item in repaired if item.get("role") == "tool"
            }
            for call in calls:
                call_id = str(call.get("id", ""))
                if call_id in answered:
                    continue
                name = str(call.get("function", {}).get("name", ""))
                repaired.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": f"（上一次运行在调用 {name or '工具'} 时被中断，没有返回结果；如需该数据请重新调用。）",
                    }
                )
                changed = True
        if changed:
            session["messages"] = repaired

    def _forced_final_answer(self, session: dict[str, Any], system_prompt: str, on_event: EventHandler) -> bool:
        """One no-tools closing call after the step budget is exhausted."""
        on_event({"type": "phase", "phase": "工具步数已达上限，正在整理已有结果作答"})
        messages = self._build_request_messages(session, system_prompt)
        try:
            content_parts: list[str] = []
            for event in self._model.chat(build_final_answer_messages(messages), tools=None):
                if event[0] == "text":
                    content_parts.append(event[1])
                    on_event({"type": "token", "text": event[1]})
                elif event[0] == "final":
                    content_parts.append(str((event[1] or {}).get("content") or ""))
            answer = "".join(content_parts).strip()
        except Exception:  # noqa: BLE001 - 收尾失败时回退到提示文案
            return False
        if not answer:
            return False
        session["messages"].append({"role": "assistant", "content": answer})
        session["display"].append(
            {"role": "assistant", "content": answer, "tool_steps": [], "ts": datetime.now(UTC).isoformat()}
        )
        session["updated_at"] = datetime.now(UTC).isoformat()
        return True

    def _archive_overflow(self, session: dict[str, Any], on_event: EventHandler) -> None:
        """Keep the live window within both the message-count and char budget.

        The cut point is extended to the next user-message boundary so an
        assistant(tool_calls)/tool pair is never split across the window edge.
        """
        messages = session["messages"]
        overflow = max(len(messages) - SHORT_TERM_WINDOW, 0)
        total_chars = sum(len(str(message.get("content") or "")) for message in messages)
        if total_chars > SHORT_TERM_MAX_CHARS:
            # 字符超限：从最旧处开始归档，直到剩余字符回到阈值内。
            dropped_chars = 0
            for index in range(len(messages)):
                if total_chars - dropped_chars <= SHORT_TERM_MAX_CHARS:
                    break
                dropped_chars += len(str(messages[index].get("content") or ""))
                overflow = max(overflow, index + 1)
        if overflow <= 0:
            return
        # 把裁剪点推到下一个 user 边界，避免 assistant(tool_calls)/tool 配对被切断。
        # 但若后面**没有** user 消息（例如窗口里全是 assistant/tool），推到末尾会
        # 让整段字符预算静默失效（窗口仍严重超预算却不归档）。此时退回字符裁剪点。
        boundary = overflow
        while boundary < len(messages) and messages[boundary].get("role") != "user":
            boundary += 1
        overflow = boundary if boundary < len(messages) else overflow
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
        # 压缩持续失败时归档只增不减，必须按条数兜底裁剪，否则会话文件会无限膨胀。
        if len(archive) > ARCHIVE_MAX_ENTRIES:
            # 丢最旧的条目，但保留一条“已丢弃 N 条”的占位说明，避免静默失忆。
            # 说明本身占 1 条，所以保留 ARCHIVE_MAX_ENTRIES - 1 条正文。
            excess = len(archive) - (ARCHIVE_MAX_ENTRIES - 1)
            archive[:] = [f"（更早的 {excess} 条对话因压缩失败已丢弃）", *archive[excess:]]
        on_event({"type": "phase", "phase": "归档短期窗口之外的对话"})

    def _consolidate_archive(self, session: dict[str, Any], on_event: EventHandler) -> None:
        """Fold archived dialogue into the rolling summary (one model call).

        Compression is deliberately batched: small archives stay in
        ``pending_archive`` (persisted with the session, so nothing is lost)
        until they are large enough to be worth a summarization call.
        """
        archive = session.get("pending_archive") or []
        if not archive:
            return
        archive_chars = sum(len(item) for item in archive)
        if len(archive) < CONSOLIDATE_MIN_ENTRIES and archive_chars < CONSOLIDATE_MIN_CHARS:
            return
        on_event({"type": "phase", "phase": "压缩进长期会话纪要"})
        existing = str(session.get("rolling_summary") or "")
        lines = [f"（既有纪要）{existing}"] if existing else []
        lines.extend(archive)
        try:
            summary = self._summarize_history_text("\n".join(lines))
        except Exception:  # noqa: BLE001 - 压缩失败不能丢归档，也不能中断本轮
            logger.warning("会话归档压缩失败；保留 pending_archive 待下次重试", exc_info=True)
            return
        if not summary:
            # 模型返回空：保留归档内容，下次达到阈值再试。
            return
        # 只有压缩成功才清空，避免上游异常时归档内容被永久丢弃。
        session["pending_archive"] = []
        session["rolling_summary"] = summary[:4000]

    def _summarize_history_text(self, history_text: str) -> str:
        final_content = ""
        for event in self._model.chat(build_compaction_messages(history_text), tools=None):
            if event[0] == "final":
                final_content = str(event[1].get("content") or "")
        return final_content[:4000]

    def _session_messages_target(self, session: dict[str, Any]) -> list[dict[str, Any]]:
        return session["messages"]
