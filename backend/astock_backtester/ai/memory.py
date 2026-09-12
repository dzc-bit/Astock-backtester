"""Long-term memory for the AI assistant.

Layered memory design, inspired by MemGPT/Letta (tiered core vs archival
memory) and mem0 (extraction + consolidation), scaled down to a local-first
desktop app:

- Short term: the agent's protocol-message window is capped (10 messages);
  everything older is folded into the session's rolling summary
  (see ``agent.AgentRunner``).
- Long term: durable user facts (preferences, watchlist symbols, recurring
  parameters) are extracted by the LLM after each turn, consolidated into a
  JSON store under ``运行产物/AI记忆`` (dedupe by content, LRU-ish eviction by
  update time), and the top records are injected into the system prompt.

Extraction failures are always non-fatal: memory enriches the assistant but
must never break a chat turn.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

MEMORY_DIR_NAME = "AI记忆"
MEMORY_FILE_NAME = "memory.json"
MAX_RECORDS = 200
MAX_CONTENT_CHARS = 160
RECALL_LIMIT = 12
RECALL_BUDGET_CHARS = 1_600

MEMORY_EXTRACT_PROMPT = """从这段最新对话里提取应当长期记住的"用户事实"。
只提取持久信息：关注/持仓的股票代码、策略偏好、参数习惯、明确的操作指令结果（例如"已把 600519 数据补齐到 2026-09"）。
不要提取：一次性行情数字、你的回答正文、临时上下文。
每条不超过 60 字；最多 3 条；没有值得记的就输出 []。
只输出 JSON 数组，格式：[{{"content": "...", "category": "watchlist|preference|fact|strategy"}}]

对话：
{dialogue}"""


@dataclass
class MemoryRecord:
    id: str
    content: str
    category: str
    created_at: str
    updated_at: str
    hits: int = 0


class MemoryStore:
    def __init__(self, ai_base_dir: str | Path) -> None:
        self._path = Path(ai_base_dir) / MEMORY_DIR_NAME / MEMORY_FILE_NAME

    def load(self) -> list[MemoryRecord]:
        if not self._path.exists():
            return []
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        records = []
        for item in payload:
            if isinstance(item, dict) and item.get("id") and item.get("content"):
                try:
                    records.append(MemoryRecord(**item))
                except TypeError:
                    continue
        return records

    def save(self, records: list[MemoryRecord]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps([asdict(record) for record in records], ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        os.replace(tmp_path, self._path)

    def remember(self, content: str, category: str = "fact") -> MemoryRecord | None:
        """Add or consolidate a memory (same normalized content refreshes it)."""
        normalized = re.sub(r"\s+", "", content)[:MAX_CONTENT_CHARS]
        if not normalized:
            return None
        records = self.load()
        now = datetime.now(UTC).isoformat()
        for record in records:
            if re.sub(r"\s+", "", record.content) == normalized:
                record.updated_at = now
                record.hits += 1
                self.save(records)
                return record
        record = MemoryRecord(id=uuid4().hex[:12], content=content[:MAX_CONTENT_CHARS], category=category, created_at=now, updated_at=now)
        records.append(record)
        records.sort(key=lambda item: item.updated_at, reverse=True)
        if len(records) > MAX_RECORDS:
            records = records[:MAX_RECORDS]
        self.save(records)
        return record

    def forget(self, memory_id: str) -> bool:
        records = self.load()
        remaining = [record for record in records if record.id != memory_id]
        if len(remaining) == len(records):
            return False
        self.save(remaining)
        return True

    def recall_context(self) -> str:
        records = sorted(self.load(), key=lambda item: item.updated_at, reverse=True)[:RECALL_LIMIT]
        if not records:
            return ""
        lines = []
        for record in records:
            content = record.content[:MAX_CONTENT_CHARS]
            lines.append(f"- [{record.category}] {content}")
        return "\n".join(lines)[:RECALL_BUDGET_CHARS]

    def count(self) -> int:
        return len(self.load())


def extract_memories(model: Any, dialogue_text: str) -> list[tuple[str, str]]:
    """Best-effort extraction; returns (content, category) pairs.

    ``model`` only needs ``chat(messages, tools=None)`` yielding ("final", ...).
    """
    if not dialogue_text.strip():
        return []
    final_content = ""
    for event in model.chat([{"role": "user", "content": MEMORY_EXTRACT_PROMPT.format(dialogue=dialogue_text)}], tools=None):
        if event[0] == "final":
            final_content = str(event[1].get("content") or "")
    start = final_content.find("[")
    end = final_content.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        payload = json.loads(final_content[start : end + 1])
    except json.JSONDecodeError:
        return []
    extracted: list[tuple[str, str]] = []
    if not isinstance(payload, list):
        return []
    for item in payload[:3]:
        if isinstance(item, dict) and str(item.get("content", "")).strip():
            category = str(item.get("category", "fact"))
            if category not in ("watchlist", "preference", "fact", "strategy"):
                category = "fact"
            extracted.append((str(item["content"])[:MAX_CONTENT_CHARS], category))
    return extracted
