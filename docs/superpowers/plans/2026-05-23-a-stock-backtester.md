# A-Stock Backtester Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first Windows desktop version of the A-share daily historical backtester described in `docs/superpowers/specs/2026-05-23-a-stock-backtester-design.md`.

**Architecture:** Implement a testable Python backtesting core first, expose it through a small JSON CLI, then connect a React/Vite UI and Tauri desktop shell. Local data is normalized into SQLite metadata plus Parquet time-series files, with CSV/Parquet import available before the live `a-stock-data` adapter is wired in.

**Tech Stack:** Python 3.11+, pandas, numpy, pyarrow, pydantic, pytest, TypeScript, React, Vite, Vitest, Tauri 2, Rust serde, Recharts.

---

## References

- Product spec: `docs/superpowers/specs/2026-05-23-a-stock-backtester-design.md`
- Tauri commands and frontend invocation: https://v2.tauri.app/develop/calling-rust/
- Tauri sidecar/external binaries: https://v2.tauri.app/develop/sidecar/
- Vite app setup and dev workflow: https://vite.dev/guide/
- pytest fixtures and modular tests: https://docs.pytest.org/en/latest/fixture.html
- `a-stock-data` README: https://github.com/simonlin1212/a-stock-data

## Scope Check

The confirmed spec spans data ingestion, strategy modeling, backtesting, UI, and desktop packaging. Keep this as one implementation plan because each subsystem is required for the first usable vertical slice, but implement in this order:

1. Python models and deterministic test data.
2. Indicator, condition, and backtest correctness.
3. Local cache/import and CLI API.
4. React UI using the CLI contract.
5. Tauri command bridge and Windows packaging.

Do not start with Tauri UI scaffolding before the Python engine has tests. The highest correctness risk is lookahead bias and execution rules, not window chrome.

## File Structure

Create these files and keep responsibilities narrow:

- `pyproject.toml`: Python package metadata, dependencies, pytest config, Ruff config.
- `package.json`: frontend/Tauri npm scripts and JavaScript dependencies.
- `backend/astock_backtester/__init__.py`: package marker and version.
- `backend/astock_backtester/models.py`: pydantic models shared by the engine and CLI.
- `backend/astock_backtester/indicators.py`: pure indicator functions.
- `backend/astock_backtester/conditions.py`: condition registry and evaluators.
- `backend/astock_backtester/data/importer.py`: CSV/Parquet normalization.
- `backend/astock_backtester/data/cache.py`: SQLite metadata and Parquet file layout.
- `backend/astock_backtester/data/astock_adapter.py`: wrapper around `a-stock-data`-sourced fetch functions.
- `backend/astock_backtester/engine.py`: daily-bar backtest engine.
- `backend/astock_backtester/cli.py`: JSON command API used by Tauri.
- `backend/astock_backtester/sample_data.py`: deterministic fixtures for tests and demo mode.
- `tests/conftest.py`: shared pytest fixtures.
- `tests/test_indicators.py`: indicator tests.
- `tests/test_conditions.py`: condition and lookahead tests.
- `tests/test_engine.py`: backtest execution tests.
- `tests/test_cache_import_cli.py`: import/cache/CLI tests.
- `frontend/index.html`: Vite entry HTML.
- `frontend/src/main.tsx`: React entry.
- `frontend/src/App.tsx`: top-level app layout.
- `frontend/src/types.ts`: frontend copy of the JSON API types.
- `frontend/src/api.ts`: Tauri/mock API client.
- `frontend/src/strategyDefaults.ts`: default strategy and condition metadata.
- `frontend/src/components/DataCenter.tsx`: data coverage and import panel.
- `frontend/src/components/StrategyEditor.tsx`: searchable condition editor.
- `frontend/src/components/BacktestSettings.tsx`: cost, date, and execution settings.
- `frontend/src/components/ResultsOverview.tsx`: metrics and curves.
- `frontend/src/components/TradesTable.tsx`: trade explanations.
- `frontend/src/styles.css`: app styling.
- `frontend/src/__tests__/strategyEditor.test.tsx`: UI behavior tests.
- `frontend/src/testSetup.ts`: Vitest DOM assertion setup.
- `frontend/vite.config.ts`: Vite app config.
- `frontend/vitest.config.ts`: UI test config.
- `src-tauri/Cargo.toml`: Tauri Rust dependencies.
- `src-tauri/tauri.conf.json`: Tauri app configuration.
- `src-tauri/src/lib.rs`: Tauri command registration.
- `src-tauri/src/commands.rs`: bridge commands that call the Python CLI.
- `docs/dev.md`: local development and verification commands.

## Task 1: Python Project Skeleton And Domain Models

**Files:**
- Create: `pyproject.toml`
- Create: `backend/astock_backtester/__init__.py`
- Create: `backend/astock_backtester/models.py`
- Create: `tests/conftest.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing model tests**

Create `tests/test_models.py`:

```python
from datetime import date

import pytest
from pydantic import ValidationError

from astock_backtester.models import (
    BacktestSettings,
    ConditionNode,
    ConditionOperator,
    DatasetCoverage,
    StrategyConfig,
)


def test_strategy_config_rejects_empty_entry_groups():
    with pytest.raises(ValidationError):
        StrategyConfig(
            name="bad",
            market_filters=[],
            entry_groups=[],
            exit_rules=[],
            score_threshold=None,
        )


def test_condition_node_keeps_signal_date_boundary_metadata():
    node = ConditionNode(
        id="cap-small",
        condition_id="market_cap_between",
        enabled=True,
        params={"min": 2_000_000_000, "max": 20_000_000_000},
        weight=15.0,
        data_lag_days=0,
    )

    assert node.condition_id == "market_cap_between"
    assert node.params["max"] == 20_000_000_000
    assert node.data_lag_days == 0


def test_backtest_settings_defaults_to_conservative_execution():
    settings = BacktestSettings(
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 10),
        initial_cash=100_000,
    )

    assert settings.conservative_execution is True
    assert settings.buy_price == "next_open"
    assert settings.limit_up_blocks_buy is True
    assert settings.limit_down_blocks_sell is True


def test_dataset_coverage_tracks_market_cap_and_capital_flow():
    coverage = DatasetCoverage(
        dataset="capital_flow",
        symbols=12,
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 10),
        missing_rows=3,
    )

    assert coverage.dataset == "capital_flow"
    assert coverage.missing_rows == 3


def test_condition_operator_accepts_and_or_score():
    assert ConditionOperator.AND.value == "and"
    assert ConditionOperator.OR.value == "or"
    assert ConditionOperator.SCORE.value == "score"
```

- [ ] **Step 2: Run model test to verify it fails**

Run:

```powershell
python -m pytest tests/test_models.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'astock_backtester'`.

- [ ] **Step 3: Create Python package config**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=69", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "astock-backtester"
version = "0.1.0"
description = "Windows desktop A-share daily historical backtester backend"
requires-python = ">=3.11"
dependencies = [
  "numpy>=1.26",
  "pandas>=2.2",
  "pyarrow>=15",
  "pydantic>=2.7",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.2",
  "ruff>=0.5",
]

[project.scripts]
astock-backtester = "astock_backtester.cli:main"

[tool.setuptools.packages.find]
where = ["backend"]

[tool.pytest.ini_options]
pythonpath = ["backend"]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

Create `backend/astock_backtester/__init__.py`:

```python
__version__ = "0.1.0"
```

- [ ] **Step 4: Implement domain models**

Create `backend/astock_backtester/models.py`:

```python
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
    def require_conditions(self) -> "ConditionGroup":
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
    def require_entry_groups(self) -> "StrategyConfig":
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
    def validate_dates_and_money(self) -> "BacktestSettings":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be > 0")
        if self.fixed_holding_days < 1:
            raise ValueError("fixed_holding_days must be >= 1")
        if self.max_positions < 1:
            raise ValueError("max_positions must be >= 1")
        if self.max_daily_buys < 1:
            raise ValueError("max_daily_buys must be >= 1")
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
```

- [ ] **Step 5: Add pytest fixtures**

Create `tests/conftest.py`:

```python
from datetime import date

import pytest

from astock_backtester.models import BacktestSettings, ConditionGroup, ConditionNode, ConditionOperator, StrategyConfig


@pytest.fixture
def basic_strategy() -> StrategyConfig:
    return StrategyConfig(
        name="basic",
        market_filters=[
            ConditionNode(
                id="market-hot",
                condition_id="market_rising_ratio_at_least",
                params={"min_ratio": 0.5},
            )
        ],
        entry_groups=[
            ConditionGroup(
                id="entry",
                operator=ConditionOperator.AND,
                conditions=[
                    ConditionNode(
                        id="cap",
                        condition_id="market_cap_between",
                        params={"min": 1_000_000_000, "max": 30_000_000_000},
                    ),
                    ConditionNode(
                        id="flow",
                        condition_id="capital_flow_n_day_sum_at_least",
                        params={"window": 3, "min": 3_000_000},
                    ),
                ],
            )
        ],
        exit_rules=[
            ConditionNode(
                id="exit-ma",
                condition_id="close_below_ma",
                params={"window": 3},
            )
        ],
    )


@pytest.fixture
def basic_settings() -> BacktestSettings:
    return BacktestSettings(
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 12),
        initial_cash=100_000,
        fixed_holding_days=3,
        take_profit_pct=0.08,
        stop_loss_pct=-0.05,
        max_positions=2,
        max_daily_buys=1,
    )
```

- [ ] **Step 6: Run model tests**

Run:

```powershell
python -m pytest tests/test_models.py -q
```

Expected: `5 passed`.

- [ ] **Step 7: Commit Task 1**

```powershell
git add pyproject.toml backend/astock_backtester/__init__.py backend/astock_backtester/models.py tests/conftest.py tests/test_models.py
git commit -m "feat: add backend domain models"
```

## Task 2: Deterministic Sample Data And Indicators

**Files:**
- Create: `backend/astock_backtester/sample_data.py`
- Create: `backend/astock_backtester/indicators.py`
- Create: `tests/test_indicators.py`

- [ ] **Step 1: Write failing indicator tests**

Create `tests/test_indicators.py`:

```python
import pandas as pd

from astock_backtester.indicators import add_macd, add_market_heat, add_moving_average, add_returns
from astock_backtester.sample_data import sample_daily_bars


def test_add_moving_average_uses_symbol_boundaries():
    df = sample_daily_bars()
    result = add_moving_average(df, windows=[3])
    aaa = result[result["symbol"] == "AAA"].reset_index(drop=True)
    bbb = result[result["symbol"] == "BBB"].reset_index(drop=True)

    assert pd.isna(aaa.loc[1, "ma_3"])
    assert aaa.loc[2, "ma_3"] == 11.0
    assert bbb.loc[2, "ma_3"] == 21.0


def test_add_returns_calculates_past_gain_without_future_rows():
    df = sample_daily_bars()
    result = add_returns(df, windows=[2])
    aaa = result[result["symbol"] == "AAA"].reset_index(drop=True)

    assert round(aaa.loc[2, "return_2d"], 6) == round((12 / 10) - 1, 6)


def test_add_macd_outputs_expected_columns():
    result = add_macd(sample_daily_bars())

    assert {"macd_dif", "macd_dea", "macd_hist"}.issubset(result.columns)
    assert result["macd_hist"].notna().any()


def test_add_market_heat_computes_rising_ratio_by_date():
    result = add_market_heat(sample_daily_bars())
    heat = result[["trade_date", "market_rising_ratio"]].drop_duplicates()
    row = heat[heat["trade_date"] == pd.Timestamp("2024-01-03")].iloc[0]

    assert row["market_rising_ratio"] == 1.0
```

- [ ] **Step 2: Run indicator tests to verify failure**

Run:

```powershell
python -m pytest tests/test_indicators.py -q
```

Expected: fail with `ModuleNotFoundError` or `ImportError` for `astock_backtester.indicators`.

- [ ] **Step 3: Create deterministic sample data**

Create `backend/astock_backtester/sample_data.py`:

```python
from __future__ import annotations

import pandas as pd


def sample_daily_bars() -> pd.DataFrame:
    rows = [
        ("AAA", "2024-01-02", 10.0, 10.5, 9.8, 10.0, 1000, 0.03, 8_000_000_000, 2_000_000, False, False, 90),
        ("AAA", "2024-01-03", 10.0, 11.2, 9.9, 11.0, 1500, 0.04, 8_800_000_000, 3_000_000, False, False, 91),
        ("AAA", "2024-01-04", 11.0, 12.4, 10.8, 12.0, 2200, 0.06, 9_600_000_000, 4_000_000, False, False, 92),
        ("AAA", "2024-01-05", 12.0, 12.2, 10.6, 11.0, 1600, 0.05, 8_800_000_000, -1_000_000, False, False, 93),
        ("AAA", "2024-01-08", 11.0, 11.5, 10.1, 10.2, 1300, 0.04, 8_160_000_000, -2_000_000, False, False, 96),
        ("BBB", "2024-01-02", 20.0, 20.5, 19.8, 20.0, 800, 0.01, 40_000_000_000, 500_000, False, False, 200),
        ("BBB", "2024-01-03", 20.0, 21.2, 19.9, 21.0, 900, 0.02, 42_000_000_000, 400_000, False, False, 201),
        ("BBB", "2024-01-04", 21.0, 22.0, 20.5, 22.0, 950, 0.02, 44_000_000_000, 300_000, False, False, 202),
        ("BBB", "2024-01-05", 22.0, 22.1, 21.5, 21.8, 700, 0.01, 43_600_000_000, -300_000, False, False, 203),
        ("BBB", "2024-01-08", 21.8, 22.4, 21.2, 22.2, 850, 0.02, 44_400_000_000, 700_000, False, False, 206),
    ]
    columns = [
        "symbol",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "turnover_rate",
        "float_market_cap",
        "main_net_inflow",
        "is_st",
        "is_suspended",
        "listing_days",
    ]
    df = pd.DataFrame(rows, columns=columns)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
```

- [ ] **Step 4: Implement indicator functions**

Create `backend/astock_backtester/indicators.py`:

```python
from __future__ import annotations

import pandas as pd


def _sorted(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(["symbol", "trade_date"]).reset_index(drop=True)


def add_moving_average(df: pd.DataFrame, windows: list[int]) -> pd.DataFrame:
    out = _sorted(df).copy()
    grouped = out.groupby("symbol", group_keys=False)
    for window in windows:
        out[f"ma_{window}"] = grouped["close"].rolling(window=window).mean().reset_index(level=0, drop=True)
    return out


def add_returns(df: pd.DataFrame, windows: list[int]) -> pd.DataFrame:
    out = _sorted(df).copy()
    grouped = out.groupby("symbol", group_keys=False)
    for window in windows:
        out[f"return_{window}d"] = grouped["close"].pct_change(periods=window)
    return out


def add_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    out = _sorted(df).copy()

    def enrich(group: pd.DataFrame) -> pd.DataFrame:
        close = group["close"]
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=signal, adjust=False).mean()
        group = group.copy()
        group["macd_dif"] = dif
        group["macd_dea"] = dea
        group["macd_hist"] = (dif - dea) * 2
        return group

    return out.groupby("symbol", group_keys=False).apply(enrich, include_groups=False).reset_index(drop=True)


def add_market_heat(df: pd.DataFrame) -> pd.DataFrame:
    out = _sorted(df).copy()
    previous_close = out.groupby("symbol")["close"].shift(1)
    out["_is_rising"] = out["close"] > previous_close
    heat = (
        out.groupby("trade_date")["_is_rising"]
        .mean()
        .rename("market_rising_ratio")
        .reset_index()
    )
    out = out.merge(heat, on="trade_date", how="left")
    out["market_rising_ratio"] = out["market_rising_ratio"].fillna(0.0)
    return out.drop(columns=["_is_rising"])
```

- [ ] **Step 5: Run indicator tests**

Run:

```powershell
python -m pytest tests/test_indicators.py -q
```

Expected: `4 passed`.

- [ ] **Step 6: Commit Task 2**

```powershell
git add backend/astock_backtester/sample_data.py backend/astock_backtester/indicators.py tests/test_indicators.py
git commit -m "feat: add daily indicator calculations"
```

## Task 3: Condition Registry With Market Cap And Capital Flow

**Files:**
- Create: `backend/astock_backtester/conditions.py`
- Create: `tests/test_conditions.py`

- [ ] **Step 1: Write failing condition tests**

Create `tests/test_conditions.py`:

```python
import pandas as pd

from astock_backtester.conditions import evaluate_condition, evaluate_group, registered_conditions
from astock_backtester.indicators import add_market_heat, add_moving_average
from astock_backtester.models import ConditionGroup, ConditionNode, ConditionOperator
from astock_backtester.sample_data import sample_daily_bars


def enriched_frame() -> pd.DataFrame:
    return add_market_heat(add_moving_average(sample_daily_bars(), [3]))


def test_registry_contains_core_first_version_conditions():
    ids = {item.condition_id for item in registered_conditions()}

    assert "market_cap_between" in ids
    assert "capital_flow_n_day_sum_at_least" in ids
    assert "market_rising_ratio_at_least" in ids
    assert "close_above_ma" in ids


def test_market_cap_between_uses_signal_day_value():
    df = enriched_frame()
    row = df[(df["symbol"] == "AAA") & (df["trade_date"] == pd.Timestamp("2024-01-04"))].iloc[0]
    node = ConditionNode(
        id="cap",
        condition_id="market_cap_between",
        params={"min": 8_000_000_000, "max": 10_000_000_000},
    )

    result = evaluate_condition(node, row, df)

    assert result.passed is True
    assert "float market cap" in result.reason


def test_capital_flow_rolling_sum_is_date_bound():
    df = enriched_frame()
    row = df[(df["symbol"] == "AAA") & (df["trade_date"] == pd.Timestamp("2024-01-04"))].iloc[0]
    node = ConditionNode(
        id="flow",
        condition_id="capital_flow_n_day_sum_at_least",
        params={"window": 3, "min": 9_000_000},
    )

    result = evaluate_condition(node, row, df)

    assert result.passed is True
    assert result.observed_value == 9_000_000


def test_and_group_requires_all_conditions():
    df = enriched_frame()
    row = df[(df["symbol"] == "AAA") & (df["trade_date"] == pd.Timestamp("2024-01-04"))].iloc[0]
    group = ConditionGroup(
        id="entry",
        operator=ConditionOperator.AND,
        conditions=[
            ConditionNode(id="cap", condition_id="market_cap_between", params={"min": 1, "max": 10_000_000_000}),
            ConditionNode(id="ma", condition_id="close_above_ma", params={"window": 3}),
        ],
    )

    result = evaluate_group(group, row, df)

    assert result.passed is True
    assert len(result.reasons) == 2


def test_score_group_requires_threshold():
    df = enriched_frame()
    row = df[(df["symbol"] == "AAA") & (df["trade_date"] == pd.Timestamp("2024-01-04"))].iloc[0]
    group = ConditionGroup(
        id="score",
        operator=ConditionOperator.SCORE,
        conditions=[
            ConditionNode(id="cap", condition_id="market_cap_between", params={"min": 1, "max": 10_000_000_000}, weight=20),
            ConditionNode(id="hot", condition_id="market_rising_ratio_at_least", params={"min_ratio": 0.5}, weight=15),
        ],
    )

    result = evaluate_group(group, row, df, score_threshold=30)

    assert result.passed is True
    assert result.score == 35
```

- [ ] **Step 2: Run condition tests to verify failure**

Run:

```powershell
python -m pytest tests/test_conditions.py -q
```

Expected: fail with `ModuleNotFoundError` or missing `conditions`.

- [ ] **Step 3: Implement condition registry**

Create `backend/astock_backtester/conditions.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from astock_backtester.models import ConditionGroup, ConditionNode, ConditionOperator


@dataclass(frozen=True)
class ConditionDefinition:
    condition_id: str
    label: str
    category: str
    required_columns: tuple[str, ...]


@dataclass(frozen=True)
class ConditionResult:
    passed: bool
    reason: str
    observed_value: float | None = None


@dataclass(frozen=True)
class GroupResult:
    passed: bool
    reasons: list[str]
    score: float = 0.0


Evaluator = Callable[[ConditionNode, pd.Series, pd.DataFrame], ConditionResult]


def registered_conditions() -> list[ConditionDefinition]:
    return [
        ConditionDefinition("market_cap_between", "Float market cap range", "market_cap", ("float_market_cap",)),
        ConditionDefinition("capital_flow_n_day_sum_at_least", "N-day main net inflow", "capital_flow", ("main_net_inflow",)),
        ConditionDefinition("market_rising_ratio_at_least", "Market rising ratio", "market_heat", ("market_rising_ratio",)),
        ConditionDefinition("close_above_ma", "Close above moving average", "trend", ()),
        ConditionDefinition("close_below_ma", "Close below moving average", "trend", ()),
        ConditionDefinition("turnover_between", "Turnover range", "volume", ("turnover_rate",)),
        ConditionDefinition("past_return_at_most", "Past return upper bound", "price_movement", ()),
    ]


def _market_cap_between(node: ConditionNode, row: pd.Series, frame: pd.DataFrame) -> ConditionResult:
    value = float(row["float_market_cap"])
    minimum = float(node.params["min"])
    maximum = float(node.params["max"])
    passed = minimum <= value <= maximum
    return ConditionResult(passed, f"float market cap {value:.0f} in [{minimum:.0f}, {maximum:.0f}]", value)


def _capital_flow_n_day_sum_at_least(node: ConditionNode, row: pd.Series, frame: pd.DataFrame) -> ConditionResult:
    window = int(node.params["window"])
    minimum = float(node.params["min"])
    symbol_frame = frame[
        (frame["symbol"] == row["symbol"]) & (frame["trade_date"] <= row["trade_date"])
    ].sort_values("trade_date")
    value = float(symbol_frame.tail(window)["main_net_inflow"].sum())
    passed = value >= minimum
    return ConditionResult(passed, f"{window}d main net inflow {value:.0f} >= {minimum:.0f}", value)


def _market_rising_ratio_at_least(node: ConditionNode, row: pd.Series, frame: pd.DataFrame) -> ConditionResult:
    value = float(row["market_rising_ratio"])
    minimum = float(node.params["min_ratio"])
    return ConditionResult(value >= minimum, f"market rising ratio {value:.2%} >= {minimum:.2%}", value)


def _close_above_ma(node: ConditionNode, row: pd.Series, frame: pd.DataFrame) -> ConditionResult:
    window = int(node.params["window"])
    value = float(row["close"] - row[f"ma_{window}"])
    return ConditionResult(value > 0, f"close {row['close']:.2f} above MA{window} {row[f'ma_{window}']:.2f}", value)


def _close_below_ma(node: ConditionNode, row: pd.Series, frame: pd.DataFrame) -> ConditionResult:
    window = int(node.params["window"])
    value = float(row["close"] - row[f"ma_{window}"])
    return ConditionResult(value < 0, f"close {row['close']:.2f} below MA{window} {row[f'ma_{window}']:.2f}", value)


def _turnover_between(node: ConditionNode, row: pd.Series, frame: pd.DataFrame) -> ConditionResult:
    value = float(row["turnover_rate"])
    minimum = float(node.params["min"])
    maximum = float(node.params["max"])
    return ConditionResult(minimum <= value <= maximum, f"turnover {value:.2%} in [{minimum:.2%}, {maximum:.2%}]", value)


def _past_return_at_most(node: ConditionNode, row: pd.Series, frame: pd.DataFrame) -> ConditionResult:
    window = int(node.params["window"])
    value = float(row[f"return_{window}d"])
    maximum = float(node.params["max"])
    return ConditionResult(value <= maximum, f"{window}d return {value:.2%} <= {maximum:.2%}", value)


EVALUATORS: dict[str, Evaluator] = {
    "market_cap_between": _market_cap_between,
    "capital_flow_n_day_sum_at_least": _capital_flow_n_day_sum_at_least,
    "market_rising_ratio_at_least": _market_rising_ratio_at_least,
    "close_above_ma": _close_above_ma,
    "close_below_ma": _close_below_ma,
    "turnover_between": _turnover_between,
    "past_return_at_most": _past_return_at_most,
}


def evaluate_condition(node: ConditionNode, row: pd.Series, frame: pd.DataFrame) -> ConditionResult:
    if not node.enabled:
        return ConditionResult(True, f"{node.condition_id} disabled")
    try:
        evaluator = EVALUATORS[node.condition_id]
    except KeyError as exc:
        raise ValueError(f"unknown condition_id: {node.condition_id}") from exc
    return evaluator(node, row, frame)


def evaluate_group(
    group: ConditionGroup,
    row: pd.Series,
    frame: pd.DataFrame,
    score_threshold: float | None = None,
) -> GroupResult:
    results = [evaluate_condition(node, row, frame) for node in group.conditions]
    reasons = [result.reason for result in results if result.passed]

    if group.operator == ConditionOperator.AND:
        return GroupResult(all(result.passed for result in results), reasons)
    if group.operator == ConditionOperator.OR:
        return GroupResult(any(result.passed for result in results), reasons)

    score = 0.0
    for node, result in zip(group.conditions, results, strict=True):
        if result.passed:
            score += float(node.weight or 0.0)
    threshold = float(score_threshold or 0.0)
    return GroupResult(score >= threshold, reasons, score)
```

- [ ] **Step 4: Run condition tests**

Run:

```powershell
python -m pytest tests/test_conditions.py -q
```

Expected: `5 passed`.

- [ ] **Step 5: Commit Task 3**

```powershell
git add backend/astock_backtester/conditions.py tests/test_conditions.py
git commit -m "feat: add strategy condition registry"
```

## Task 4: Local Cache, CSV/Parquet Import, And Preflight

**Files:**
- Create: `backend/astock_backtester/data/__init__.py`
- Create: `backend/astock_backtester/data/importer.py`
- Create: `backend/astock_backtester/data/cache.py`
- Create: `tests/test_cache_import_cli.py`

- [ ] **Step 1: Write failing cache/import tests**

Create `tests/test_cache_import_cli.py`:

```python
import pandas as pd

from astock_backtester.data.cache import LocalCache
from astock_backtester.data.importer import normalize_daily_bars
from astock_backtester.sample_data import sample_daily_bars


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
```

- [ ] **Step 2: Run cache/import tests to verify failure**

Run:

```powershell
python -m pytest tests/test_cache_import_cli.py -q
```

Expected: fail with missing `astock_backtester.data`.

- [ ] **Step 3: Implement data package marker**

Create `backend/astock_backtester/data/__init__.py`:

```python
"""Data import, cache, and external adapter modules."""
```

- [ ] **Step 4: Implement CSV/Parquet normalization**

Create `backend/astock_backtester/data/importer.py`:

```python
from __future__ import annotations

from pathlib import Path

import pandas as pd


REQUIRED_DAILY_COLUMNS = ["symbol", "trade_date", "open", "high", "low", "close", "volume"]


def normalize_daily_bars(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "trade_date" not in out.columns and "date" in out.columns:
        out = out.rename(columns={"date": "trade_date"})
    missing = [column for column in REQUIRED_DAILY_COLUMNS if column not in out.columns]
    if missing:
        raise ValueError(f"daily bars missing required columns: {', '.join(missing)}")

    out["symbol"] = out["symbol"].astype(str)
    out["trade_date"] = pd.to_datetime(out["trade_date"])
    for column in ["open", "high", "low", "close", "volume"]:
        out[column] = pd.to_numeric(out[column], errors="raise")

    optional_defaults = {
        "turnover_rate": 0.0,
        "float_market_cap": float("nan"),
        "main_net_inflow": 0.0,
        "is_st": False,
        "is_suspended": False,
        "listing_days": 9999,
    }
    for column, default in optional_defaults.items():
        if column not in out.columns:
            out[column] = default

    return out.sort_values(["symbol", "trade_date"]).reset_index(drop=True)


def read_daily_bars(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    if source.suffix.lower() == ".csv":
        return normalize_daily_bars(pd.read_csv(source))
    if source.suffix.lower() in {".parquet", ".pq"}:
        return normalize_daily_bars(pd.read_parquet(source))
    raise ValueError(f"unsupported daily bars file extension: {source.suffix}")
```

- [ ] **Step 5: Implement local cache**

Create `backend/astock_backtester/data/cache.py`:

```python
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from astock_backtester.data.importer import normalize_daily_bars
from astock_backtester.models import DatasetCoverage


class LocalCache:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.parquet_dir = self.root / "parquet"
        self.parquet_dir.mkdir(parents=True, exist_ok=True)
        self.sqlite_path = self.root / "metadata.sqlite"
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    dataset TEXT PRIMARY KEY,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    @property
    def daily_bars_path(self) -> Path:
        return self.parquet_dir / "daily_bars.parquet"

    def write_daily_bars(self, frame: pd.DataFrame) -> None:
        normalized = normalize_daily_bars(frame)
        normalized.to_parquet(self.daily_bars_path, index=False)
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO datasets(dataset, updated_at) VALUES('daily_bars', CURRENT_TIMESTAMP)"
            )

    def read_daily_bars(self) -> pd.DataFrame:
        if not self.daily_bars_path.exists():
            return pd.DataFrame()
        return pd.read_parquet(self.daily_bars_path).sort_values(["symbol", "trade_date"]).reset_index(drop=True)

    def coverage(self) -> list[DatasetCoverage]:
        bars = self.read_daily_bars()
        if bars.empty:
            return [DatasetCoverage(dataset="daily_bars", symbols=0, start_date=None, end_date=None)]
        return [
            DatasetCoverage(
                dataset="daily_bars",
                symbols=int(bars["symbol"].nunique()),
                start_date=bars["trade_date"].min().date(),
                end_date=bars["trade_date"].max().date(),
                missing_rows=int(bars[["open", "high", "low", "close"]].isna().any(axis=1).sum()),
            )
        ]
```

- [ ] **Step 6: Run cache/import tests**

Run:

```powershell
python -m pytest tests/test_cache_import_cli.py -q
```

Expected: `3 passed`.

- [ ] **Step 7: Commit Task 4**

```powershell
git add backend/astock_backtester/data/__init__.py backend/astock_backtester/data/importer.py backend/astock_backtester/data/cache.py tests/test_cache_import_cli.py
git commit -m "feat: add local data cache"
```

## Task 5: Daily Backtest Engine

**Files:**
- Create: `backend/astock_backtester/engine.py`
- Create: `tests/test_engine.py`

- [ ] **Step 1: Write failing engine tests**

Create `tests/test_engine.py`:

```python
from astock_backtester.engine import run_backtest
from astock_backtester.indicators import add_market_heat, add_moving_average, add_returns
from astock_backtester.sample_data import sample_daily_bars


def enriched_data():
    frame = sample_daily_bars()
    frame = add_moving_average(frame, [3])
    frame = add_returns(frame, [2])
    frame = add_market_heat(frame)
    return frame


def test_backtest_buys_next_open_after_signal(basic_strategy, basic_settings):
    result = run_backtest(enriched_data(), basic_strategy, basic_settings)

    assert result.trades
    first = result.trades[0]
    assert str(first.buy_signal_date) == "2024-01-04"
    assert str(first.buy_date) == "2024-01-05"
    assert first.buy_price == 12.0
    assert any("float market cap" in reason for reason in first.buy_reason)


def test_backtest_respects_max_daily_buys(basic_strategy, basic_settings):
    result = run_backtest(enriched_data(), basic_strategy, basic_settings)
    buys_by_day = {}
    for trade in result.trades:
        buys_by_day.setdefault(trade.buy_date, 0)
        buys_by_day[trade.buy_date] += 1

    assert max(buys_by_day.values()) <= 1


def test_backtest_reports_metrics_and_equity_curve(basic_strategy, basic_settings):
    result = run_backtest(enriched_data(), basic_strategy, basic_settings)

    assert result.metrics.trade_count >= 1
    assert result.equity_curve
    assert result.metrics.max_drawdown_pct <= 0


def test_preflight_reports_missing_capital_flow_when_required(basic_strategy, basic_settings):
    data = enriched_data().drop(columns=["main_net_inflow"])

    result = run_backtest(data, basic_strategy, basic_settings)

    assert any(issue.dataset == "capital_flow" and issue.severity == "error" for issue in result.preflight_issues)
    assert result.trades == []
```

- [ ] **Step 2: Run engine tests to verify failure**

Run:

```powershell
python -m pytest tests/test_engine.py -q
```

Expected: fail with missing `astock_backtester.engine`.

- [ ] **Step 3: Implement engine preflight and backtest**

Create `backend/astock_backtester/engine.py`:

```python
from __future__ import annotations

from datetime import date

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


def _build_metrics(initial_cash: float, final_equity: float, trades: list[Trade], equity_curve: list[EquityPoint]) -> BacktestMetrics:
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
    trade_dates = sorted(data["trade_date"].unique())
    cash = settings.initial_cash
    trades: list[Trade] = []
    open_positions: list[Trade] = []
    equity_curve: list[EquityPoint] = []
    peak_equity = settings.initial_cash

    for signal_date in trade_dates:
        today = data[data["trade_date"] == signal_date]

        still_open: list[Trade] = []
        for position in open_positions:
            held_days = sum(position.buy_date <= item <= signal_date for item in trade_dates)
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
                position.sell_signal_date = signal_date.date()
                position.sell_date = signal_date.date()
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
                        buy_signal_date=signal_date.date(),
                        buy_date=next_date.date(),
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
```

- [ ] **Step 4: Run engine tests**

Run:

```powershell
python -m pytest tests/test_engine.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Run all backend tests**

Run:

```powershell
python -m pytest tests -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 5**

```powershell
git add backend/astock_backtester/engine.py tests/test_engine.py
git commit -m "feat: add daily backtest engine"
```

## Task 6: JSON CLI API For Tauri And Demo Mode

**Files:**
- Create: `backend/astock_backtester/cli.py`
- Modify: `tests/test_cache_import_cli.py`

- [ ] **Step 1: Add failing CLI tests**

Append to `tests/test_cache_import_cli.py`:

```python
import json

from astock_backtester.cli import handle_command


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
```

- [ ] **Step 2: Run CLI tests to verify failure**

Run:

```powershell
python -m pytest tests/test_cache_import_cli.py -q
```

Expected: fail with missing `astock_backtester.cli`.

- [ ] **Step 3: Implement CLI**

Create `backend/astock_backtester/cli.py`:

```python
from __future__ import annotations

import json
import sys
from datetime import date
from typing import Any

from astock_backtester.data.cache import LocalCache
from astock_backtester.engine import run_backtest
from astock_backtester.indicators import add_market_heat, add_moving_average, add_returns
from astock_backtester.models import BacktestSettings, ConditionGroup, ConditionNode, ConditionOperator, StrategyConfig
from astock_backtester.sample_data import sample_daily_bars


def _default_strategy() -> StrategyConfig:
    return StrategyConfig(
        name="demo",
        market_filters=[
            ConditionNode(id="market", condition_id="market_rising_ratio_at_least", params={"min_ratio": 0.5})
        ],
        entry_groups=[
            ConditionGroup(
                id="entry",
                operator=ConditionOperator.AND,
                conditions=[
                    ConditionNode(id="cap", condition_id="market_cap_between", params={"min": 1, "max": 30_000_000_000}),
                    ConditionNode(id="flow", condition_id="capital_flow_n_day_sum_at_least", params={"window": 3, "min": 3_000_000}),
                    ConditionNode(id="ma", condition_id="close_above_ma", params={"window": 3}),
                ],
            )
        ],
        exit_rules=[ConditionNode(id="exit", condition_id="close_below_ma", params={"window": 3})],
    )


def _default_settings() -> BacktestSettings:
    return BacktestSettings(
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 8),
        initial_cash=100_000,
        fixed_holding_days=3,
        take_profit_pct=0.08,
        stop_loss_pct=-0.05,
        max_positions=2,
        max_daily_buys=1,
    )


def _jsonable_model(model: Any) -> Any:
    return json.loads(model.model_dump_json())


def handle_command(payload: dict[str, Any]) -> dict[str, Any]:
    command = payload.get("command")
    try:
        if command == "coverage":
            cache = LocalCache(payload["cache_dir"])
            return {"ok": True, "coverage": [_jsonable_model(item) for item in cache.coverage()]}
        if command == "demo_backtest":
            frame = sample_daily_bars()
            frame = add_moving_average(frame, [3])
            frame = add_returns(frame, [2])
            frame = add_market_heat(frame)
            result = run_backtest(frame, _default_strategy(), _default_settings())
            return {"ok": True, "result": _jsonable_model(result)}
        return {"ok": False, "error": {"code": "unknown_command", "message": f"Unknown command: {command}"}}
    except Exception as exc:
        return {"ok": False, "error": {"code": "command_failed", "message": str(exc)}}


def main() -> None:
    raw = sys.stdin.read()
    payload = json.loads(raw) if raw.strip() else {}
    print(json.dumps(handle_command(payload), ensure_ascii=False))
```

- [ ] **Step 4: Run CLI tests**

Run:

```powershell
python -m pytest tests/test_cache_import_cli.py -q
```

Expected: all tests in the file pass.

- [ ] **Step 5: Smoke test CLI through stdin**

Run:

```powershell
'{"command":"demo_backtest"}' | python -m astock_backtester.cli
```

Expected: JSON begins with `{"ok": true, "result":`.

- [ ] **Step 6: Commit Task 6**

```powershell
git add backend/astock_backtester/cli.py tests/test_cache_import_cli.py
git commit -m "feat: add backend json cli"
```

## Task 7: Frontend Scaffold, Types, API Client, And Tests

**Files:**
- Create: `package.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/types.ts`
- Create: `frontend/src/api.ts`
- Create: `frontend/src/strategyDefaults.ts`
- Create: `frontend/src/styles.css`
- Create: `frontend/src/__tests__/strategyEditor.test.tsx`
- Create: `frontend/vitest.config.ts`

- [ ] **Step 1: Create frontend package config**

Create `package.json`:

```json
{
  "name": "a-stock-backtester",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite --host 127.0.0.1 --config frontend/vite.config.ts",
    "test:ui": "vitest --config frontend/vitest.config.ts",
    "build": "vite build --config frontend/vite.config.ts",
    "tauri": "tauri"
  },
  "dependencies": {
    "@tauri-apps/api": "^2.0.0",
    "lucide-react": "^0.468.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "recharts": "^2.12.7"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.4.6",
    "@testing-library/react": "^15.0.7",
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "jsdom": "^24.1.0",
    "typescript": "^5.5.0",
    "vite": "^5.3.0",
    "vitest": "^1.6.0"
  }
}
```

Create `frontend/vite.config.ts`:

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  root: "frontend",
  plugins: [react()],
  server: {
    port: 1420,
    strictPort: false
  },
  build: {
    outDir: "../dist",
    emptyOutDir: true
  }
});
```

Create `frontend/vitest.config.ts`:

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  root: "frontend",
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["src/testSetup.ts"]
  }
});
```

Create `frontend/src/testSetup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 2: Create frontend types and mock API**

Create `frontend/src/types.ts`:

```ts
export type DatasetCoverage = {
  dataset: string;
  symbols: number;
  start_date: string | null;
  end_date: string | null;
  missing_rows: number;
};

export type ConditionNode = {
  id: string;
  condition_id: string;
  enabled: boolean;
  params: Record<string, number | string | boolean>;
  weight?: number | null;
  data_lag_days: number;
};

export type ConditionGroup = {
  id: string;
  operator: "and" | "or" | "score";
  conditions: ConditionNode[];
};

export type StrategyConfig = {
  name: string;
  market_filters: ConditionNode[];
  entry_groups: ConditionGroup[];
  exit_rules: ConditionNode[];
  score_threshold?: number | null;
};

export type BacktestMetrics = {
  total_return_pct: number;
  annualized_return_pct: number;
  max_drawdown_pct: number;
  win_rate_pct: number;
  trade_count: number;
  average_trade_return_pct: number;
};

export type EquityPoint = {
  trade_date: string;
  equity: number;
  cash: number;
  market_value: number;
  drawdown_pct: number;
};

export type Trade = {
  symbol: string;
  buy_signal_date: string;
  buy_date: string;
  sell_date?: string | null;
  buy_price: number;
  sell_price?: number | null;
  shares: number;
  buy_reason: string[];
  sell_reason: string[];
  pnl?: number | null;
  pnl_pct?: number | null;
};

export type BacktestResult = {
  metrics: BacktestMetrics;
  equity_curve: EquityPoint[];
  trades: Trade[];
  preflight_issues: Array<{ code: string; message: string; severity: "warning" | "error"; dataset?: string | null }>;
};
```

Create `frontend/src/api.ts`:

```ts
import { invoke } from "@tauri-apps/api/core";
import type { BacktestResult, DatasetCoverage } from "./types";

type BackendResponse<T> = { ok: true } & T | { ok: false; error: { code: string; message: string } };

const demoResult: BacktestResult = {
  metrics: {
    total_return_pct: 0.032,
    annualized_return_pct: 0.032,
    max_drawdown_pct: -0.018,
    win_rate_pct: 0.6,
    trade_count: 5,
    average_trade_return_pct: 0.011
  },
  equity_curve: [
    { trade_date: "2024-01-02", equity: 100000, cash: 100000, market_value: 0, drawdown_pct: 0 },
    { trade_date: "2024-01-05", equity: 102300, cash: 51000, market_value: 51300, drawdown_pct: 0 },
    { trade_date: "2024-01-08", equity: 103200, cash: 103200, market_value: 0, drawdown_pct: 0 }
  ],
  trades: [
    {
      symbol: "AAA",
      buy_signal_date: "2024-01-04",
      buy_date: "2024-01-05",
      sell_date: "2024-01-08",
      buy_price: 12,
      sell_price: 10.2,
      shares: 4000,
      buy_reason: ["float market cap in range", "3d main net inflow >= threshold"],
      sell_reason: ["fixed holding days reached"],
      pnl: -7200,
      pnl_pct: -0.15
    }
  ],
  preflight_issues: []
};

function isTauriRuntime(): boolean {
  return Boolean((window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__);
}

async function callBackend<T>(payload: Record<string, unknown>): Promise<T> {
  if (!isTauriRuntime()) {
    if (payload.command === "coverage") {
      return {
        coverage: [
          { dataset: "daily_bars", symbols: 2, start_date: "2024-01-02", end_date: "2024-01-08", missing_rows: 0 },
          { dataset: "capital_flow", symbols: 2, start_date: "2024-01-02", end_date: "2024-01-08", missing_rows: 0 }
        ]
      } as T;
    }
    return { result: demoResult } as T;
  }
  const response = await invoke<BackendResponse<T>>("backend_command", { payload });
  if (!response.ok) {
    throw new Error(response.error.message);
  }
  return response;
}

export async function loadCoverage(cacheDir: string): Promise<DatasetCoverage[]> {
  const response = await callBackend<{ coverage: DatasetCoverage[] }>({ command: "coverage", cache_dir: cacheDir });
  return response.coverage;
}

export async function runDemoBacktest(): Promise<BacktestResult> {
  const response = await callBackend<{ result: BacktestResult }>({ command: "demo_backtest" });
  return response.result;
}
```

- [ ] **Step 3: Create default strategy metadata**

Create `frontend/src/strategyDefaults.ts`:

```ts
import type { StrategyConfig } from "./types";

export const conditionCategories = [
  "Market Heat",
  "Market Cap",
  "Capital Flow",
  "Trend",
  "Volume",
  "Price Movement",
  "Pattern"
] as const;

export const conditionLibrary = [
  { id: "market_rising_ratio_at_least", label: "Market rising ratio", category: "Market Heat" },
  { id: "market_cap_between", label: "Float market cap range", category: "Market Cap" },
  { id: "capital_flow_n_day_sum_at_least", label: "N-day main net inflow", category: "Capital Flow" },
  { id: "close_above_ma", label: "Close above moving average", category: "Trend" },
  { id: "turnover_between", label: "Turnover range", category: "Volume" }
];

export const defaultStrategy: StrategyConfig = {
  name: "Market heat + small cap inflow",
  market_filters: [
    {
      id: "market",
      condition_id: "market_rising_ratio_at_least",
      enabled: true,
      params: { min_ratio: 0.5 },
      data_lag_days: 0
    }
  ],
  entry_groups: [
    {
      id: "entry",
      operator: "and",
      conditions: [
        {
          id: "cap",
          condition_id: "market_cap_between",
          enabled: true,
          params: { min: 1000000000, max: 30000000000 },
          data_lag_days: 0
        },
        {
          id: "flow",
          condition_id: "capital_flow_n_day_sum_at_least",
          enabled: true,
          params: { window: 3, min: 3000000 },
          data_lag_days: 0
        }
      ]
    }
  ],
  exit_rules: [
    {
      id: "exit-ma",
      condition_id: "close_below_ma",
      enabled: true,
      params: { window: 3 },
      data_lag_days: 0
    }
  ],
  score_threshold: null
};
```

- [ ] **Step 4: Create smoke UI and test**

Create `frontend/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>A-Stock Backtester</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

Create `frontend/src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

Create `frontend/src/App.tsx`:

```tsx
import { useMemo, useState } from "react";
import { defaultStrategy } from "./strategyDefaults";
import type { StrategyConfig } from "./types";

export function App() {
  const [strategy] = useState<StrategyConfig>(defaultStrategy);
  const enabledCount = useMemo(
    () => strategy.market_filters.length + strategy.entry_groups.flatMap((group) => group.conditions).length,
    [strategy]
  );

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>A-Stock Backtester</h1>
          <p>Daily historical strategy research for A-share data.</p>
        </div>
        <strong>{enabledCount} active conditions</strong>
      </header>
      <section className="panel">
        <h2>{strategy.name}</h2>
        <p>Market cap, capital flow, market heat, and technical conditions are ready for editing.</p>
      </section>
    </main>
  );
}
```

Create `frontend/src/styles.css`:

```css
:root {
  font-family: Inter, "Segoe UI", Arial, sans-serif;
  color: #18202b;
  background: #f4f6f8;
}

body {
  margin: 0;
}

.app-shell {
  min-height: 100vh;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 20px 28px;
  background: #ffffff;
  border-bottom: 1px solid #d9dee7;
}

.topbar h1 {
  margin: 0;
  font-size: 24px;
}

.topbar p {
  margin: 4px 0 0;
  color: #5d6978;
}

.panel {
  margin: 24px;
  padding: 20px;
  background: #ffffff;
  border: 1px solid #d9dee7;
  border-radius: 8px;
}
```

Create `frontend/src/__tests__/strategyEditor.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { App } from "../App";

describe("App shell", () => {
  it("shows active condition count and strategy name", () => {
    render(<App />);

    expect(screen.getByText("A-Stock Backtester")).toBeInTheDocument();
    expect(screen.getByText("3 active conditions")).toBeInTheDocument();
    expect(screen.getByText("Market heat + small cap inflow")).toBeInTheDocument();
  });
});
```

- [ ] **Step 5: Install frontend dependencies**

Run:

```powershell
npm install
```

Expected: `package-lock.json` is created and npm exits with code 0.

- [ ] **Step 6: Run frontend tests**

Run:

```powershell
npm run test:ui -- --run
```

Expected: `1 passed`.

- [ ] **Step 7: Commit Task 7**

```powershell
git add package.json package-lock.json frontend
git commit -m "feat: scaffold frontend app"
```

## Task 8: Full React Work Areas

**Files:**
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/components/DataCenter.tsx`
- Create: `frontend/src/components/StrategyEditor.tsx`
- Create: `frontend/src/components/BacktestSettings.tsx`
- Create: `frontend/src/components/ResultsOverview.tsx`
- Create: `frontend/src/components/TradesTable.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/__tests__/strategyEditor.test.tsx`

- [ ] **Step 1: Replace UI test with work-area assertions**

Replace `frontend/src/__tests__/strategyEditor.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { App } from "../App";

describe("Backtester UI", () => {
  it("renders the five first-version work areas", async () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "Data Center" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Strategy Editor" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Backtest Settings" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Result Overview" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Trade Explanations" })).toBeInTheDocument();
  });

  it("exposes market cap and capital flow conditions", () => {
    render(<App />);

    expect(screen.getByText("Float market cap range")).toBeInTheDocument();
    expect(screen.getByText("N-day main net inflow")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run UI tests to verify failure**

Run:

```powershell
npm run test:ui -- --run
```

Expected: tests fail because the five work-area components do not exist in the UI.

- [ ] **Step 3: Implement Data Center**

Create `frontend/src/components/DataCenter.tsx`:

```tsx
import type { DatasetCoverage } from "../types";

type Props = {
  coverage: DatasetCoverage[];
  onRefresh: () => void;
};

export function DataCenter({ coverage, onRefresh }: Props) {
  return (
    <section className="surface">
      <div className="section-title">
        <h2>Data Center</h2>
        <button type="button" onClick={onRefresh}>Refresh</button>
      </div>
      <table>
        <thead>
          <tr>
            <th>Dataset</th>
            <th>Symbols</th>
            <th>Date Range</th>
            <th>Missing Rows</th>
          </tr>
        </thead>
        <tbody>
          {coverage.map((item) => (
            <tr key={item.dataset}>
              <td>{item.dataset}</td>
              <td>{item.symbols}</td>
              <td>{item.start_date ?? "-"} to {item.end_date ?? "-"}</td>
              <td>{item.missing_rows}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
```

- [ ] **Step 4: Implement Strategy Editor**

Create `frontend/src/components/StrategyEditor.tsx`:

```tsx
import { conditionLibrary } from "../strategyDefaults";
import type { StrategyConfig } from "../types";

type Props = {
  strategy: StrategyConfig;
};

export function StrategyEditor({ strategy }: Props) {
  return (
    <section className="surface">
      <div className="section-title">
        <h2>Strategy Editor</h2>
        <span>{strategy.name}</span>
      </div>
      <div className="strategy-grid">
        <div>
          <h3>Condition Library</h3>
          <input aria-label="Search indicators, market cap, capital flow" />
          <ul className="condition-list">
            {conditionLibrary.map((condition) => (
              <li key={condition.id}>
                <strong>{condition.label}</strong>
                <small>{condition.category}</small>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3>Entry Groups</h3>
          {strategy.entry_groups.map((group) => (
            <div className="group" key={group.id}>
              <strong>{group.operator.toUpperCase()}</strong>
              {group.conditions.map((condition) => (
                <p key={condition.id}>{condition.condition_id}</p>
              ))}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
```

- [ ] **Step 5: Implement settings, results, and trades components**

Create `frontend/src/components/BacktestSettings.tsx`:

```tsx
export function BacktestSettings() {
  return (
    <section className="surface">
      <h2>Backtest Settings</h2>
      <div className="settings-grid">
        <label>Initial capital<input defaultValue="100000" /></label>
        <label>Fixed holding days<input defaultValue="5" /></label>
        <label>Take profit<input defaultValue="8%" /></label>
        <label>Stop loss<input defaultValue="-5%" /></label>
        <label>Max holdings<input defaultValue="10" /></label>
        <label>Slippage<input defaultValue="0.05%" /></label>
      </div>
    </section>
  );
}
```

Create `frontend/src/components/ResultsOverview.tsx`:

```tsx
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { BacktestResult } from "../types";

type Props = {
  result: BacktestResult | null;
  onRun: () => void;
};

export function ResultsOverview({ result, onRun }: Props) {
  return (
    <section className="surface">
      <div className="section-title">
        <h2>Result Overview</h2>
        <button type="button" onClick={onRun}>Run Demo Backtest</button>
      </div>
      {result ? (
        <>
          <div className="metrics">
            <span>Total return {(result.metrics.total_return_pct * 100).toFixed(2)}%</span>
            <span>Max drawdown {(result.metrics.max_drawdown_pct * 100).toFixed(2)}%</span>
            <span>Win rate {(result.metrics.win_rate_pct * 100).toFixed(2)}%</span>
            <span>Trades {result.metrics.trade_count}</span>
          </div>
          <div className="chart">
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={result.equity_curve}>
                <XAxis dataKey="trade_date" />
                <YAxis />
                <Tooltip />
                <Line type="monotone" dataKey="equity" stroke="#1167b1" dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      ) : (
        <p>No result yet.</p>
      )}
    </section>
  );
}
```

Create `frontend/src/components/TradesTable.tsx`:

```tsx
import type { Trade } from "../types";

type Props = {
  trades: Trade[];
};

export function TradesTable({ trades }: Props) {
  return (
    <section className="surface">
      <h2>Trade Explanations</h2>
      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Buy</th>
            <th>Sell</th>
            <th>Reason</th>
            <th>PnL</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade) => (
            <tr key={`${trade.symbol}-${trade.buy_date}`}>
              <td>{trade.symbol}</td>
              <td>{trade.buy_date} @ {trade.buy_price}</td>
              <td>{trade.sell_date ?? "-"}</td>
              <td>{trade.buy_reason.join("; ")}</td>
              <td>{trade.pnl_pct == null ? "-" : `${(trade.pnl_pct * 100).toFixed(2)}%`}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
```

- [ ] **Step 6: Wire App**

Replace `frontend/src/App.tsx`:

```tsx
import { useEffect, useState } from "react";
import { loadCoverage, runDemoBacktest } from "./api";
import { BacktestSettings } from "./components/BacktestSettings";
import { DataCenter } from "./components/DataCenter";
import { ResultsOverview } from "./components/ResultsOverview";
import { StrategyEditor } from "./components/StrategyEditor";
import { TradesTable } from "./components/TradesTable";
import { defaultStrategy } from "./strategyDefaults";
import type { BacktestResult, DatasetCoverage } from "./types";

export function App() {
  const [coverage, setCoverage] = useState<DatasetCoverage[]>([]);
  const [result, setResult] = useState<BacktestResult | null>(null);

  const refreshCoverage = async () => {
    setCoverage(await loadCoverage(".astock-cache"));
  };

  const runBacktest = async () => {
    setResult(await runDemoBacktest());
  };

  useEffect(() => {
    void refreshCoverage();
  }, []);

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>A-Stock Backtester</h1>
          <p>Daily historical strategy research for A-share data.</p>
        </div>
        <strong>Conservative daily backtest</strong>
      </header>
      <div className="workspace">
        <DataCenter coverage={coverage} onRefresh={refreshCoverage} />
        <StrategyEditor strategy={defaultStrategy} />
        <BacktestSettings />
        <ResultsOverview result={result} onRun={runBacktest} />
        <TradesTable trades={result?.trades ?? []} />
      </div>
    </main>
  );
}
```

- [ ] **Step 7: Expand CSS**

Append to `frontend/src/styles.css`:

```css
.workspace {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
  padding: 20px;
}

.surface {
  background: #ffffff;
  border: 1px solid #d9dee7;
  border-radius: 8px;
  padding: 16px;
}

.section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

button {
  border: 1px solid #b8c2d1;
  background: #ffffff;
  border-radius: 6px;
  padding: 8px 12px;
  cursor: pointer;
}

table {
  width: 100%;
  border-collapse: collapse;
}

th,
td {
  text-align: left;
  border-bottom: 1px solid #e2e6ed;
  padding: 10px;
  vertical-align: top;
}

.strategy-grid {
  display: grid;
  grid-template-columns: minmax(260px, 360px) minmax(0, 1fr);
  gap: 20px;
}

.condition-list {
  list-style: none;
  padding: 0;
  margin: 12px 0 0;
}

.condition-list li {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid #e2e6ed;
  padding: 10px 0;
}

.condition-list small {
  color: #667385;
}

.group {
  border: 1px solid #d9dee7;
  border-radius: 8px;
  padding: 12px;
}

.settings-grid,
.metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
}

label {
  display: grid;
  gap: 6px;
  color: #4b5664;
}

input {
  border: 1px solid #b8c2d1;
  border-radius: 6px;
  padding: 8px;
}

.chart {
  margin-top: 12px;
}
```

- [ ] **Step 8: Run frontend tests and build**

Run:

```powershell
npm run test:ui -- --run
npm run build
```

Expected: UI tests pass and Vite build exits with code 0.

- [ ] **Step 9: Commit Task 8**

```powershell
git add frontend
git commit -m "feat: add backtester work areas"
```

## Task 9: Tauri Shell And Python Bridge

**Files:**
- Create: `src-tauri/Cargo.toml`
- Create: `src-tauri/tauri.conf.json`
- Create: `src-tauri/src/lib.rs`
- Create: `src-tauri/src/commands.rs`

- [ ] **Step 1: Create Tauri config**

Create `src-tauri/Cargo.toml`:

```toml
[package]
name = "a-stock-backtester"
version = "0.1.0"
description = "A-share historical backtester"
edition = "2021"

[lib]
name = "a_stock_backtester_lib"
crate-type = ["staticlib", "cdylib", "rlib"]

[build-dependencies]
tauri-build = { version = "2", features = [] }

[dependencies]
serde = { version = "1", features = ["derive"] }
serde_json = "1"
tauri = { version = "2", features = [] }
```

Create `src-tauri/tauri.conf.json`:

```json
{
  "$schema": "https://schema.tauri.app/config/2",
  "productName": "A-Stock Backtester",
  "version": "0.1.0",
  "identifier": "local.astock.backtester",
  "build": {
    "beforeDevCommand": "npm run dev",
    "devUrl": "http://127.0.0.1:1420",
    "beforeBuildCommand": "npm run build",
    "frontendDist": "../dist"
  },
  "app": {
    "windows": [
      {
        "title": "A-Stock Backtester",
        "width": 1280,
        "height": 860,
        "minWidth": 960,
        "minHeight": 700
      }
    ]
  },
  "bundle": {
    "active": true,
    "targets": ["nsis"],
    "resources": []
  }
}
```

- [ ] **Step 2: Implement Rust command bridge**

Create `src-tauri/src/commands.rs`:

```rust
use serde_json::Value;
use std::io::Write;
use std::process::{Command, Stdio};

#[tauri::command]
pub fn backend_command(payload: Value) -> Result<Value, String> {
    let mut child = Command::new("python")
        .args(["-m", "astock_backtester.cli"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|err| format!("failed to start backend: {err}"))?;

    {
        let stdin = child.stdin.as_mut().ok_or("backend stdin unavailable")?;
        stdin
            .write_all(payload.to_string().as_bytes())
            .map_err(|err| format!("failed to write backend stdin: {err}"))?;
    }

    let output = child
        .wait_with_output()
        .map_err(|err| format!("failed to read backend output: {err}"))?;

    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).to_string());
    }

    serde_json::from_slice(&output.stdout).map_err(|err| format!("invalid backend json: {err}"))
}
```

Create `src-tauri/src/lib.rs`:

```rust
mod commands;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![commands::backend_command])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

Create `src-tauri/build.rs`:

```rust
fn main() {
    tauri_build::build()
}
```

- [ ] **Step 3: Install Tauri CLI**

Run:

```powershell
npm install --save-dev @tauri-apps/cli@^2.0.0
```

Expected: `package-lock.json` updates and command exits with code 0.

- [ ] **Step 4: Verify frontend and Rust compile path**

Run:

```powershell
npm run build
npm run tauri -- build --debug
```

Expected: Vite build succeeds; Tauri debug build succeeds or reports a clear missing local toolchain such as Rust/MSVC not installed.

- [ ] **Step 5: Commit Task 9**

```powershell
git add package.json package-lock.json src-tauri
git commit -m "feat: add tauri desktop shell"
```

## Task 10: `a-stock-data` Adapter Boundary

**Files:**
- Create: `backend/astock_backtester/data/astock_adapter.py`
- Create: `tests/test_astock_adapter.py`
- Modify: `backend/astock_backtester/cli.py`

- [ ] **Step 1: Write failing adapter tests**

Create `tests/test_astock_adapter.py`:

```python
import pandas as pd

from astock_backtester.data.astock_adapter import AStockDataAdapter, AStockDataUnavailable


def test_adapter_reports_unconfigured_fetcher():
    adapter = AStockDataAdapter(fetcher=None)

    try:
        adapter.fetch_daily_bars(["AAA"], "2024-01-02", "2024-01-08")
    except AStockDataUnavailable as exc:
        assert "a-stock-data fetcher is not configured" in str(exc)
    else:
        raise AssertionError("expected AStockDataUnavailable")


def test_adapter_normalizes_fetcher_output():
    def fake_fetcher(symbols, start_date, end_date):
        return pd.DataFrame(
            {
                "symbol": ["AAA"],
                "date": ["2024-01-02"],
                "open": [10.0],
                "high": [11.0],
                "low": [9.8],
                "close": [10.5],
                "volume": [1000],
                "float_market_cap": [8_000_000_000],
                "main_net_inflow": [2_000_000],
            }
        )

    adapter = AStockDataAdapter(fetcher=fake_fetcher)
    result = adapter.fetch_daily_bars(["AAA"], "2024-01-02", "2024-01-08")

    assert result.loc[0, "symbol"] == "AAA"
    assert result.loc[0, "main_net_inflow"] == 2_000_000
```

- [ ] **Step 2: Run adapter tests to verify failure**

Run:

```powershell
python -m pytest tests/test_astock_adapter.py -q
```

Expected: fail with missing `astock_adapter`.

- [ ] **Step 3: Implement adapter boundary**

Create `backend/astock_backtester/data/astock_adapter.py`:

```python
from __future__ import annotations

from collections.abc import Callable, Sequence

import pandas as pd

from astock_backtester.data.importer import normalize_daily_bars


class AStockDataUnavailable(RuntimeError):
    pass


DailyBarsFetcher = Callable[[Sequence[str], str, str], pd.DataFrame]


class AStockDataAdapter:
    def __init__(self, fetcher: DailyBarsFetcher | None = None) -> None:
        self.fetcher = fetcher

    def fetch_daily_bars(self, symbols: Sequence[str], start_date: str, end_date: str) -> pd.DataFrame:
        if self.fetcher is None:
            raise AStockDataUnavailable(
                "a-stock-data fetcher is not configured. Configure a fetcher that returns daily OHLCV, "
                "market cap, turnover, and capital-flow columns."
            )
        return normalize_daily_bars(self.fetcher(symbols, start_date, end_date))
```

- [ ] **Step 4: Add CLI command for explicit unavailable state**

Add this branch in `handle_command` before `demo_backtest`:

```python
        if command == "fetch_status":
            return {
                "ok": True,
                "status": {
                    "configured": False,
                    "message": "a-stock-data adapter boundary is present; configure fetcher functions before live fetching.",
                },
            }
```

Add this test to `tests/test_astock_adapter.py`:

```python
from astock_backtester.cli import handle_command


def test_fetch_status_is_explicit():
    response = handle_command({"command": "fetch_status"})

    assert response["ok"] is True
    assert response["status"]["configured"] is False
```

- [ ] **Step 5: Run adapter tests**

Run:

```powershell
python -m pytest tests/test_astock_adapter.py -q
```

Expected: `3 passed`.

- [ ] **Step 6: Commit Task 10**

```powershell
git add backend/astock_backtester/data/astock_adapter.py backend/astock_backtester/cli.py tests/test_astock_adapter.py
git commit -m "feat: add astock data adapter boundary"
```

## Task 11: Documentation And Verification

**Files:**
- Create: `docs/dev.md`
- Modify: `docs/superpowers/plans/2026-05-23-a-stock-backtester.md` only to mark executed checkboxes if this plan is being used as the task tracker.

- [ ] **Step 1: Create development documentation**

Create `docs/dev.md`:

```markdown
# Development

## Backend

Install editable backend dependencies:

```powershell
python -m pip install -e ".[dev]"
```

Run backend tests:

```powershell
python -m pytest tests -q
```

Smoke test backend JSON CLI:

```powershell
'{"command":"demo_backtest"}' | python -m astock_backtester.cli
```

## Frontend

Install JavaScript dependencies:

```powershell
npm install
```

Run UI tests:

```powershell
npm run test:ui -- --run
```

Run Vite build:

```powershell
npm run build
```

## Desktop

Run a Tauri debug build:

```powershell
npm run tauri -- build --debug
```

The Python backend must be importable in the environment that launches Tauri. During development, run:

```powershell
python -m pip install -e ".[dev]"
```

before starting the desktop app.
```

The Tauri bridge calls `python -m astock_backtester.cli`, so the backend package must be installed editable in the same Python environment used by the desktop process. Packaged sidecar bundling is a later hardening step after the development bridge is verified.

- [ ] **Step 2: Run full verification**

Run:

```powershell
python -m pytest tests -q
npm run test:ui -- --run
npm run build
```

Expected: backend tests pass, UI tests pass, Vite build succeeds.

- [ ] **Step 3: Run desktop verification**

Run:

```powershell
npm run tauri -- build --debug
```

Expected: debug desktop build succeeds. If the host lacks Rust or MSVC Build Tools, capture the exact missing-toolchain error in the final report and do not claim desktop packaging is verified.

- [ ] **Step 4: Commit documentation and final verification updates**

```powershell
git add docs/dev.md docs/superpowers/plans/2026-05-23-a-stock-backtester.md
git commit -m "docs: add development verification guide"
```

## Final Acceptance Criteria

- Backend tests cover models, indicators, conditions, cache/import, CLI, `a-stock-data` adapter boundary, and engine behavior.
- Engine uses signal-day-or-earlier data for entry decisions and buys on the next trading day open.
- Strategy conditions include market heat, market cap, and capital-flow options.
- Backtest result includes metrics, equity curve, trades, buy reasons, sell reasons, and preflight issues.
- UI shows Data Center, Strategy Editor, Backtest Settings, Result Overview, and Trade Explanations.
- Tauri command bridge can call the Python CLI in development.
- Full verification commands are run immediately before claiming completion.

## Known Implementation Constraints

- The first live `a-stock-data` fetcher is represented by an adapter boundary. It must be connected to concrete fetch functions only after the implementation agent inspects the installed `a-stock-data` skill or vendored code and verifies exact callable names.
- Daily volume ratio is implemented as a daily-bar proxy, not real-time intraday volume ratio.
- Conservative same-day take-profit and stop-loss ambiguity uses the worse outcome until minute-level data is added.
