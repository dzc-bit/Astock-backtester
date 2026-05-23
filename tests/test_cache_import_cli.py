from astock_backtester.data.cache import LocalCache
from astock_backtester.data.importer import normalize_daily_bars
from astock_backtester.sample_data import sample_daily_bars
from astock_backtester.cli import handle_command


def test_normalize_daily_bars_accepts_required_columns():
    raw = sample_daily_bars().rename(columns={"trade_date": "date"})

    result = normalize_daily_bars(raw)

    assert result["trade_date"].dtype == "datetime64[ns]"
    assert result.columns.tolist()[:6] == ["symbol", "trade_date", "open", "high", "low", "close"]


def test_local_cache_round_trips_daily_bars(tmp_path):
    cache = LocalCache(tmp_path)
    bars = sample_daily_bars()

    cache.write_daily_bars(bars)
    loaded = cache.read_daily_bars()

    assert len(loaded) == len(bars)
    assert set(loaded["symbol"]) == {"AAA", "BBB"}


def test_local_cache_reports_dataset_coverage(tmp_path):
    cache = LocalCache(tmp_path)
    cache.write_daily_bars(sample_daily_bars())

    coverage = cache.coverage()

    daily = next(item for item in coverage if item.dataset == "daily_bars")
    assert daily.symbols == 2
    assert str(daily.start_date) == "2024-01-02"


def test_cli_coverage_command_returns_daily_bars_dataset(tmp_path):
    payload = {"command": "coverage", "cache_dir": str(tmp_path)}
    response = handle_command(payload)

    assert response["ok"] is True
    assert response["coverage"][0]["dataset"] == "daily_bars"


def test_cli_demo_backtest_returns_metrics():
    response = handle_command({"command": "demo_backtest"})

    assert response["ok"] is True
    assert response["result"]["metrics"]["trade_count"] >= 1
    assert response["result"]["trades"]


def test_cli_rejects_unknown_command():
    response = handle_command({"command": "nope"})

    assert response["ok"] is False
    assert response["error"]["code"] == "unknown_command"
