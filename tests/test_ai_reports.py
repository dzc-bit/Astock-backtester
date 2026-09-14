from __future__ import annotations

from typing import Any

import pytest
from astock_backtester.ai.config import AiConfig
from astock_backtester.ai.reports import (
    ReportStore,
    ScheduledReportEngine,
    _safe_report_name,
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


class FakeBackend:
    def __init__(self) -> None:
        self.logs: list[tuple[str, str]] = []

    def log(self, level: str, message: str) -> None:
        self.logs.append((level, message))


def test_report_store_roundtrip_and_name_safety(tmp_path):
    store = ReportStore(tmp_path)
    meta = store.save("复盘报告-20260913-1530.md", "# 报告\n正文")
    assert meta.name == "复盘报告-20260913-1530.md"
    assert store.read(meta.name) == "# 报告\n正文"
    listing = store.list()
    assert [item.name for item in listing] == ["复盘报告-20260913-1530.md"]
    assert store.read("../逃逸.md") is None
    assert store.read("https://evil.example.md") is None
    assert _safe_report_name("子/目录.md") is None
    assert _safe_report_name(".hidden.md") is None


def test_review_report_uses_model_when_available(tmp_path):
    backend = FakeBackend()
    store = ReportStore(tmp_path)
    model = ScriptedModel("# 收盘复盘正文")
    engine = ScheduledReportEngine(
        backend=backend,
        model_provider=lambda: model,
        config_provider=lambda: AiConfig(base_url="http://x", api_key="k", model="m", report_enabled=True),
        store=store,
        digest_items_provider=lambda: [{"title": "要点", "summary": "内容"}],
        ai_base_dir=tmp_path,
    )
    outcome = engine.generate_review_report()
    assert outcome["ok"] is True
    saved = store.list()[0]
    assert saved.name.startswith("复盘报告-")
    content = store.read(saved.name)
    assert "# 收盘复盘正文" in content
    # 提示词注入了日期与免责要求
    prompt_text = str(model.prompts[0][0]["content"])
    assert "收盘复盘" in prompt_text
    assert "要点" in prompt_text


def test_review_report_falls_back_to_data_digest_without_model(tmp_path):
    backend = FakeBackend()
    store = ReportStore(tmp_path)
    engine = ScheduledReportEngine(
        backend=backend,
        model_provider=lambda: None,
        config_provider=lambda: AiConfig(base_url="http://x", api_key="k", model="m", report_enabled=True),
        store=store,
        digest_items_provider=lambda: [{"title": "要点", "summary": "内容"}],
        ai_base_dir=tmp_path,
    )
    outcome = engine.generate_review_report()
    assert outcome["ok"] is True
    content = store.read(store.list()[0].name)
    assert "数据摘要版" in content
    assert "要点" in content


def test_review_report_skips_when_disabled(tmp_path):
    engine = ScheduledReportEngine(
        backend=FakeBackend(),
        model_provider=lambda: None,
        config_provider=lambda: AiConfig(base_url="http://x", api_key="k", model="m", report_enabled=False),
        store=ReportStore(tmp_path),
        ai_base_dir=tmp_path,
    )
    assert engine.generate_review_report() == {"ok": False, "skipped": "disabled"}


def test_tick_runs_each_job_once_per_day(tmp_path, monkeypatch):
    engine = ScheduledReportEngine(
        backend=FakeBackend(),
        model_provider=lambda: None,
        config_provider=lambda: AiConfig(
            base_url="http://x",
            api_key="k",
            model="m",
            report_enabled=True,
            evolution_enabled=True,
        ),
        store=ReportStore(tmp_path),
        digest_items_provider=lambda: [{"title": "t", "summary": "s"}],
        ai_base_dir=tmp_path,
    )
    monkeypatch.setattr(ScheduledReportEngine, "_time_matches", staticmethod(lambda now, hhmm: True))
    monkeypatch.setattr(engine, "generate_evolution_report", lambda: {"ok": False, "skipped": "no_saved_strategies"})
    first = engine.tick()
    assert sorted(first["ran"]) == ["evolution", "report"]
    # 同一天内不再重复执行
    second = engine.tick()
    assert second["ran"] == []


def test_evolution_report_writes_markdown_with_drift(tmp_path, monkeypatch):
    (tmp_path / "策略配置").mkdir()
    (tmp_path / "策略配置" / "saved-strategies.json").write_text(
        '[{"id": "s1", "name": "测试策略", "saved_at": "now", "strategy": {"name": "测试策略"}}]',
        encoding="utf-8",
    )
    store = ReportStore(tmp_path)
    engine = ScheduledReportEngine(
        backend=FakeBackend(),
        model_provider=lambda: None,
        config_provider=lambda: AiConfig(base_url="http://x", api_key="k", model="m", evolution_enabled=True),
        store=store,
        ai_base_dir=tmp_path,
    )
    monkeypatch.setattr(engine, "_latest_data_date", lambda: "2026-09-11")

    def fake_evolution(backend, preset, start_date, end_date, *, frame=None):
        return {
            "name": preset.get("name"),
            "metrics": {
                "total_return_pct": 0.25,
                "annualized_return_pct": 0.5,
                "max_drawdown_pct": -0.1,
                "win_rate_pct": 0.55,
                "trade_count": 40,
            },
            "variants": [],
            "suggestion": "当前默认参数已接近最优。",
        }

    monkeypatch.setattr("astock_backtester.ai.reports._evolution_for_strategy", fake_evolution)
    outcome = engine.generate_evolution_report()
    assert outcome["ok"] is True
    content = store.read(store.list()[0].name)
    assert "策略库自动体检报告" in content
    assert "测试策略" in content
    assert "+25.00%" in content

    # 第二次体检带漂移对比
    def fake_evolution_down(backend, preset, start_date, end_date, *, frame=None):
        row = fake_evolution(backend, preset, start_date, end_date)
        row["metrics"] = dict(row["metrics"], total_return_pct=0.10)
        return row

    monkeypatch.setattr("astock_backtester.ai.reports._evolution_for_strategy", fake_evolution_down)
    outcome2 = engine.generate_evolution_report(force=True)
    assert outcome2["ok"] is True
    content2 = store.read(outcome2["name"])
    assert "较上次体检" in content2
    assert "-15.0%" in content2


def test_evolution_report_skips_without_saved_strategies(tmp_path):
    engine = ScheduledReportEngine(
        backend=FakeBackend(),
        model_provider=lambda: None,
        config_provider=lambda: AiConfig(base_url="http://x", api_key="k", model="m", evolution_enabled=True),
        store=ReportStore(tmp_path),
        ai_base_dir=tmp_path,
    )
    assert engine.generate_evolution_report() == {"ok": False, "skipped": "no_saved_strategies"}


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("15:30", "15:30"),
        ("9:05", "09:05"),
        ("25:00", "15:30"),
        ("abc", "15:30"),
        ("", "15:30"),
    ],
)
def test_report_time_fallbacks(raw, expected):
    from astock_backtester.ai.config import normalize_hhmm

    assert normalize_hhmm(raw, "15:30") == expected
