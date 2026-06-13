from __future__ import annotations

import hashlib
import math
from typing import Callable

import pandas as pd

from astock_backtester.conditions import evaluate_condition, evaluate_group
from astock_backtester.models import (
    BacktestMetrics,
    BacktestResult,
    BacktestSettings,
    DailyStrategyMatches,
    EquityPoint,
    PreflightIssue,
    StrategyConfig,
    StrategyMatch,
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

BOARD_LOT_SIZE = 100

CAPITAL_FLOW_CONDITIONS = {
    "capital_flow_n_day_sum_at_least",
    "capital_flow_today_at_least",
    "capital_flow_n_day_positive_count_at_least",
}


def _stock_pool_mask(data: pd.DataFrame, settings: BacktestSettings) -> pd.Series:
    symbols = data["symbol"].astype(str)
    if settings.stock_pool == "all":
        return pd.Series(True, index=data.index)
    if settings.stock_pool == "custom":
        selected = {str(symbol).strip() for symbol in settings.custom_symbols if str(symbol).strip()}
        return symbols.isin(selected)
    if settings.stock_pool == "main_board":
        return symbols.str.startswith(("000", "001", "002", "003", "600", "601", "603", "605"))
    if settings.stock_pool == "gem":
        return symbols.str.startswith("300")
    if settings.stock_pool == "star":
        return symbols.str.startswith("688")
    if settings.stock_pool == "beijing":
        return symbols.str.startswith(("43", "83", "87", "88", "92"))
    return pd.Series(True, index=data.index)


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
    requires_capital_flow = bool(condition_ids & CAPITAL_FLOW_CONDITIONS)
    if requires_capital_flow and "main_net_inflow" not in frame.columns:
        issues.append(
            PreflightIssue(
                code="missing_capital_flow",
                dataset="capital_flow",
                severity="error",
                message="Selected strategy requires capital-flow data.",
            )
        )
    if requires_capital_flow and "main_net_inflow" in frame.columns:
        if frame["main_net_inflow"].isna().all():
            issues.append(
                PreflightIssue(
                    code="empty_capital_flow",
                    dataset="capital_flow",
                    severity="error",
                    message="Selected strategy requires capital-flow data, but all cached values are missing.",
                )
            )
    if "market_cap_between" in condition_ids and "float_market_cap" in frame.columns:
        if frame["float_market_cap"].isna().all():
            issues.append(
                PreflightIssue(
                    code="empty_market_cap",
                    dataset="market_cap",
                    severity="error",
                    message="Selected strategy requires market-cap data, but all cached values are missing.",
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
        average_position_pct=0.0,
        max_position_pct=0.0,
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


def _filter_mask_for_node(node, data: pd.DataFrame) -> pd.Series:
    mask = pd.Series(True, index=data.index)
    if not node.enabled:
        return mask
    condition_id = node.condition_id
    params = node.params
    if condition_id == "market_cap_between":
        return data["float_market_cap"].between(float(params["min"]), float(params["max"]), inclusive="both")
    if condition_id == "capital_flow_n_day_sum_at_least":
        window = int(params["window"])
        column = f"main_net_inflow_sum_{window}d"
        if column in data:
            return data[column] >= float(params["min"])
        return mask
    if condition_id == "capital_flow_today_at_least":
        return data["main_net_inflow"] >= float(params["min"])
    if condition_id == "capital_flow_n_day_positive_count_at_least":
        window = int(params["window"])
        column = f"main_net_inflow_positive_count_{window}d"
        if column in data:
            return data[column] >= int(params["min_count"])
        return mask
    if condition_id == "market_rising_ratio_at_least":
        return data["market_rising_ratio"] >= float(params["min_ratio"])
    if condition_id == "close_above_ma":
        window = int(params["window"])
        return data["close"] > data[f"ma_{window}"]
    if condition_id == "close_below_ma":
        window = int(params["window"])
        return data["close"] < data[f"ma_{window}"]
    if condition_id == "turnover_between":
        return data["turnover_rate"].between(float(params["min"]), float(params["max"]), inclusive="both")
    if condition_id == "past_return_at_most":
        window = int(params["window"])
        return data[f"return_{window}d"] <= float(params["max"])
    if condition_id == "past_return_between":
        window = int(params["window"])
        return data[f"return_{window}d"].between(float(params["min"]), float(params["max"]), inclusive="both")
    if condition_id == "volume_ratio_between":
        window = int(params["window"])
        return data[f"volume_ratio_{window}d"].between(float(params["min"]), float(params["max"]), inclusive="both")
    if condition_id == "macd_histogram_at_least":
        return data["macd_hist"] >= float(params["min"])
    if condition_id == "breakout_above_n_day_high":
        window = int(params["window"])
        column = f"prior_high_{window}d"
        if column in data:
            return data["close"] > data[column]
        return mask
    if condition_id == "breakdown_below_n_day_low":
        window = int(params["window"])
        column = f"prior_low_{window}d"
        if column in data:
            return data["close"] < data[column]
        return mask
    return mask


def _candidate_prefilter_mask(strategy: StrategyConfig, data: pd.DataFrame) -> pd.Series:
    mask = pd.Series(True, index=data.index)
    for node in strategy.market_filters:
        mask &= _filter_mask_for_node(node, data)
    for group in strategy.entry_groups:
        operator = getattr(group.operator, "value", group.operator)
        if operator == "score":
            continue
        group_masks = [_filter_mask_for_node(node, data) for node in group.conditions]
        if not group_masks:
            continue
        if operator == "or":
            group_mask = group_masks[0].copy()
            for node_mask in group_masks[1:]:
                group_mask |= node_mask
        else:
            group_mask = group_masks[0].copy()
            for node_mask in group_masks[1:]:
                group_mask &= node_mask
        mask &= group_mask
    return mask.fillna(False)


def _next_trade_date(dates: list[pd.Timestamp], signal_date: pd.Timestamp) -> pd.Timestamp | None:
    for trade_date in dates:
        if trade_date > signal_date:
            return trade_date
    return None


def _numeric_value(row: pd.Series, column: str) -> float:
    if column not in row.index:
        return 0.0
    value = pd.to_numeric(row[column], errors="coerce")
    if pd.isna(value):
        return 0.0
    return float(value)


def _max_numeric_prefix(row: pd.Series, prefix: str) -> float:
    values = [
        _numeric_value(row, column)
        for column in row.index
        if isinstance(column, str) and column.startswith(prefix)
    ]
    return max(values, default=0.0)


def _compressed_positive(value: float, scale: float) -> float:
    if value <= 0 or scale <= 0:
        return 0.0
    return math.log1p(value / scale)


def _stable_symbol_tiebreaker(row: pd.Series) -> float:
    key = f"{row.get('trade_date', '')}-{row.get('symbol', '')}".encode("utf-8")
    digest = hashlib.blake2b(key, digest_size=8).digest()
    return int.from_bytes(digest, "big") / float(2**64 - 1)


def _optional_string(row: pd.Series, column: str) -> str | None:
    if column not in row.index:
        return None
    value = row[column]
    if pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _optional_float(row: pd.Series, column: str) -> float | None:
    if column not in row.index:
        return None
    value = pd.to_numeric(row[column], errors="coerce")
    if pd.isna(value):
        return None
    return float(value)


def _stock_limit_pct(row: pd.Series) -> float | None:
    pre_close = _optional_float(row, "pre_close")
    if pre_close is None or pre_close <= 0:
        return None
    symbol = str(row.get("symbol", ""))
    if bool(row.get("is_st", False)):
        return 0.05
    if symbol.startswith(("300", "688")):
        return 0.20
    return 0.10


def _is_open_near_limit(row: pd.Series, direction: str) -> bool:
    limit_pct = _stock_limit_pct(row)
    if limit_pct is None:
        return False
    pre_close = _optional_float(row, "pre_close")
    open_price = _optional_float(row, "open")
    if pre_close is None or open_price is None:
        return False
    tolerance = 1e-4
    if direction == "up":
        return open_price >= pre_close * (1 + limit_pct) * (1 - tolerance)
    return open_price <= pre_close * (1 - limit_pct) * (1 + tolerance)


def _buy_execution_price(row: pd.Series, settings: BacktestSettings) -> float:
    price = float(row["open"])
    if settings.conservative_execution:
        return price * (1 + settings.slippage_rate)
    return price


def _sell_execution_price(price: float, settings: BacktestSettings) -> float:
    if settings.conservative_execution:
        return price * (1 - settings.slippage_rate)
    return price


def _blocked_trade(
    row: pd.Series,
    signal_date: pd.Timestamp,
    trade_date: pd.Timestamp,
    planned_amount: float,
    current_equity: float,
    reasons: list[str],
    blocked_reason: str,
) -> Trade:
    return Trade(
        symbol=str(row["symbol"]),
        buy_signal_date=pd.Timestamp(signal_date).date(),
        buy_date=pd.Timestamp(trade_date).date(),
        buy_price=float(row["open"]),
        shares=0,
        planned_amount=planned_amount,
        buy_amount=0.0,
        target_position_pct=planned_amount / current_equity if current_equity else 0.0,
        actual_position_pct=0.0,
        buy_reason=reasons,
        blocked_reason=blocked_reason,
    )


def _candidate_rank(row: pd.Series) -> tuple[float, float, float, float, float, float, float]:
    flow_score = _compressed_positive(_numeric_value(row, "main_net_inflow"), 1_000_000.0)
    liquidity_score = _compressed_positive(_numeric_value(row, "volume"), 10_000.0)
    market_cap_score = _compressed_positive(_numeric_value(row, "float_market_cap"), 1_000_000_000.0)
    turnover_score = _numeric_value(row, "turnover_rate")
    volume_ratio_score = min(_max_numeric_prefix(row, "volume_ratio_"), 3.0)
    return_score = min(max(_max_numeric_prefix(row, "return_"), -0.3), 0.3)
    return (
        flow_score,
        liquidity_score,
        market_cap_score,
        turnover_score,
        volume_ratio_score,
        return_score,
        _stable_symbol_tiebreaker(row),
    )


def _candidate_rank_score(row: pd.Series) -> float:
    rank = _candidate_rank(row)
    return float(sum(rank[:-1]))


def _build_daily_strategy_matches(
    signal_date: pd.Timestamp,
    candidates: list[tuple[pd.Series, list[str]]],
) -> DailyStrategyMatches:
    signal_day = pd.Timestamp(signal_date).date()
    matches = [
        StrategyMatch(
            symbol=str(row["symbol"]),
            signal_date=signal_day,
            trade_date=pd.Timestamp(row["trade_date"]).date(),
            name=_optional_string(row, "name"),
            close=float(row["close"]),
            change_pct=_optional_float(row, "change_pct"),
            reasons=list(reasons),
            rank_score=_candidate_rank_score(row),
        )
        for row, reasons in candidates
    ]
    return DailyStrategyMatches(signal_date=signal_day, trade_date=signal_day, matches=matches)


def _scan_entry_candidates(
    today: pd.DataFrame,
    data: pd.DataFrame,
    strategy: StrategyConfig,
    settings: BacktestSettings,
) -> list[tuple[pd.Series, list[str]]]:
    candidates: list[tuple[pd.Series, list[str]]] = []
    candidate_rows = today[today["_passes_entry_prefilter"]]
    for _, row in candidate_rows.iterrows():
        if bool(row["is_suspended"]):
            continue
        if settings.exclude_st and "is_st" in row.index and bool(row["is_st"]):
            continue
        if int(row["listing_days"]) < settings.min_listing_days:
            continue
        market_ok, market_reasons = _passes_market_filters(strategy, row, data)
        if not market_ok:
            continue
        entry_ok, entry_reasons = _passes_entry(strategy, row, data)
        if entry_ok:
            candidates.append((row, market_reasons + entry_reasons))

    candidates.sort(key=lambda candidate: _candidate_rank(candidate[0]), reverse=True)
    return candidates


def _build_metrics(
    initial_cash: float,
    final_equity: float,
    trades: list[Trade],
    equity_curve: list[EquityPoint],
) -> BacktestMetrics:
    total_return = (final_equity / initial_cash) - 1
    annualized_return = 0.0
    if len(equity_curve) >= 2:
        first_date = equity_curve[0].trade_date
        last_date = equity_curve[-1].trade_date
        days = (last_date - first_date).days
        if days > 0:
            annualized_return = (final_equity / initial_cash) ** (365 / days) - 1
    closed = [trade for trade in trades if trade.pnl_pct is not None]
    wins = [trade for trade in closed if (trade.pnl_pct or 0) > 0]
    avg_trade = sum(trade.pnl_pct or 0 for trade in closed) / len(closed) if closed else 0.0
    position_pcts = [trade.actual_position_pct for trade in closed]
    max_drawdown = min((point.drawdown_pct for point in equity_curve), default=0.0)
    return BacktestMetrics(
        total_return_pct=total_return,
        annualized_return_pct=annualized_return,
        max_drawdown_pct=max_drawdown,
        win_rate_pct=len(wins) / len(closed) if closed else 0.0,
        trade_count=len(closed),
        average_trade_return_pct=avg_trade,
        average_position_pct=sum(position_pcts) / len(position_pcts) if position_pcts else 0.0,
        max_position_pct=max(position_pcts, default=0.0),
    )


def _mark_to_market(
    open_positions: list[Trade],
    rows_by_symbol: dict[str, object],
    last_close_by_symbol: dict[str, float] | None = None,
) -> float:
    market_value = 0.0
    for position in open_positions:
        row = rows_by_symbol.get(position.symbol)
        if row is not None:
            market_value += float(row.close) * position.shares
            continue
        if last_close_by_symbol is not None and position.symbol in last_close_by_symbol:
            market_value += last_close_by_symbol[position.symbol] * position.shares
    return market_value


def _completed_holding_days(buy_date, signal_date: pd.Timestamp, trade_dates: list[pd.Timestamp]) -> int:
    buy_day = pd.Timestamp(buy_date).date()
    signal_day = pd.Timestamp(signal_date).date()
    return sum(buy_day < item.date() <= signal_day for item in trade_dates)


def _exit_signal(
    position: Trade,
    current: pd.Series,
    settings: BacktestSettings,
) -> tuple[list[str], float | None]:
    if settings.stop_loss_pct is not None and (current["low"] / position.buy_price - 1) <= settings.stop_loss_pct:
        return [f"止损触发：{settings.stop_loss_pct:.2%}"], position.buy_price * (1 + settings.stop_loss_pct)
    if settings.take_profit_pct is not None and (current["high"] / position.buy_price - 1) >= settings.take_profit_pct:
        return [f"止盈触发：{settings.take_profit_pct:.2%}"], position.buy_price * (1 + settings.take_profit_pct)
    return [], None


def _planned_entry_amount(
    settings: BacktestSettings,
    cash: float,
    open_positions: list[Trade],
    current_equity: float,
) -> float:
    if settings.position_sizing_mode == "fixed_ratio":
        return min(cash, current_equity * settings.position_size_pct)
    remaining_slots = max(1, settings.max_positions - len(open_positions))
    return cash / remaining_slots


def run_backtest(
    frame: pd.DataFrame,
    strategy: StrategyConfig,
    settings: BacktestSettings,
    on_trade_closed: Callable[[Trade], None] | None = None,
    on_event: Callable[[dict], None] | None = None,
) -> BacktestResult:
    issues = _preflight(frame, strategy)
    if any(issue.severity == "error" for issue in issues):
        return _empty_result(issues, settings.initial_cash)

    data = frame.sort_values(["trade_date", "symbol"]).reset_index(drop=True)
    data = data[
        (data["trade_date"] >= pd.Timestamp(settings.start_date))
        & (data["trade_date"] <= pd.Timestamp(settings.end_date))
    ].copy()
    data = data.loc[_stock_pool_mask(data, settings)].copy()
    data["_passes_entry_prefilter"] = _candidate_prefilter_mask(strategy, data)
    trade_dates = list(sorted(data["trade_date"].unique()))
    rows_by_date = {trade_date: group for trade_date, group in data.groupby("trade_date", sort=False)}
    rows_by_date_symbol = {
        trade_date: {str(row.symbol): row for row in group.itertuples(index=False)}
        for trade_date, group in rows_by_date.items()
    }
    cash = settings.initial_cash
    trades: list[Trade] = []
    open_positions: list[Trade] = []
    equity_curve: list[EquityPoint] = []
    latest_strategy_matches: DailyStrategyMatches | None = None
    peak_equity = settings.initial_cash
    last_close_by_symbol: dict[str, float] = {}

    total_trade_days = len(trade_dates)
    for day_index, signal_date in enumerate(trade_dates, start=1):
        today = rows_by_date.get(signal_date, data.iloc[0:0])
        today_by_symbol = rows_by_date_symbol.get(signal_date, {})
        for row in today.itertuples(index=False):
            last_close_by_symbol[str(row.symbol)] = float(row.close)
        if on_event is not None:
            on_event(
                {
                    "type": "progress",
                    "trade_date": pd.Timestamp(signal_date).date(),
                    "scanned_days": day_index,
                    "total_days": total_trade_days,
                    "open_positions": len(open_positions),
                    "closed_trades": len(trades),
                    "candidates": 0,
                    "message": f"扫描 {pd.Timestamp(signal_date).date()}：持仓 {len(open_positions)} 只，已平仓 {len(trades)} 笔",
                }
            )

        still_open: list[Trade] = []
        for position in open_positions:
            if pd.Timestamp(signal_date).date() <= position.buy_date:
                still_open.append(position)
                continue
            held_days = _completed_holding_days(position.buy_date, signal_date, trade_dates)
            current_tuple = today_by_symbol.get(position.symbol)
            if current_tuple is None:
                still_open.append(position)
                continue
            current = pd.Series(current_tuple._asdict())
            exit_reasons: list[str] = []
            trigger_price: float | None = None
            if held_days >= settings.fixed_holding_days:
                exit_reasons.append(f"fixed holding days reached: {settings.fixed_holding_days}")
            else:
                trigger_reasons, trigger_price = _exit_signal(position, current, settings)
                exit_reasons.extend(trigger_reasons)
                if not trigger_reasons:
                    for node in strategy.exit_rules:
                        result = evaluate_condition(node, current, data)
                        if result.passed:
                            exit_reasons.append(result.reason)
            if exit_reasons:
                if settings.limit_down_blocks_sell and _is_open_near_limit(current, "down"):
                    position.blocked_reason = f"卖出日开盘接近跌停，暂不卖出：{position.symbol}"
                    still_open.append(position)
                    if on_event is not None:
                        on_event({"type": "trade_blocked", "trade": position})
                    continue
                raw_sell_price = trigger_price if trigger_price is not None else float(current["open"])
                sell_price = _sell_execution_price(raw_sell_price, settings)
                proceeds = sell_price * position.shares * (1 - settings.fee_rate - settings.stamp_tax_rate)
                cash += proceeds
                position.sell_signal_date = pd.Timestamp(signal_date).date()
                position.sell_date = pd.Timestamp(signal_date).date()
                position.sell_price = sell_price
                position.sell_amount = proceeds
                position.sell_reason = exit_reasons
                position.pnl = proceeds - position.buy_amount
                position.pnl_pct = (proceeds / position.buy_amount - 1) if position.buy_amount else None
                trades.append(position)
                if on_trade_closed is not None:
                    on_trade_closed(position)
                if on_event is not None:
                    on_event({"type": "trade_closed", "trade": position})
            else:
                still_open.append(position)
        open_positions = still_open

        next_date = _next_trade_date(trade_dates, signal_date)
        candidates = _scan_entry_candidates(today, data, strategy, settings)
        candidate_count = len(candidates)
        latest_strategy_matches = _build_daily_strategy_matches(signal_date, candidates)
        if on_event is not None:
            on_event(
                {
                    "type": "progress",
                    "trade_date": pd.Timestamp(signal_date).date(),
                    "scanned_days": day_index,
                    "total_days": total_trade_days,
                    "open_positions": len(open_positions),
                    "closed_trades": len(trades),
                    "candidates": candidate_count,
                    "message": (
                        f"扫描 {pd.Timestamp(signal_date).date()}：候选 {candidate_count} 只，"
                        f"持仓 {len(open_positions)} 只"
                    ),
                }
            )
        market_value = _mark_to_market(open_positions, today_by_symbol, last_close_by_symbol)
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

        if next_date is not None and len(open_positions) < settings.max_positions:
            current_market_value = _mark_to_market(open_positions, today_by_symbol, last_close_by_symbol)
            current_equity = cash + current_market_value
            for row, reasons in candidates[: settings.max_daily_buys]:
                if len(open_positions) >= settings.max_positions:
                    break
                buy_tuple = rows_by_date_symbol.get(next_date, {}).get(str(row["symbol"]))
                if buy_tuple is None:
                    continue
                buy = pd.Series(buy_tuple._asdict())
                planned_amount = _planned_entry_amount(settings, cash, open_positions, current_equity)
                if settings.limit_up_blocks_buy and _is_open_near_limit(buy, "up"):
                    blocked_reason = f"次日开盘接近涨停，未买入：{buy['symbol']}"
                    blocked_trade = _blocked_trade(
                        buy,
                        signal_date,
                        next_date,
                        planned_amount,
                        current_equity,
                        reasons,
                        blocked_reason,
                    )
                    if on_event is not None:
                        on_event({"type": "trade_blocked", "trade": blocked_trade})
                    continue
                executed_buy_price = _buy_execution_price(buy, settings)
                cost_per_share = executed_buy_price * (1 + settings.fee_rate)
                shares = int(planned_amount // cost_per_share)
                shares = (shares // BOARD_LOT_SIZE) * BOARD_LOT_SIZE
                if shares <= 0:
                    continue
                buy_amount = shares * cost_per_share
                cash -= buy_amount
                opened_trade = Trade(
                    symbol=str(row["symbol"]),
                    buy_signal_date=pd.Timestamp(signal_date).date(),
                    buy_date=pd.Timestamp(next_date).date(),
                    buy_price=executed_buy_price,
                    shares=shares,
                    planned_amount=planned_amount,
                    buy_amount=buy_amount,
                    target_position_pct=planned_amount / current_equity if current_equity else 0.0,
                    actual_position_pct=buy_amount / current_equity if current_equity else 0.0,
                    buy_reason=reasons,
                )
                open_positions.append(opened_trade)
                if on_event is not None:
                    on_event({"type": "trade_opened", "trade": opened_trade})

    final_equity = equity_curve[-1].equity if equity_curve else settings.initial_cash
    result_trades = [*trades, *open_positions]
    return BacktestResult(
        metrics=_build_metrics(settings.initial_cash, final_equity, trades, equity_curve),
        equity_curve=equity_curve,
        trades=result_trades,
        preflight_issues=issues,
        latest_strategy_matches=latest_strategy_matches,
    )
