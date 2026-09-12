from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from astock_backtester.ai.config import AiConfig
from astock_backtester.ai.insights import EventBroker, InsightEngine
from astock_backtester.models import (
    MarketBreadth,
    MarketIndexQuote,
    MarketNewsItem,
    MarketNewsResponse,
    RealtimeMarketSnapshot,
    RiskAlertsResponse,
)


class ScriptedModel:
    def __init__(self, content: str) -> None:
        self.content = content
        self.prompts: list[list[dict[str, Any]]] = []

    def chat(self, messages: list[dict[str, Any]], *, tools=None):
        self.prompts.append(messages)
        yield ("final", {"content": self.content, "tool_calls": None})

    def embed(self, texts):
        return [[0.0]]


def _news(titles: list[str]) -> MarketNewsResponse:
    return MarketNewsResponse(
        updated_at=datetime.now(UTC),
        source="fake",
        items=[MarketNewsItem(title=title, source="财联社") for title in titles],
    )


def _snapshot(up: int, total: int) -> RealtimeMarketSnapshot:
    return RealtimeMarketSnapshot(
        status="live",
        source="fake",
        updated_at=datetime.now(UTC),
        indexes=[MarketIndexQuote(symbol="sh000001", name="上证指数", last=3100.0, source="fake")],
        breadth=MarketBreadth(up=up, down=total - up, flat=0, total=total, source="fake"),
        message="ok",
    )


class FakeBackend:
    def __init__(self) -> None:
        self.news_titles: list[str] = ["第一条新闻"]
        self.breadth_up = 2600
        self.breadth_total = 5200
        self.risk_count = 3

    news_provider = SimpleNamespace()
    realtime_provider = SimpleNamespace()
    risk_provider = SimpleNamespace()

    def latest_news(self):
        return _news(self.news_titles)

    def snapshot(self):
        return _snapshot(self.breadth_up, self.breadth_total)

    def alerts(self):
        return RiskAlertsResponse(updated_at=datetime.now(UTC), source="fake", items=[])

    def log(self, level, message):
        pass


def _engine(backend: FakeBackend, broker: EventBroker, model_content: str = "NO_INSIGHT", config: AiConfig | None = None):
    model = ScriptedModel(model_content)
    engine = InsightEngine(
        broker,
        backend,
        model_provider=lambda: model,
        config_provider=lambda: config or AiConfig(base_url="http://x", api_key="k", model="m"),
    )
    return engine, model


def _wire(backend: FakeBackend) -> None:
    backend.news_provider = SimpleNamespace(latest_news=backend.latest_news)
    backend.realtime_provider = SimpleNamespace(market_snapshot=backend.snapshot)
    backend.risk_provider = SimpleNamespace(current_alerts=backend.alerts)


def test_broker_publish_and_unsubscribe():
    broker = EventBroker()
    stream = broker.subscribe()
    broker.publish({"type": "data_fresh", "module": "news"})
    assert stream.get(timeout=1)["module"] == "news"
    broker.unsubscribe(stream)
    broker.publish({"type": "data_fresh", "module": "market"})
    assert stream.empty()


def test_data_fresh_emitted_without_llm():
    broker = EventBroker()
    stream = broker.subscribe()
    backend = FakeBackend()
    _wire(backend)
    engine, _ = _engine(backend, broker)
    engine.tick()
    backend.news_titles = ["全新的新闻"]
    backend.breadth_up = 1000  # 大幅变化
    engine.tick()
    events = []
    while not stream.empty():
        events.append(stream.get_nowait())
    types = [event["type"] for event in events]
    assert "data_fresh" in types
    assert events[0]["module"] == "news"
    # 模型返回 NO_INSIGHT → 无 insight
    assert "insight" not in types


def test_insight_generated_when_configured_and_capped():
    broker = EventBroker()
    stream = broker.subscribe()
    backend = FakeBackend()
    _wire(backend)
    config = AiConfig(base_url="http://x", api_key="k", model="m", insight_max_per_hour=1)
    engine, model = _engine(backend, broker, model_content="红盘占比异常，注意情绪退潮风险", config=config)
    backend.breadth_up = 500  # ratio 0.096 < 0.25 → 极端
    engine.tick()
    events = []
    while not stream.empty():
        events.append(stream.get_nowait())
    insights = [event for event in events if event["type"] == "insight"]
    assert len(insights) == 1
    assert insights[0]["insight"]["source"] == "ai-insight"
    assert "AI 生成" in insights[0]["insight"]["disclaimer"]
    assert model.prompts  # 确实调用了模型

    # 小时级上限：cap=1 → 第二次极端不再生成
    backend.breadth_up = 100
    engine.tick()
    drained = []
    while not stream.empty():
        drained.append(stream.get_nowait())
    assert not [event for event in drained if event["type"] == "insight"]


def test_insight_disabled_or_zero_cap_never_calls_model():
    broker = EventBroker()
    broker.subscribe()
    backend = FakeBackend()
    _wire(backend)
    disabled_config = AiConfig(base_url="http://x", api_key="k", model="m", insights_enabled=False)
    engine, model = _engine(backend, broker, model_content="内容", config=disabled_config)
    backend.breadth_up = 100
    engine.tick()
    assert not model.prompts

    zero_cap_config = AiConfig(base_url="http://x", api_key="k", model="m", insight_max_per_hour=0)
    engine2, model2 = _engine(backend, broker, model_content="内容", config=zero_cap_config)
    backend.breadth_up = 50
    engine2._last_breadth_ratio = 0.5
    engine2.tick()
    assert not model2.prompts
