from __future__ import annotations

from typing import Any

from astock_backtester.ai.memory import MemoryStore, extract_memories


class ScriptedModel:
    def __init__(self, content: str) -> None:
        self.content = content
        self.prompts: list[list[dict[str, Any]]] = []

    def chat(self, messages: list[dict[str, Any]], *, tools: Any = None):
        self.prompts.append(messages)
        yield ("final", {"content": self.content, "tool_calls": None})

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0]]


def test_store_remember_dedupe_and_eviction(tmp_path):
    store = MemoryStore(tmp_path)
    assert store.count() == 0
    first = store.remember("用户长期关注 600519", "watchlist")
    assert first is not None
    again = store.remember("用户长期关注   600519", "watchlist")  # 空白归一后同内容 → 刷新而非新增
    assert store.count() == 1
    assert again is not None and again.id == first.id
    assert again.hits == 1

    for index in range(5):
        store.remember(f"事实 {index}", "fact")
    assert store.count() == 6
    assert store.forget(first.id) is True
    assert store.count() == 5
    assert store.forget(first.id) is False


def test_recall_context_renders_lines(tmp_path):
    store = MemoryStore(tmp_path)
    store.remember("用户关注 600519", "watchlist")
    store.remember("用户偏好低换手策略", "preference")
    context = store.recall_context()
    assert "[watchlist] 用户关注 600519" in context
    assert "[preference] 用户偏好低换手策略" in context
    empty = MemoryStore(tmp_path / "empty")
    assert empty.recall_context() == ""


def test_extract_memories_parses_model_json(tmp_path):
    model = ScriptedModel('[{"content": "用户持仓 300750", "category": "watchlist"}, {"content": "偏好 20 日线", "category": "bogus"}]')
    extracted = extract_memories(model, "user: 我关注宁德时代\nassistant: 好的")
    assert extracted == [("用户持仓 300750", "watchlist"), ("偏好 20 日线", "fact")]
    assert len(model.prompts) == 1
    assert "对话" in model.prompts[0][0]["content"]


def test_extract_memories_tolerates_garbage():
    assert extract_memories(ScriptedModel("没有可提取的内容"), "user: 你好") == []
    assert extract_memories(ScriptedModel("前缀 [1, 2"), "user: 你好") == []
    assert extract_memories(ScriptedModel("[]"), "") == []
