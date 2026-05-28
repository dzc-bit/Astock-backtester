from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


def load_import_script():
    script_path = Path(__file__).parents[1] / "scripts" / "run-full-market-import.py"
    spec = importlib.util.spec_from_file_location("run_full_market_import", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class BrokenProvider:
    def list_symbols(self) -> list[str]:
        raise RuntimeError("remote symbol list failed")


class EmptyDailyProvider:
    def fetch_daily_bars(self, symbol, start_date, end_date):
        return pd.DataFrame()


def test_load_symbols_falls_back_to_adata_local_cache(tmp_path, monkeypatch):
    module = load_import_script()
    monkeypatch.setattr(module, "read_adata_local_symbols", lambda: ["1", "SZ000002", "600000.SH"])

    symbols, source = module.load_symbols(tmp_path, BrokenProvider())

    assert symbols == ["000001", "000002", "600000"]
    assert source == "adata-local"
    assert (tmp_path / "symbols.csv").exists()


def test_load_symbols_uses_existing_cache_when_provider_is_broken(tmp_path):
    module = load_import_script()
    (tmp_path / "symbols.csv").write_text("symbol\n000001\n000002\n", encoding="utf-8")

    symbols, source = module.load_symbols(tmp_path, BrokenProvider())

    assert symbols == ["000001", "000002"]
    assert source == "cache"


def test_fetch_daily_bars_falls_back_to_http_source(monkeypatch):
    module = load_import_script()

    class FakeAdapter:
        def fetch_daily_bars(self, symbols, start_date, end_date):
            return pd.DataFrame(
                {
                    "symbol": symbols,
                    "trade_date": [start_date],
                    "open": [1.0],
                    "high": [1.0],
                    "low": [1.0],
                    "close": [1.0],
                    "volume": [1],
                }
            )

    class FakeAdapterFactory:
        @classmethod
        def from_http_sources(cls):
            return FakeAdapter()

    monkeypatch.setattr(module, "AStockDataAdapter", FakeAdapterFactory)

    frame, source = module.fetch_daily_bars("000001", "2024-01-02", "2024-01-02", EmptyDailyProvider())

    assert source == "http"
    assert frame.loc[0, "symbol"] == "000001"


def test_resume_only_counts_completed_symbols_with_rows(tmp_path):
    module = load_import_script()
    progress_path = tmp_path / "import-progress.jsonl"
    progress_path.write_text(
        "\n".join(
            [
                '{"status":"completed","symbol":"000001","rows":0}',
                '{"status":"completed","symbol":"000002","rows":12}',
                '{"status":"failed","symbol":"000003","rows":12}',
            ]
        ),
        encoding="utf-8",
    )

    completed = module.load_completed_symbols(progress_path)

    assert completed == {"000002"}
