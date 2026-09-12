"""AiService facade: the single object the HTTP service talks to.

Wires config store, LLM client, tool registry, agent loop, sessions, knowledge
index and the insight engine together.  Constructed lazily by
``DataServiceState`` so a user who never touches AI features pays nothing.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from astock_backtester.ai.agent import AgentRunner
from astock_backtester.ai.config import AiConfig, AiConfigStore, ai_base_dir_from_cache_dir
from astock_backtester.ai.context import ContextBudget, ToolResultStore
from astock_backtester.ai.digest import DigestEngine, DigestStore
from astock_backtester.ai.errors import AiNotConfigured, ai_error_code
from astock_backtester.ai.insights import HEARTBEAT_INTERVAL_SECONDS, EventBroker, InsightEngine
from astock_backtester.ai.llm_client import OpenAiCompatibleClient
from astock_backtester.ai.memory import MemoryStore, extract_memories
from astock_backtester.ai.models import AiChatRequest, AiStatusResponse
from astock_backtester.ai.prompts import build_system_prompt
from astock_backtester.ai.rag.retriever import KnowledgeIndex, build_knowledge_tool
from astock_backtester.ai.sessions import SessionStore
from astock_backtester.ai.tools.astock_data_tools import build_astock_data_tools
from astock_backtester.ai.tools.local_tools import build_local_tools
from astock_backtester.ai.tools.query_tools import build_query_tools
from astock_backtester.ai.tools.registry import ToolRegistry


class AiService:
    def __init__(self, *, cache_dir: str | Path, backend: Any, log: Any) -> None:
        base_dir = ai_base_dir_from_cache_dir(cache_dir)
        self._config_store = AiConfigStore(base_dir)
        self._sessions = SessionStore(base_dir)
        self._model = OpenAiCompatibleClient(self._config_store.load)
        self._result_store = ToolResultStore()
        self._budget = ContextBudget()
        self._registry = ToolRegistry()
        self._registry.register_all(build_local_tools(backend))
        self._registry.register_all(build_astock_data_tools(backend))
        self._registry.register_all(build_query_tools(backend))
        self._knowledge = KnowledgeIndex(
            embedder=self._model.embed,
            cache_dir=base_dir / "AI缓存",
        )
        self._registry.register(build_knowledge_tool(self._knowledge, self._budget))
        self._agent = AgentRunner(self._model, self._registry, self._result_store, self._budget)
        self._memory = MemoryStore(base_dir)
        self._digest_store = DigestStore(base_dir)
        self._broker = EventBroker()
        self._digest = DigestEngine(
            broker=self._broker,
            backend=backend,
            model_provider=lambda: self._model if self._config_store.load().is_configured() else None,
            config_provider=self._config_store.load,
            store=self._digest_store,
        )
        self._registry.register(self._build_digest_tool())
        self._engine = InsightEngine(
            self._broker,
            backend,
            model_provider=lambda: self._model if self._config_store.load().is_configured() else None,
            config_provider=self._config_store.load,
        )
        self._engine.start()
        self._digest.start()
        self._log = log
        self._log("info", f"AI 子系统已初始化：{len(self._registry.names())} 个工具（未配置模型前仅提供状态与快讯通道）")

    # ---------------------------------------------------------------- status
    def status(self) -> AiStatusResponse:
        config = self._config_store.load()
        knowledge_info = self._knowledge.info()
        return AiStatusResponse(
            configured=config.is_configured(),
            base_url=config.base_url,
            model=config.model,
            insights_enabled=config.insights_enabled and config.is_configured(),
            tool_names=self._registry.names(),
            knowledge_documents=knowledge_info["documents"],
            knowledge_chunks=knowledge_info["chunks"],
            knowledge_ready=knowledge_info["ready"],
            memory_count=self._memory.count(),
        )

    def news_digest_view(self) -> dict[str, Any]:
        return self._digest.view()

    def refresh_news_digest(self) -> dict[str, Any]:
        return self._digest.run_once(force=True)

    def _build_digest_tool(self) -> Any:
        from astock_backtester.ai.tools.registry import AiTool

        store = self._digest_store

        def execute(_: dict[str, Any]) -> dict[str, Any]:
            items = store.load()
            if not items:
                return {"ok": False, "error": "还没有 AI 聚合简报（启动且配置模型后自动生成）。"}
            rows = [
                {key: getattr(item, key) for key in ("title", "summary", "tags", "symbols", "created_at")}
                for item in items[:8]
            ]
            return {"ok": True, "items": rows}

        def summarize(payload: dict[str, Any]) -> str:
            lines = ["AI 聚合要点："]
            for item in payload.get("items", []):
                lines.append(f"- {item.get('title')}｜{item.get('summary')}")
            return "\n".join(lines)

        return AiTool(
            name="latest_market_digest",
            description="读取启动时 AI 自动聚合的多源市场要点（新闻/涨停池/行情/复盘），回答'今日发生了什么/最新消息'前先调用。",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            executor=execute,
            summarizer=summarize,
        )

    def reveal_api_key(self) -> str:
        return self._config_store.load().api_key

    def config_view(self) -> dict[str, Any]:
        return self._config_store.masked_view()

    def save_config(self, payload: dict[str, Any]) -> dict[str, Any]:

        current = self._config_store.load()
        merged = AiConfig(
            base_url=str(payload.get("base_url", current.base_url)),
            api_key=str(payload.get("api_key", "") or ""),
            model=str(payload.get("model", current.model)),
            embedding_model=str(payload.get("embedding_model", current.embedding_model)),
            api_style=str(payload.get("api_style", current.api_style)),
            temperature=float(payload.get("temperature", current.temperature)),
            max_steps=int(payload.get("max_steps", current.max_steps)),
            insights_enabled=bool(payload.get("insights_enabled", current.insights_enabled)),
            insight_max_per_hour=int(payload.get("insight_max_per_hour", current.insight_max_per_hour)),
        )
        saved = self._config_store.save(merged)
        return {"ok": True, "configured": saved.is_configured(), **self._config_store.masked_view()}

    # ------------------------------------------------------------------ chat
    def chat_stream(self, request: AiChatRequest) -> Iterator[dict[str, Any]]:
        config = self._config_store.load()
        if not config.is_configured():
            raise AiNotConfigured("AI 服务尚未配置，请先在设置中填写 base_url、API Key 和模型名。")
        session = (
            self._sessions.get(request.session_id) if request.session_id else None
        ) or self._sessions.create(title=request.message[:20])
        session_id = str(session.get("session_id"))
        yield {"type": "session", "session_id": session_id, "title": session.get("title")}

        system_prompt = build_system_prompt(self._knowledge.is_ready())
        memory_context = self._memory.recall_context()
        if memory_context:
            system_prompt += f"\n\n## 用户长期记忆（个性化参考）\n{memory_context}"

        events: queue.Queue[dict[str, Any] | None] = queue.Queue()
        error_holder: list[dict[str, Any]] = []

        def on_event(event: dict[str, Any]) -> None:
            events.put(event)

        def worker() -> None:
            try:
                artifacts = self._agent.run(
                    session=session,
                    user_message=request.message,
                    system_prompt=system_prompt,
                    max_steps=config.max_steps,
                    context=request.context.model_dump() if request.context else None,
                    on_event=on_event,
                )
                events.put(
                    {
                        "type": "result",
                        "session_id": session_id,
                        "display": session.get("display", []),
                        "strategy": artifacts.get("strategy"),
                        "updated_at": datetime.now(UTC).isoformat(),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - converted to a stable error event
                error_holder.append({"type": "error", "code": ai_error_code(exc), "message": str(exc)})
            finally:
                # 哨兵必须在 finally 里：save/其他异常不能挂死消费端线程
                self._sessions.save(session)
                events.put(None)
            if error_holder:
                return
            # 长期记忆提取在哨兵之后的独立 daemon 线程，绝不阻塞事件流
            threading.Thread(
                target=self._remember_from, args=(session,), name="ai-memory-extract", daemon=True
            ).start()

        thread = threading.Thread(target=worker, name="ai-agent-run", daemon=True)
        thread.start()
        try:
            while True:
                event = events.get()
                if event is None:
                    break
                yield event
        finally:
            self._sessions.save(session)
        if error_holder:
            yield error_holder[0]

    def _remember_from(self, session: dict[str, Any]) -> None:
        """Best-effort long-term memory extraction after a completed turn."""
        try:
            if not self._config_store.load().is_configured():
                return
            turns = session.get("display", [])[-4:]
            dialogue = "\n".join(f"{turn.get('role')}: {str(turn.get('content'))[:400]}" for turn in turns)
            for content, category in extract_memories(self._model, dialogue):
                self._memory.remember(content, category)
        except Exception:  # noqa: BLE001 - memory must never break a chat turn
            pass

    def delete_session(self, session_id: str) -> bool:
        return self._sessions.delete(session_id)

    def list_sessions(self) -> list[dict[str, Any]]:
        return self._sessions.list_sessions()

    # ---------------------------------------------------------------- events
    def events_stream(self) -> Iterator[dict[str, Any]]:
        stream = self._broker.subscribe()
        try:
            while True:
                try:
                    event = stream.get(timeout=HEARTBEAT_INTERVAL_SECONDS)
                    yield event
                except queue.Empty:
                    yield {"type": "heartbeat", "timestamp": datetime.now(UTC).isoformat()}
        finally:
            self._broker.unsubscribe(stream)
