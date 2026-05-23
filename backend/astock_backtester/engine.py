from __future__ import annotations

import pandas as pd

from astock_backtester.conditions import evaluate_condition, evaluate_group
from astock_backtester.models import (
    BacktestMetrics,
    BacktestResult,
    BacktestSettings,
    EquityPoint,
    PreflightIssue,
    StrategyConfig,
    Trade,
)


REQUIRED_BASE_COLUMNS = {
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "is_suspended",
    "listing_days",
    "float_market_cap",
    "main_net_inflow",
}


def _preflight(frame: pd.DataFrame, strategy: StrategyConfig) -> list[PreflightIssue]:
    issues: list[PreflightIssue] = []
    missing = sorted(REQUIRED_BASE_COLUMNS - set(frame.columns))
    for column in missing:
        dataset = "capital_flow" if column == "main_net_inflow" else "daily_bars"
        if column == "float_market_cap":
            dataset = "market_cap"
        issues.append(
            PreflightIssue(
                code=f"missing_{column}",
                dataset=dataset,
                severity="error",
                message=f"Required column is missing: {column}",
            )
        )

    condition_ids = {
        node.condition_id
        for group in strategy.entry_groups
        for node in group.conditions
    } | {node.condition_id for node in strategy.market_filters + strategy.exit_rules}
    if "capital_flow_n_day_sum_at_least" in condition_ids and "main_net_inflow" not in frame.columns:
        issues.append(
            PreflightIssue(
                code="missing_capital_flow",
                dataset="capital_flow",
                severity="error",
                message="Selected strategy requires capital-flow data.",
            )
        )
    return issues


def _empty_result(issues: list[PreflightIssue], initial_cash: float) -> BacktestResult:
    metrics = BacktestMetrics(
        total_return_pct=0.0,
        annualized_return_pct=0.0,
        max_drawdown_pct=0.0,
        win_rate_pct=0.0,
        trade_count=0,
        average_trade_return_pct=0.0,
    )
    return BacktestResult(metrics=metrics, equity_curve=[], trades=[], preflight_issues=issues)


def _passes_market_filters(strategy: StrategyConfig, row: pd.Series, frame: pd.DataFrame) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    for node in strategy.market_filters:
        result = evaluate_condition(node, row, frame)
        if not result.passed:
            return False, reasons
        reasons.append(result.reason)
    return True, reasons


def _passes_entry(strategy: StrategyConfig, row: pd.Series, frame: pd.DataFrame) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    for group in strategy.entry_groups:
        result = evaluate_group(group, row, frame, score_threshold=strategy.score_threshold)
        if not result.passed:
            return False, reasons
        reasons.extend(result.reasons)
    return True, reasons


def _next_trade_date(dates: list[pd.Timestamp], signal_date: pd.Timestamp) -> pd.Timestamp | None:
    for trade_date in dates:
        if trade_date > signal_date:
            return trade_date
    return None


def _build_metrics(
    initial_cash: float,
    final_equity: float,
    trades: list[Trade],
    equity_curve: list[EquityPoint],
) -> BacktestMetrics:
    total_return = (final_equity / initial_cash) - 1
    closed = [trade for trade in trades if trade.pnl_pct is not None]
    wins = [trade for trade in closed if (trade.pnl_pct or 0) > 0]
    avg_trade = sum(trade.pnl_pct or 0 for trade in closed) / len(closed) if closed else 0.0
    max_drawdown = min((point.drawdown_pct for point in equity_curve), default=0.0)
    return BacktestMetrics(
        total_return_pct=total_return,
        annualized_return_pct=total_return,
        max_drawdown_pct=max_drawdown,
        win_rate_pct=len(wins) / len(closed) if closed else 0.0,
        trade_count=len(closed),
        average_trade_return_pct=avg_trade,
    )


def run_backtest(frame: pd.DataFrame, strategy: StrategyConfig, settings: BacktestSettings) -> BacktestResult:
    issues = _preflight(frame, strategy)
    if any(issue.severity == "error" for issue in issues):
        return _empty_result(issues, settings.initial_cash)

    data = frame.sort_values(["trade_date", "symbol"]).reset_index(drop=True)
    data = data[
        (data["trade_date"] >= pd.Timestamp(settings.start_date))
        & (data["trade_date"] <= pd.Timestamp(settings.end_date))
    ].copy()
    trade_dates = list(sorted(data["trade_date"].unique()))
    cash = settings.initial_cash
    trades: list[Trade] = []
    open_positions: list[Trade] = []
    equity_curve: list[EquityPoint] = []
    peak_equity = settings.initial_cash

    for signal_date in trade_dates:
        today = data[data["trade_date"] == signal_date]

        still_open: list[Trade] = []
        for position in open_positions:
            held_days = sum(position.buy_date <= item.date() <= pd.Timestamp(signal_date).date() for item in trade_dates)
            row = today[today["symbol"] == position.symbol]
            if row.empty:
                still_open.append(position)
                continue
            current = row.iloc[0]
            exit_reasons: list[str] = []
            if held_days >= settings.fixed_holding_days:
                exit_reasons.append(f"fixed holding days reached: {settings.fixed_holding_days}")
            if settings.take_profit_pct is not None and (current["high"] / position.buy_price - 1) >= settings.take_profit_pct:
                exit_reasons.append(f"take profit touched: {settings.take_profit_pct:.2%}")
            if settings.stop_loss_pct is not None and (current["low"] / position.buy_price - 1) <= settings.stop_loss_pct:
                exit_reasons.append(f"stop loss touched: {settings.stop_loss_pct:.2%}")
            for node in strategy.exit_rules:
                result = evaluate_condition(node, current, data)
                if result.passed:
                    exit_reasons.append(result.reason)
            if exit_reasons:
                sell_price = float(current["open"]) * (1 - settings.slippage_rate)
                proceeds = sell_price * position.shares * (1 - settings.fee_rate - settings.stamp_tax_rate)
                cash += proceeds
                position.sell_signal_date = pd.Timestamp(signal_date).date()
                position.sell_date = pd.Timestamp(signal_date).date()
                position.sell_price = sell_price
                position.sell_reason = exit_reasons
                position.pnl = proceeds - (position.buy_price * position.shares)
                position.pnl_pct = (sell_price / position.buy_price) - 1
                trades.append(position)
            else:
                still_open.append(position)
        open_positions = still_open

        next_date = _next_trade_date(trade_dates, signal_date)
        if next_date is not None and len(open_positions) < settings.max_positions:
            candidates: list[tuple[pd.Series, list[str]]] = []
            for _, row in today.iterrows():
                if bool(row["is_suspended"]):
                    continue
                if int(row["listing_days"]) < settings.min_listing_days:
                    continue
                market_ok, market_reasons = _passes_market_filters(strategy, row, data)
                if not market_ok:
                    continue
                entry_ok, entry_reasons = _passes_entry(strategy, row, data)
                if entry_ok:
                    candidates.append((row, market_reasons + entry_reasons))

            for row, reasons in candidates[: settings.max_daily_buys]:
                if len(open_positions) >= settings.max_positions:
                    break
                buy_row = data[(data["trade_date"] == next_date) & (data["symbol"] == row["symbol"])]
                if buy_row.empty:
                    continue
                buy = buy_row.iloc[0]
                cash_per_position = cash / max(1, settings.max_positions - len(open_positions))
                buy_price = float(buy["open"]) * (1 + settings.slippage_rate)
                shares = int(cash_per_position // buy_price)
                if shares <= 0:
                    continue
                cost = shares * buy_price * (1 + settings.fee_rate)
                cash -= cost
                open_positions.append(
                    Trade(
                        symbol=str(row["symbol"]),
                        buy_signal_date=pd.Timestamp(signal_date).date(),
                        buy_date=pd.Timestamp(next_date).date(),
                        buy_price=float(buy["open"]),
                        shares=shares,
                        buy_reason=reasons,
                    )
                )

        market_value = 0.0
        for position in open_positions:
            row = today[today["symbol"] == position.symbol]
            if not row.empty:
                market_value += float(row.iloc[0]["close"]) * position.shares
        equity = cash + market_value
        peak_equity = max(peak_equity, equity)
        drawdown = (equity / peak_equity) - 1 if peak_equity else 0.0
        equity_curve.append(
            EquityPoint(
                trade_date=pd.Timestamp(signal_date).date(),
                equity=equity,
                cash=cash,
                market_value=market_value,
                drawdown_pct=drawdown,
            )
        )

    final_equity = equity_curve[-1].equity if equity_curve else settings.initial_cash
    return BacktestResult(
        metrics=_build_metrics(settings.initial_cash, final_equity, trades, equity_curve),
        equity_curve=equity_curve,
        trades=trades,
        preflight_issues=issues,
    )
