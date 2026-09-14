from __future__ import annotations

from astock_backtester.ai.overfit import assess_overfit


def test_few_trades_is_flagged():
    result = assess_overfit({"trade_count": 3, "total_return_pct": 0.2, "win_rate_pct": 1.0, "max_drawdown_pct": -0.01})
    codes = [finding["code"] for finding in result["findings"]]
    assert "few_trades" in codes
    assert result["level"] in ("warning", "critical")


def test_very_few_trades_is_critical():
    result = assess_overfit({"trade_count": 1, "total_return_pct": 0.05, "win_rate_pct": 1.0, "max_drawdown_pct": -0.01})
    assert result["level"] == "critical"


def test_perfect_win_rate_and_high_return_few_trades_flagged():
    metrics = {"trade_count": 8, "total_return_pct": 1.5, "win_rate_pct": 1.0, "max_drawdown_pct": -0.02}
    result = assess_overfit(metrics)
    codes = {finding["code"] for finding in result["findings"]}
    assert "perfect_win_rate" in codes
    assert "high_return_few_trades" in codes


def test_healthy_metrics_pass_clean():
    metrics = {"trade_count": 120, "total_return_pct": 0.18, "win_rate_pct": 0.54, "max_drawdown_pct": -0.12}
    result = assess_overfit(metrics)
    assert result["level"] == "none"
    assert result["findings"] == []


def test_grid_best_outlier_flagged():
    combos = [
        {"metrics": {"total_return_pct": value}}
        for value in (0.01, 0.02, 0.02, 0.03, 0.02, 0.01)
    ]
    combos.append({"metrics": {"total_return_pct": 0.30}})
    result = assess_overfit({"trade_count": 50}, combos=combos)
    codes = {finding["code"] for finding in result["findings"]}
    assert "grid_best_outlier" in codes


def test_grid_only_best_positive_flagged():
    combos = [{"metrics": {"total_return_pct": value}} for value in (-0.05, -0.02, -0.01, -0.03, 0.0, -0.04)]
    combos.append({"metrics": {"total_return_pct": 0.12}})
    result = assess_overfit({"trade_count": 50}, combos=combos)
    codes = {finding["code"] for finding in result["findings"]}
    assert "grid_only_best_positive" in codes


def test_grid_without_dispersion_passes():
    combos = [{"metrics": {"total_return_pct": value}} for value in (0.10, 0.11, 0.12, 0.11, 0.10, 0.12)]
    result = assess_overfit({"trade_count": 80}, combos=combos)
    assert result["level"] == "none"
