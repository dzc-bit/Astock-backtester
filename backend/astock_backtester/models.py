from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ConditionOperator(str, Enum):
    AND = "and"
    OR = "or"
    SCORE = "score"


class ConditionNode(BaseModel):
    id: str
    condition_id: str
    enabled: bool = True
    params: dict[str, Any] = Field(default_factory=dict)
    weight: float | None = None
    data_lag_days: int = 0

    @field_validator("data_lag_days")
    @classmethod
    def data_lag_days_cannot_be_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("data_lag_days must be >= 0")
        return value


class ConditionGroup(BaseModel):
    id: str
    operator: ConditionOperator
    conditions: list[ConditionNode]

    @model_validator(mode="after")
    def require_conditions(self) -> ConditionGroup:
        if not self.conditions:
            raise ValueError("condition group must contain at least one condition")
        return self


class StrategyConfig(BaseModel):
    name: str
    market_filters: list[ConditionNode] = Field(default_factory=list)
    entry_groups: list[ConditionGroup]
    exit_rules: list[ConditionNode] = Field(default_factory=list)
    score_threshold: float | None = None

    @model_validator(mode="after")
    def require_entry_groups(self) -> StrategyConfig:
        if not self.entry_groups:
            raise ValueError("strategy must contain at least one entry group")
        if self.score_threshold is not None and self.score_threshold < 0:
            raise ValueError("score_threshold must be >= 0")
        return self


class BacktestSettings(BaseModel):
    start_date: date
    end_date: date
    initial_cash: float
    benchmark_symbol: str = "000300.SH"
    buy_price: Literal["next_open"] = "next_open"
    conservative_execution: bool = True
    limit_up_blocks_buy: bool = True
    limit_down_blocks_sell: bool = True
    fee_rate: float = 0.0003
    stamp_tax_rate: float = 0.0005
    slippage_rate: float = 0.0005
    fixed_holding_days: int = 5
    take_profit_pct: float | None = None
    stop_loss_pct: float | None = None
    max_positions: int = 10
    max_daily_buys: int = 3
    min_listing_days: int = 60
    exclude_st: bool = True

    @model_validator(mode="after")
    def validate_dates_and_money(self) -> BacktestSettings:
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be > 0")
        if self.fee_rate < 0:
            raise ValueError("fee_rate must be >= 0")
        if self.stamp_tax_rate < 0:
            raise ValueError("stamp_tax_rate must be >= 0")
        if self.slippage_rate < 0:
            raise ValueError("slippage_rate must be >= 0")
        if self.fixed_holding_days < 1:
            raise ValueError("fixed_holding_days must be >= 1")
        if self.max_positions < 1:
            raise ValueError("max_positions must be >= 1")
        if self.max_daily_buys < 1:
            raise ValueError("max_daily_buys must be >= 1")
        if self.min_listing_days < 0:
            raise ValueError("min_listing_days must be >= 0")
        if self.stop_loss_pct is not None and self.stop_loss_pct >= 0:
            raise ValueError("stop_loss_pct must be negative")
        if self.take_profit_pct is not None and self.take_profit_pct <= 0:
            raise ValueError("take_profit_pct must be positive")
        return self


class DatasetCoverage(BaseModel):
    dataset: str
    symbols: int
    start_date: date | None
    end_date: date | None
    missing_rows: int = 0


class PreflightIssue(BaseModel):
    code: str
    message: str
    severity: Literal["warning", "error"]
    dataset: str | None = None


class Trade(BaseModel):
    symbol: str
    buy_signal_date: date
    buy_date: date
    sell_signal_date: date | None = None
    sell_date: date | None = None
    buy_price: float
    sell_price: float | None = None
    shares: int
    buy_reason: list[str]
    sell_reason: list[str] = Field(default_factory=list)
    blocked_reason: str | None = None
    pnl: float | None = None
    pnl_pct: float | None = None


class EquityPoint(BaseModel):
    trade_date: date
    equity: float
    cash: float
    market_value: float
    drawdown_pct: float


class BacktestMetrics(BaseModel):
    total_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float
    win_rate_pct: float
    trade_count: int
    average_trade_return_pct: float


class BacktestResult(BaseModel):
    metrics: BacktestMetrics
    equity_curve: list[EquityPoint]
    trades: list[Trade]
    preflight_issues: list[PreflightIssue] = Field(default_factory=list)
