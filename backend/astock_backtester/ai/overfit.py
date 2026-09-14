"""Deterministic backtest overfit checks (no model needed).

``assess_overfit`` inspects a finished backtest's metrics plus — when a
parameter grid was swept — the dispersion across combinations, and returns
machine-readable findings.  The frontend shows them next to the result and
feeds them into the AI one-shot commentary as context; the check itself must
stay cheap, explainable and runnable with AI unconfigured.
"""

from __future__ import annotations

from typing import Any

MIN_RELIABLE_TRADES = 10
# 指标口径：BacktestMetrics 里的 *_pct 是小数比例（0.05 = +5%）。
SUSPICIOUS_WIN_RATE = 0.999
SUSPICIOUS_RETURN = 1.0
LOW_TRADE_HIGH_RETURN_TRADES = 30
SMOOTH_DRAWDOWN = 0.005
SMOOTH_RETURN = 0.5
PARAM_DISPERSION_RATIO = 3.0


def _finding(level: str, code: str, message: str) -> dict[str, str]:
    return {"level": level, "code": code, "message": message}


def _param_dispersion_findings(combos: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Compare the best combination against the grid median: a best that is
    many times better than its neighbours is a classic overfit signature."""
    returns: list[float] = []
    for combo in combos:
        metrics = combo.get("metrics") or {}
        value = metrics.get("total_return_pct")
        if isinstance(value, (int, float)):
            returns.append(float(value))
    if len(returns) < 5:
        return []
    ordered = sorted(returns)
    median = ordered[len(ordered) // 2]
    best = ordered[-1]
    if median <= 0:
        if best > 0:
            return [
                _finding(
                    "warning",
                    "grid_only_best_positive",
                    f"参数网格 {len(returns)} 组里只有最优组收益为正（{best:+.1%}），其余均不赚钱，参数大概率过拟合。",
                )
            ]
        return []
    if best >= median * PARAM_DISPERSION_RATIO and best > 0:
        return [
            _finding(
                "warning",
                "grid_best_outlier",
                f"最优组合收益 {best:+.1%} 是网格中位数（{median:+.1%}）的 {best / median:.1f} 倍，业绩依赖特定参数，稳健性存疑。",
            )
        ]
    return []


def assess_overfit(metrics: dict[str, Any], *, combos: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    trade_count = metrics.get("trade_count")
    total_return = metrics.get("total_return_pct")
    win_rate = metrics.get("win_rate_pct")
    max_drawdown = metrics.get("max_drawdown_pct")

    if isinstance(trade_count, (int, float)) and trade_count < MIN_RELIABLE_TRADES:
        findings.append(
            _finding(
                "warning" if trade_count >= 5 else "critical",
                "few_trades",
                f"仅 {int(trade_count)} 笔交易，样本太少，收益/胜率统计意义不足；建议拉长回测区间或放宽条件。",
            )
        )
    if (
        isinstance(win_rate, (int, float))
        and win_rate >= SUSPICIOUS_WIN_RATE
        and isinstance(trade_count, (int, float))
        and trade_count >= 5
    ):
        findings.append(
            _finding(
                "warning",
                "perfect_win_rate",
                "胜率接近 100%：先检查是否用了未来函数、止损从未被触发，或数据本身存在缺口。",
            )
        )
    if (
        isinstance(total_return, (int, float))
        and total_return >= SUSPICIOUS_RETURN
        and isinstance(trade_count, (int, float))
        and trade_count < LOW_TRADE_HIGH_RETURN_TRADES
    ):
        findings.append(
            _finding(
                "warning",
                "high_return_few_trades",
                f"总收益 {total_return:+.1%} 却只来自 {int(trade_count)} 笔交易，收益高度依赖个别行情，实盘外推风险大。",
            )
        )
    if (
        isinstance(max_drawdown, (int, float))
        and abs(max_drawdown) <= SMOOTH_DRAWDOWN
        and isinstance(total_return, (int, float))
        and total_return >= SMOOTH_RETURN
    ):
        findings.append(
            _finding(
                "info",
                "suspiciously_smooth",
                "收益很高而回撤极浅：确认是否真实逐日撮合，警惕成交价按理想价成交的乐观假设。",
            )
        )
    if combos:
        findings.extend(_param_dispersion_findings(combos))

    level = "none"
    if any(item["level"] == "critical" for item in findings):
        level = "critical"
    elif any(item["level"] == "warning" for item in findings):
        level = "warning"
    elif findings:
        level = "info"
    return {"level": level, "findings": findings}
