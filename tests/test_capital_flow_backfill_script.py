from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd


def load_backfill_script():
    script_path = Path(__file__).parents[1] / "scripts" / "run-capital-flow-backfill.py"
    spec = importlib.util.spec_from_file_location("run_capital_flow_backfill", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_select_backfill_symbols_prioritizes_missing_flow_rows(tmp_path):
    module = load_backfill_script()
    frame = pd.DataFrame(
        {
            "symbol": ["000001", "000001", "000002", "000003"],
            "trade_date": pd.to_datetime(["2026-06-05", "2026-06-06", "2026-06-05", "2026-06-05"]),
            "main_net_inflow": [1.0, float("nan"), float("nan"), 3.0],
        }
    )

    symbols = module.select_backfill_symbols(frame, explicit_symbols=[], completed_symbols=set(), limit=0)

    assert symbols == ["000001", "000002"]


def test_select_backfill_symbols_uses_explicit_symbols_when_daily_rows_are_missing(tmp_path):
    module = load_backfill_script()

    symbols = module.select_backfill_symbols(
        pd.DataFrame(),
        explicit_symbols=["1", "SZ000002", "600000.SH"],
        completed_symbols=set(),
        limit=2,
    )

    assert symbols == ["000001", "000002"]


def test_select_backfill_symbols_uses_provider_symbols_when_daily_rows_are_missing(tmp_path):
    module = load_backfill_script()

    symbols = module.select_backfill_symbols(
        pd.DataFrame(),
        explicit_symbols=[],
        completed_symbols={"000002"},
        limit=2,
        provider_symbols=["SZ000002", "600000.SH", "1"],
    )

    assert symbols == ["000001", "600000"]


def test_select_backfill_symbols_adds_provider_symbols_after_missing_daily_rows(tmp_path):
    module = load_backfill_script()
    frame = pd.DataFrame(
        {
            "symbol": ["000003", "000003"],
            "trade_date": pd.to_datetime(["2026-06-05", "2026-06-08"]),
            "main_net_inflow": [float("nan"), float("nan")],
        }
    )

    symbols = module.select_backfill_symbols(
        frame,
        explicit_symbols=[],
        completed_symbols=set(),
        limit=0,
        provider_symbols=["000001", "000003"],
    )

    assert symbols == ["000003", "000001"]


def test_load_provider_symbols_uses_configured_provider_without_daily_rows(monkeypatch):
    module = load_backfill_script()

    class FakeProvider:
        def list_symbols(self):
            return ["SZ000001", "600000.SH"]

    monkeypatch.setattr(module, "ADataProvider", lambda: object())
    monkeypatch.setattr(module, "AkshareProvider", lambda: object())
    monkeypatch.setattr(module, "HttpAStockProvider", lambda: object())
    monkeypatch.setattr(module, "CompositeProvider", lambda providers: FakeProvider())

    assert module.load_provider_symbols() == ["000001", "600000"]


def test_supervised_backfill_stops_after_consecutive_failures(tmp_path):
    module = load_backfill_script()
    events_path = tmp_path / "capital-flow-progress.jsonl"

    def failing_runner(symbol: str) -> dict:
        return {
            "status": "partial",
            "imported_rows": 0,
            "failures": [{"symbol": symbol, "code": "network_error", "message": "remote closed"}],
            "diagnostics": [],
        }

    summary = module.run_supervised_backfill(
        symbols=["000001", "000002", "000003"],
        run_symbol=failing_runner,
        progress_path=events_path,
        max_consecutive_failures=2,
        sleep_seconds=0,
    )

    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert summary["processed"] == 2
    assert summary["stopped_reason"] == "max_consecutive_failures"
    assert events[-1]["event"] == "stopped"
    assert events[-1]["consecutive_failures"] == 2


def test_supervised_backfill_treats_already_complete_result_as_completed(tmp_path):
    module = load_backfill_script()
    events_path = tmp_path / "capital-flow-progress.jsonl"

    def already_complete_runner(symbol: str) -> dict:
        return {
            "status": "ok",
            "imported_rows": 0,
            "failures": [],
            "diagnostics": [{"code": "capital_flow_backfill_not_needed"}],
        }

    summary = module.run_supervised_backfill(
        symbols=["000001"],
        run_symbol=already_complete_runner,
        progress_path=events_path,
        max_consecutive_failures=1,
        sleep_seconds=0,
    )

    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert summary["completed"] == 1
    assert summary["failed"] == 0
    assert summary["stopped_reason"] is None
    assert events[1]["status"] == "completed"
    assert events[1]["status_code"] == "ok"
    assert events[-1]["event"] == "finish"


def test_supervised_backfill_processes_symbols_in_batches_and_writes_resume_events(tmp_path):
    module = load_backfill_script()
    events_path = tmp_path / "capital-flow-progress.jsonl"
    calls = []

    def batch_runner(symbols: list[str]) -> dict:
        calls.append(list(symbols))
        return {
            "status": "ok",
            "imported_rows": len(symbols),
            "returned_rows": len(symbols) * 2,
            "fetched_symbols": symbols,
            "missing_symbols": [],
            "skipped_symbols": [],
            "failures": [],
            "diagnostics": [],
        }

    summary = module.run_supervised_backfill(
        symbols=["000001", "000002", "000003"],
        run_symbol=lambda symbol: None,
        run_batch=batch_runner,
        batch_size=2,
        progress_path=events_path,
        max_consecutive_failures=2,
        sleep_seconds=0,
    )

    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    completed_events = [event for event in events if event.get("status") == "completed"]
    assert calls == [["000001", "000002"], ["000003"]]
    assert summary["processed"] == 3
    assert summary["completed"] == 3
    assert summary["failed"] == 0
    assert summary["imported_rows"] == 3
    assert [event["symbol"] for event in completed_events] == ["000001", "000002", "000003"]
    assert all(event["completion_kind"] == "imported" for event in completed_events)
    assert module.load_completed_symbols(events_path) == {"000001", "000002", "000003"}


def test_supervised_backfill_batch_summary_uses_exact_imported_and_returned_rows(tmp_path):
    module = load_backfill_script()
    events_path = tmp_path / "capital-flow-progress.jsonl"

    def batch_runner(symbols: list[str]) -> dict:
        return {
            "status": "ok",
            "imported_rows": 7,
            "returned_rows": 9,
            "fetched_symbols": symbols,
            "missing_symbols": [],
            "skipped_symbols": [],
            "failures": [],
            "diagnostics": [],
        }

    summary = module.run_supervised_backfill(
        symbols=["000001", "000002"],
        run_symbol=lambda symbol: None,
        run_batch=batch_runner,
        batch_size=2,
        progress_path=events_path,
        max_consecutive_failures=2,
        sleep_seconds=0,
    )

    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    batch_events = [event for event in events if event.get("event") == "batch"]
    completed_events = [event for event in events if event.get("status") == "completed"]
    assert summary["imported_rows"] == 7
    assert summary["returned_rows"] == 9
    assert batch_events == [
        {
            "event": "batch",
            "time": batch_events[0]["time"],
            "index": 1,
            "total_batches": 1,
            "symbols": ["000001", "000002"],
            "status_code": "ok",
            "imported_rows": 7,
            "returned_rows": 9,
            "seconds": batch_events[0]["seconds"],
        }
    ]
    assert all(event["completion_kind"] == "imported" for event in completed_events)
    assert module.load_completed_symbols(events_path) == {"000001", "000002"}


def test_supervised_backfill_batch_symbol_events_use_per_symbol_row_counts(tmp_path):
    module = load_backfill_script()
    events_path = tmp_path / "capital-flow-progress.jsonl"

    def batch_runner(symbols: list[str]) -> dict:
        return {
            "status": "ok",
            "imported_rows": 5,
            "returned_rows": 7,
            "rows": [
                {"symbol": "000001", "trade_date": "2026-06-03", "main_net_inflow": 1.0},
                {"symbol": "000001", "trade_date": "2026-06-04", "main_net_inflow": 2.0},
                {"symbol": "000001", "trade_date": "2026-06-05", "main_net_inflow": 3.0},
                {"symbol": "000002", "trade_date": "2026-06-04", "main_net_inflow": 4.0},
                {"symbol": "000002", "trade_date": "2026-06-05", "main_net_inflow": 5.0},
            ],
            "diagnostics": [
                {
                    "code": "capital_flow_symbol_summary",
                    "symbol": "000001",
                    "returned_rows": 4,
                    "imported_rows": 3,
                },
                {
                    "code": "capital_flow_symbol_summary",
                    "symbol": "000002",
                    "returned_rows": 3,
                    "imported_rows": 2,
                },
            ],
            "fetched_symbols": symbols,
            "missing_symbols": [],
            "skipped_symbols": [],
            "failures": [],
        }

    summary = module.run_supervised_backfill(
        symbols=["000001", "000002"],
        run_symbol=lambda symbol: None,
        run_batch=batch_runner,
        batch_size=2,
        progress_path=events_path,
        max_consecutive_failures=2,
        sleep_seconds=0,
    )

    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    symbol_events = {
        event["symbol"]: event
        for event in events
        if event.get("status") == "completed"
    }
    assert summary["imported_rows"] == 5
    assert summary["returned_rows"] == 7
    assert symbol_events["000001"]["imported_rows"] == 3
    assert symbol_events["000001"]["returned_rows"] == 4
    assert symbol_events["000002"]["imported_rows"] == 2
    assert symbol_events["000002"]["returned_rows"] == 3


def test_supervised_backfill_batch_shortfall_marks_only_that_symbol_failed(tmp_path):
    module = load_backfill_script()
    events_path = tmp_path / "capital-flow-progress.jsonl"

    def batch_runner(symbols: list[str]) -> dict:
        return {
            "status": "partial",
            "imported_rows": 1,
            "returned_rows": 1,
            "fetched_symbols": ["000001"],
            "missing_symbols": ["000002"],
            "skipped_symbols": [],
            "failures": [],
            "diagnostics": [{"code": "date_coverage_shortfall", "symbol": "000002"}],
        }

    summary = module.run_supervised_backfill(
        symbols=["000001", "000002"],
        run_symbol=lambda symbol: None,
        run_batch=batch_runner,
        batch_size=2,
        progress_path=events_path,
        max_consecutive_failures=1,
        sleep_seconds=0,
    )

    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert summary["processed"] == 2
    assert summary["completed"] == 1
    assert summary["failed"] == 1
    assert summary["stopped_reason"] == "max_consecutive_failures"
    assert [event.get("status") for event in events if event.get("symbol") in {"000001", "000002"}] == [
        "completed",
        "failed",
    ]
    assert module.load_completed_symbols(events_path) == {"000001"}


def test_supervised_backfill_batch_partial_keeps_skipped_symbols_completed(tmp_path):
    module = load_backfill_script()
    events_path = tmp_path / "capital-flow-progress.jsonl"

    def batch_runner(symbols: list[str]) -> dict:
        return {
            "status": "partial",
            "imported_rows": 1,
            "returned_rows": 1,
            "fetched_symbols": ["000003"],
            "missing_symbols": ["000004"],
            "skipped_symbols": ["000001", "000002"],
            "failures": [{"symbol": "000004", "code": "network_error", "error": "remote closed"}],
            "diagnostics": [{"code": "capital_flow_crawler_fetch_summary", "skipped_symbols": ["000001", "000002"]}],
        }

    summary = module.run_supervised_backfill(
        symbols=["000001", "000002", "000003", "000004"],
        run_symbol=lambda symbol: None,
        run_batch=batch_runner,
        batch_size=4,
        progress_path=events_path,
        max_consecutive_failures=2,
        sleep_seconds=0,
    )

    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    symbol_statuses = {
        event["symbol"]: event["status"]
        for event in events
        if event.get("symbol") in {"000001", "000002", "000003", "000004"}
    }
    assert summary["processed"] == 4
    assert summary["completed"] == 3
    assert summary["failed"] == 1
    assert symbol_statuses == {
        "000001": "completed",
        "000002": "completed",
        "000003": "completed",
        "000004": "failed",
    }
    assert module.load_completed_symbols(events_path) == {"000001", "000002", "000003"}


def test_supervised_backfill_stops_on_shortfall_diagnostics_without_terminal_failures(tmp_path):
    module = load_backfill_script()
    events_path = tmp_path / "capital-flow-progress.jsonl"

    def partial_without_failures_runner(symbol: str) -> dict:
        return {
            "status": "partial",
            "imported_rows": 0,
            "failures": [],
            "diagnostics": [{"code": "date_coverage_shortfall", "symbol": symbol}],
        }

    summary = module.run_supervised_backfill(
        symbols=["000001", "000002"],
        run_symbol=partial_without_failures_runner,
        progress_path=events_path,
        max_consecutive_failures=1,
        sleep_seconds=0,
    )

    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert summary["processed"] == 1
    assert summary["completed"] == 0
    assert summary["failed"] == 1
    assert summary["stopped_reason"] == "max_consecutive_failures"
    assert events[1]["status"] == "failed"
    assert events[1]["diagnostics"][0]["code"] == "date_coverage_shortfall"
    assert events[-1]["event"] == "stopped"


def test_supervised_backfill_treats_sina_shortfall_as_completed_when_rows_return(tmp_path):
    module = load_backfill_script()
    events_path = tmp_path / "capital-flow-progress.jsonl"

    def sina_shortfall_runner(symbol: str) -> dict:
        return {
            "status": "ok",
            "imported_rows": 0,
            "returned_rows": 2770,
            "fetched_symbols": [symbol],
            "missing_symbols": [],
            "failures": [],
            "diagnostics": [{"code": "date_coverage_shortfall", "provider": "sina", "symbol": symbol}],
        }

    summary = module.run_supervised_backfill(
        symbols=["000001"],
        run_symbol=sina_shortfall_runner,
        progress_path=events_path,
        max_consecutive_failures=1,
        sleep_seconds=0,
    )

    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert summary["completed"] == 1
    assert summary["failed"] == 0
    assert events[1]["status"] == "completed"
    assert events[1]["returned_rows"] == 2770
    assert events[-1]["event"] == "finish"


def test_supervised_backfill_treats_known_source_gap_as_completed(tmp_path):
    module = load_backfill_script()
    events_path = tmp_path / "capital-flow-progress.jsonl"

    def known_gap_runner(symbol: str) -> dict:
        return {
            "status": "partial",
            "imported_rows": 0,
            "returned_rows": 2770,
            "fetched_symbols": [symbol],
            "missing_symbols": [],
            "failures": [],
            "diagnostics": [{"code": "capital_flow_known_source_gap_remaining", "symbol": symbol}],
        }

    summary = module.run_supervised_backfill(
        symbols=["000001"],
        run_symbol=known_gap_runner,
        progress_path=events_path,
        max_consecutive_failures=1,
        sleep_seconds=0,
    )

    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert summary["completed"] == 1
    assert summary["failed"] == 0
    assert events[1]["completion_kind"] == "known_source_gap"
    assert module.load_completed_symbols(events_path) == {"000001"}


def test_supervised_backfill_batch_does_not_complete_symbol_missing_from_result(tmp_path):
    module = load_backfill_script()
    events_path = tmp_path / "capital-flow-progress.jsonl"

    def batch_runner(symbols: list[str]) -> dict:
        return {
            "status": "ok",
            "imported_rows": 1,
            "returned_rows": 1,
            "fetched_symbols": ["000001"],
            "missing_symbols": [],
            "skipped_symbols": [],
            "failures": [],
            "diagnostics": [],
        }

    summary = module.run_supervised_backfill(
        symbols=["000001", "000002"],
        run_symbol=lambda symbol: None,
        run_batch=batch_runner,
        batch_size=2,
        progress_path=events_path,
        max_consecutive_failures=1,
        sleep_seconds=0,
    )

    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    symbol_statuses = {
        event["symbol"]: event["status"]
        for event in events
        if event.get("symbol") in {"000001", "000002"}
    }
    assert summary["completed"] == 1
    assert summary["failed"] == 1
    assert summary["stopped_reason"] == "max_consecutive_failures"
    assert symbol_statuses == {"000001": "completed", "000002": "failed"}
    assert module.load_completed_symbols(events_path) == {"000001"}


def test_load_completed_symbols_resumes_not_needed_symbols(tmp_path):
    module = load_backfill_script()
    progress_path = tmp_path / "capital-flow-progress.jsonl"
    progress_path.write_text(
        "\n".join(
            [
                json.dumps({"status": "completed", "symbol": "000001", "imported_rows": 3}),
                json.dumps(
                    {
                        "status": "completed",
                        "symbol": "000002",
                        "imported_rows": 0,
                        "completion_kind": "already_complete",
                    }
                ),
                json.dumps({"status": "failed", "symbol": "000003", "imported_rows": 0}),
            ]
        ),
        encoding="utf-8",
    )

    assert module.load_completed_symbols(progress_path) == {"000001", "000002"}


def test_load_completed_symbols_does_not_resume_returned_only_symbols(tmp_path):
    module = load_backfill_script()
    progress_path = tmp_path / "capital-flow-progress.jsonl"
    progress_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "status": "completed",
                        "symbol": "000001",
                        "imported_rows": 0,
                        "returned_rows": 2770,
                        "completion_kind": "imported",
                    }
                ),
                json.dumps(
                    {
                        "status": "completed",
                        "symbol": "000002",
                        "imported_rows": 0,
                        "returned_rows": 0,
                        "completion_kind": "imported",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    assert module.load_completed_symbols(progress_path) == set()


def test_run_backfill_from_args_passes_crawler_tuning_options(monkeypatch, tmp_path):
    module = load_backfill_script()
    calls = []

    class FakeCache:
        def __init__(self, root):
            self.root = root

        def read_daily_bars(self):
            return pd.DataFrame()

    class FakeWarehouse:
        def __init__(self, root):
            self.root = root

        def read_daily_bars(self, *args, **kwargs):
            return pd.DataFrame()

    class FakeCrawler:
        def fetch_many_fund_flows(self, symbols, start_date, end_date, **kwargs):
            calls.append((list(symbols), start_date, end_date, kwargs))
            return {
                "rows": [
                    {"symbol": symbols[0], "trade_date": "2026-06-05", "main_net_inflow": 1.0}
                ],
                "failures": [],
                "diagnostics": [],
            }

    def fake_fetch_capital_flow_into_cache(**kwargs):
        result = kwargs["capital_flow_fetcher"](kwargs["symbols"], kwargs["start_date"], kwargs["end_date"])
        assert result["rows"]
        return {
            "status": "ok",
            "imported_rows": 1,
            "returned_rows": 1,
            "fetched_symbols": kwargs["symbols"],
            "missing_symbols": [],
            "skipped_symbols": [],
            "failures": [],
            "diagnostics": [
                {
                    "code": "capital_flow_symbol_summary",
                    "symbol": kwargs["symbols"][0],
                    "imported_rows": 1,
                    "returned_rows": 1,
                }
            ],
        }

    monkeypatch.setattr(module, "LocalCache", FakeCache)
    monkeypatch.setattr(module, "Warehouse", FakeWarehouse)
    monkeypatch.setattr(module, "CapitalFlowCrawler", lambda: FakeCrawler())
    monkeypatch.setattr(module, "fetch_capital_flow_into_cache", fake_fetch_capital_flow_into_cache)

    summary = module.run_backfill_from_args(
        [
            "--cache-dir",
            str(tmp_path),
            "--symbols",
            "000001",
            "--start-date",
            "2026-06-05",
            "--end-date",
            "2026-06-05",
            "--batch-size",
            "1",
            "--sleep-seconds",
            "0",
            "--max-workers",
            "8",
            "--timeout",
            "7",
            "--skip-eastmoney",
            "--no-provider-symbols",
        ]
    )

    assert summary["completed"] == 1
    assert calls == [
        (
            ["000001"],
            "2026-06-05",
            "2026-06-05",
            {"skip_eastmoney": True, "timeout": 7, "max_workers": 8},
        )
    ]


def test_select_missing_symbols_from_warehouse_reads_minimal_ohlc_gaps(tmp_path):
    module = load_backfill_script()
    warehouse = module.Warehouse(tmp_path)
    warehouse.write_daily_bars(
        pd.DataFrame(
            {
                "symbol": ["000001", "000002", "000003", "000004"],
                "trade_date": ["2026-06-05", "2026-06-05", "2026-06-05", "2025-12-31"],
                "open": [10.0, 10.0, float("nan"), 10.0],
                "high": [10.5, 10.5, float("nan"), 10.5],
                "low": [9.8, 9.8, float("nan"), 9.8],
                "close": [10.2, 10.2, float("nan"), 10.2],
                "volume": [1000, 1000, 0, 1000],
                "main_net_inflow": [float("nan"), 1.0, 2.0, float("nan")],
            }
        )
    )

    symbols = module.select_missing_symbols_from_warehouse(
        warehouse,
        completed_symbols={"000001"},
        start_date="2025-01-01",
        end_date="2026-06-08",
        limit=1,
    )

    assert symbols == ["000004"]


def test_run_backfill_from_args_does_not_append_provider_symbols_to_local_gaps(monkeypatch, tmp_path):
    module = load_backfill_script()
    selected_batches = []

    class FakeCache:
        def __init__(self, root):
            self.root = root

        def read_daily_bars(self):
            return pd.DataFrame()

    class FakeWarehouse:
        def __init__(self, root):
            self.root = root

        def read_daily_bars(self, *args, **kwargs):
            return pd.DataFrame()

    monkeypatch.setattr(module, "LocalCache", FakeCache)
    monkeypatch.setattr(module, "Warehouse", FakeWarehouse)
    monkeypatch.setattr(
        module,
        "select_missing_symbols_from_warehouse",
        lambda warehouse, completed, start, end, limit: ["000001"],
    )
    monkeypatch.setattr(module, "load_provider_symbols", lambda: ["000001", "000002"])
    monkeypatch.setattr(module, "CapitalFlowCrawler", lambda: object())

    def fake_fetch_capital_flow_into_cache(**kwargs):
        selected_batches.append(list(kwargs["symbols"]))
        return {
            "status": "ok",
            "imported_rows": 1,
            "returned_rows": 1,
            "fetched_symbols": kwargs["symbols"],
            "missing_symbols": [],
            "skipped_symbols": [],
            "failures": [],
            "diagnostics": [],
        }

    monkeypatch.setattr(module, "fetch_capital_flow_into_cache", fake_fetch_capital_flow_into_cache)

    summary = module.run_backfill_from_args(
        [
            "--cache-dir",
            str(tmp_path),
            "--limit",
            "2",
            "--sleep-seconds",
            "0",
        ]
    )

    assert summary["total_symbols"] == 1
    assert selected_batches == [["000001"]]
