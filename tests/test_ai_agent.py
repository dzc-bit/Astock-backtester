from __future__ import annotations

from typing import Any

from astock_backtester.ai.agent import AgentRunner
from astock_backtester.ai.context import ContextBudget, ToolResultStore
from astock_backtester.ai.tools.registry import AiTool, ToolRegistry


class FakeModel:
    """Scripted ChatModel: pops scripted turn sequences, repeats the last one."""

    def __init__(self, script: list[list[tuple[str, Any]]]) -> None:
        self.script = script
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None):
        self.calls.append({"messages": messages, "tools": tools})
        if not self.script:
            item = self._last
        else:
            item = self.script.pop(0)
            self._last = item
        yield from item

    _last: list[tuple[str, Any]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text))] for text in texts]


def _final(content: str | None = None, tool_calls: list[dict[str, Any]] | None = None):
    return ("final", {"content": content, "tool_calls": tool_calls})


def _tool_call(call_id: str, name: str, arguments: str) -> dict[str, Any]:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        AiTool(
            name="echo_tool",
            description="echo",
            parameters={"type": "object", "properties": {}},
            executor=lambda args: {"ok": True, "value": args.get("x"), "diagnostics": ["d1"]},
            summarizer=lambda payload: f"value={payload.get('value')}",
        )
    )
    return registry


def _session() -> dict[str, Any]:
    return {
        "session_id": "s1",
        "title": "新会话",
        "created_at": "now",
        "updated_at": "now",
        "rolling_summary": "",
        "messages": [],
        "display": [],
    }


def test_agent_runs_tool_then_answers():
    model = FakeModel(
        [
            [_final(tool_calls=[_tool_call("t1", "echo_tool", '{"x": 7}')])],
            [_final(content="结论 7")],
        ]
    )
    runner = AgentRunner(model, _registry(), ToolResultStore(), ContextBudget())
    events: list[dict[str, Any]] = []
    session = _session()
    runner.run(
        session=session,
        user_message="看看 7",
        system_prompt="SYS",
        max_steps=4,
        on_event=events.append,
    )
    types = [event["type"] for event in events]
    assert types[0] == "phase"
    assert "tool_call" in types and "tool_result" in types
    tool_result = next(event for event in events if event["type"] == "tool_result")
    assert tool_result["ok"] is True and tool_result["summary"] == "value=7"
    tool_call = next(event for event in events if event["type"] == "tool_call")
    assert tool_call["args"] == {"x": 7}

    tool_messages = [message for message in session["messages"] if message.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["content"].startswith("value=7")  # digest only, no full payload
    assert session["display"][-1]["content"] == "结论 7"
    assert session["display"][-2]["tool_steps"][0]["name"] == "echo_tool"

    # full payload kept in the store, referenced by call id
    second_model_call = model.calls[-1]
    tool_messages_in_request = [m for m in second_model_call["messages"] if m.get("role") == "tool"]
    assert tool_messages_in_request[0]["content"].startswith("value=7")


def test_agent_stops_at_max_steps():
    model = FakeModel([[_final(tool_calls=[_tool_call("t1", "echo_tool", '{"x": 1}')])] for _ in range(4)])
    runner = AgentRunner(model, _registry(), ToolResultStore(), ContextBudget())
    events: list[dict[str, Any]] = []
    session = _session()
    runner.run(session=session, user_message="q", system_prompt="SYS", max_steps=2, on_event=events.append)
    assert any("上限" in str(message.get("content")) for message in session["messages"])
    assert any(event["type"] == "phase" and "上限" in event.get("phase", "") for event in events)


def test_agent_archives_overflow_and_consolidates_summary():
    model = FakeModel([[_final(content="纪要内容")], [_final(content="最终答案")]])
    runner = AgentRunner(model, _registry(), ToolResultStore(), ContextBudget())
    session = _session()
    for index in range(12):
        session["messages"].append({"role": "user", "content": f"历史消息 {index} " + "x" * 2000})
    events: list[dict[str, Any]] = []
    runner.run(session=session, user_message="继续", system_prompt="SYS", max_steps=3, on_event=events.append)

    assert session["rolling_summary"] == "纪要内容"
    assert session.get("pending_archive") == []
    # 短期窗口 10 条：12 条旧消息 + 新用户消息 → 归档 3 条，保留 10 条，再加回答 1 条
    assert len(session["messages"]) == 11
    assert any(event["type"] == "phase" and "归档" in event.get("phase", "") for event in events)
    assert any(event["type"] == "phase" and "压缩" in event.get("phase", "") for event in events)
    request_messages = model.calls[-1]["messages"]
    assert any("会话纪要" in str(message.get("content")) for message in request_messages if message["role"] == "system")


def test_agent_window_stays_at_ten_without_archived_turns():
    model = FakeModel([[_final(content="答案")]])
    runner = AgentRunner(model, _registry(), ToolResultStore(), ContextBudget())
    session = _session()
    for index in range(9):
        session["messages"].append({"role": "user", "content": f"历史 {index}"})
    runner.run(session=session, user_message="最新问题", system_prompt="SYS", max_steps=2, on_event=lambda event: None)
    # 未超窗口 → 不归档、不调用纪要模型；窗口内 10 条 + 回答 1 条
    assert session["rolling_summary"] == ""
    assert len(model.calls) == 1
    request_messages = model.calls[0]["messages"]
    assert len(request_messages) == 11  # 1 system + 10 窗口消息


def test_agent_budget_digests_long_tool_summaries():
    long_summary = "y" * 5_000
    registry = ToolRegistry()
    registry.register(
        AiTool(
            name="noisy_tool",
            description="noisy",
            parameters={"type": "object", "properties": {}},
            executor=lambda args: {"ok": True},
            summarizer=lambda payload: long_summary,
        )
    )
    model = FakeModel(
        [
            [_final(tool_calls=[_tool_call("t1", "noisy_tool", "{}")])],
            [_final(content="done")],
        ]
    )
    budget = ContextBudget(digest_chars=100)
    runner = AgentRunner(model, registry, ToolResultStore(), budget)
    session = _session()
    runner.run(session=session, user_message="q", system_prompt="SYS", max_steps=2, on_event=lambda event: None)
    tool_message = next(message for message in session["messages"] if message.get("role") == "tool")
    assert len(tool_message["content"]) < 200
