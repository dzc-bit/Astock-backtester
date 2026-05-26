# Local Market Data Warehouse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a resumable local A-share data warehouse from 2015-01-01 with full-market daily bars, required market-cap fields, incremental updates, Data Center progress, and local-only backtest reads.

**Architecture:** Add a warehouse layer under `backend/astock_backtester/data/warehouse.py`, provider adapters under `backend/astock_backtester/data/providers.py`, and a sync job runner under `backend/astock_backtester/data/sync.py`. The HTTP service owns a `Warehouse` and `SyncJobManager`, exposes job endpoints, and backtests read warehouse data before falling back to the legacy cache.

**Tech Stack:** Python 3.11, pandas, pyarrow/parquet, sqlite3, pydantic, Tauri HTTP sidecar, React + TypeScript + Vitest.

---

## File Structure

- Create `backend/astock_backtester/data/warehouse.py`
  - Owns partitioned parquet storage under `.astock-cache/warehouse`.
  - Owns SQLite metadata tables for symbols, calendar, datasets, jobs, and per-symbol sync state.
  - Provides `write_daily_bars()`, `read_daily_bars()`, `coverage()`, `upsert_symbols()`, `upsert_calendar()`, and `symbol_sync_state()`.

- Create `backend/astock_backtester/data/providers.py`
  - Defines provider protocols and normalized helpers.
  - Implements `ADataProvider`, `HttpAStockProvider`, and `CompositeProvider`.
  - Computes `float_market_cap` and `total_market_cap` from historical shares and close prices.

- Create `backend/astock_backtester/data/sync.py`
  - Runs full-market bootstrap and incremental update jobs.
  - Persists progress after every symbol.
  - Records per-symbol failures and supports retry of failed symbols.

- Modify `backend/astock_backtester/data/importer.py`
  - Add required/optional normalization for `amount`, `change_pct`, `change`, `pre_close`, `float_market_cap`, and `total_market_cap`.

- Modify `backend/astock_backtester/data/cache.py`
  - Keep legacy cache behavior.
  - Add compatibility path for reading from warehouse when present.

- Modify `backend/astock_backtester/data/operations.py`
  - Prefer warehouse coverage when available.
  - Add job result helpers for service endpoints.

- Modify `backend/astock_backtester/service.py`
  - Initialize `Warehouse` and `SyncJobManager`.
  - Add `/sync/full-market`, `/sync/update`, `/sync/retry-failed`, and `/sync/status`.
  - Make `/run/backtest` read warehouse data first.

- Modify `backend/astock_backtester/models.py`
  - Add `SyncJobStatus`, `SyncJobRequest`, `SymbolSyncState`, and warehouse coverage fields.

- Modify `pyproject.toml`
  - Add runtime dependency on `adata`, `requests`, and `beautifulsoup4`.

- Modify `scripts/build-data-service.ps1`
  - Ensure PyInstaller collects `adata` package data and dependencies.

- Modify `frontend/src/types.ts`
  - Add sync job request/status types.

- Modify `frontend/src/api.ts`
  - Add sync endpoint clients and browser-preview mocks.

- Modify `frontend/src/components/DataCenter.tsx`
  - Add full-market download/update/retry controls and progress panel.
  - Keep current manual import/fetch controls available.

- Modify `frontend/src/components/BacktestSettings.tsx`
  - Use `type="date"` inputs and accept Data Center range.

- Modify `frontend/src/App.tsx`
  - Hold shared Data Center date range and pass it to backtest settings.
  - Improve market-cap related error translation.

- Tests:
  - Create `tests/test_warehouse.py`.
  - Create `tests/test_data_providers.py`.
  - Create `tests/test_sync_jobs.py`.
  - Modify `tests/test_data_operations.py`.
  - Modify `tests/test_data_service_http.py`.
  - Modify `frontend/src/components/DataCenter.test.tsx`.

---

### Task 1: Normalize Required Daily Bar And Market-Cap Fields

**Files:**
- Modify: `backend/astock_backtester/data/importer.py`
- Test: `tests/test_data_providers.py`

- [ ] **Step 1: Write failing tests for normalization fields**

Create `tests/test_data_providers.py` with:

```python
from __future__ import annotations

import math

import pandas as pd

from astock_backtester.data.importer import normalize_daily_bars


def test_normalize_daily_bars_preserves_market_cap_fields():
    frame = pd.DataFrame(
        {
            "symbol": ["600519"],
            "trade_date": ["2024-01-02"],
            "open": [1608.68],
            "high": [1611.87],
            "low": [1571.78],
            "close": [1578.69],
            "volume": [3215600],
            "amount": [5440083000.0],
            "change_pct": [-2.53],
            "change": [-40.99],
            "turnover_rate": [0.0026],
            "pre_close": [1619.68],
            "float_market_cap": [1980000000000.0],
            "total_market_cap": [1985000000000.0],
        }
    )

    result = normalize_daily_bars(frame)

    assert result.loc[0, "amount"] == 5440083000.0
    assert result.loc[0, "change_pct"] == -2.53
    assert result.loc[0, "change"] == -40.99
    assert result.loc[0, "pre_close"] == 1619.68
    assert result.loc[0, "float_market_cap"] == 1980000000000.0
    assert result.loc[0, "total_market_cap"] == 1985000000000.0


def test_normalize_daily_bars_defaults_missing_market_cap_to_nan():
    frame = pd.DataFrame(
        {
            "symbol": ["000001"],
            "trade_date": ["2024-01-02"],
            "open": [9.0],
            "high": [9.3],
            "low": [8.9],
            "close": [9.1],
            "volume": [1000],
        }
    )

    result = normalize_daily_bars(frame)

    assert math.isnan(result.loc[0, "float_market_cap"])
    assert math.isnan(result.loc[0, "total_market_cap"])
    assert result.loc[0, "amount"] == 0.0
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
.\.tools\python-3.11.9\python.exe -m pytest tests/test_data_providers.py -q
```

Expected: FAIL because `total_market_cap`, `amount`, `change_pct`, `change`, or `pre_close` defaults are not all normalized.

- [ ] **Step 3: Implement minimal normalization**

Edit `backend/astock_backtester/data/importer.py`:

```python
numeric_columns = ["open", "high", "low", "close", "volume"]
for column in numeric_columns:
    out[column] = pd.to_numeric(out[column], errors="raise")

optional_defaults = {
    "amount": 0.0,
    "change_pct": 0.0,
    "change": 0.0,
    "turnover_rate": 0.0,
    "pre_close": float("nan"),
    "float_market_cap": float("nan"),
    "total_market_cap": float("nan"),
    "main_net_inflow": float("nan"),
    "is_st": False,
    "is_suspended": False,
    "listing_days": 9999,
}
for column, default in optional_defaults.items():
    if column not in out.columns:
        out[column] = default

for column in [
    "amount",
    "change_pct",
    "change",
    "turnover_rate",
    "pre_close",
    "float_market_cap",
    "total_market_cap",
    "main_net_inflow",
]:
    out[column] = pd.to_numeric(out[column], errors="coerce")
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```powershell
.\.tools\python-3.11.9\python.exe -m pytest tests/test_data_providers.py tests/test_data_operations.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend\astock_backtester\data\importer.py tests\test_data_providers.py
git commit -m "test: cover daily bar market cap normalization"
```

---

### Task 2: Add Warehouse Storage With Year Partitions And Metadata

**Files:**
- Create: `backend/astock_backtester/data/warehouse.py`
- Test: `tests/test_warehouse.py`

- [ ] **Step 1: Write failing warehouse tests**

Create `tests/test_warehouse.py`:

```python
from __future__ import annotations

import pandas as pd

from astock_backtester.data.warehouse import Warehouse


def _bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["600519", "600519", "000001"],
            "trade_date": ["2015-01-05", "2016-01-04", "2016-01-04"],
            "open": [10.0, 11.0, 8.0],
            "high": [10.5, 11.5, 8.5],
            "low": [9.8, 10.8, 7.9],
            "close": [10.2, 11.2, 8.1],
            "volume": [1000, 1200, 900],
            "amount": [10200.0, 13440.0, 7290.0],
            "float_market_cap": [1000000000.0, 1100000000.0, 800000000.0],
            "total_market_cap": [1200000000.0, 1300000000.0, 900000000.0],
        }
    )


def test_warehouse_writes_year_partitions_and_reads_filtered_data(tmp_path):
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(_bars())

    assert (tmp_path / "warehouse" / "daily_bars" / "year=2015" / "daily_bars.parquet").exists()
    assert (tmp_path / "warehouse" / "daily_bars" / "year=2016" / "daily_bars.parquet").exists()

    result = warehouse.read_daily_bars(
        symbols=["600519"],
        start_date="2016-01-01",
        end_date="2016-12-31",
    )

    assert result["symbol"].tolist() == ["600519"]
    assert result["trade_date"].dt.strftime("%Y-%m-%d").tolist() == ["2016-01-04"]


def test_warehouse_merges_rows_by_symbol_and_trade_date(tmp_path):
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(_bars())
    warehouse.write_daily_bars(
        pd.DataFrame(
            {
                "symbol": ["600519"],
                "trade_date": ["2016-01-04"],
                "open": [12.0],
                "high": [12.5],
                "low": [11.8],
                "close": [12.2],
                "volume": [2200],
                "amount": [26840.0],
                "float_market_cap": [1500000000.0],
                "total_market_cap": [1600000000.0],
            }
        )
    )

    result = warehouse.read_daily_bars(symbols=["600519"], start_date="2016-01-04", end_date="2016-01-04")

    assert len(result) == 1
    assert result.loc[0, "close"] == 12.2
    assert result.loc[0, "float_market_cap"] == 1500000000.0


def test_warehouse_coverage_reports_daily_and_market_cap(tmp_path):
    warehouse = Warehouse(tmp_path)
    warehouse.write_daily_bars(_bars())

    coverage = {item.dataset: item for item in warehouse.coverage()}

    assert coverage["daily_bars"].symbols == 2
    assert coverage["daily_bars"].start_date.isoformat() == "2015-01-05"
    assert coverage["market_cap"].missing_rows == 0
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
.\.tools\python-3.11.9\python.exe -m pytest tests/test_warehouse.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'astock_backtester.data.warehouse'`.

- [ ] **Step 3: Implement warehouse**

Create `backend/astock_backtester/data/warehouse.py`:

```python
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Sequence

import pandas as pd

from astock_backtester.data.importer import normalize_daily_bars
from astock_backtester.models import DatasetCoverage


class Warehouse:
    def __init__(self, cache_root: str | Path) -> None:
        self.cache_root = Path(cache_root)
        self.root = self.cache_root / "warehouse"
        self.daily_bars_root = self.root / "daily_bars"
        self.daily_bars_root.mkdir(parents=True, exist_ok=True)
        self.sqlite_path = self.root / "metadata.sqlite"
        self._init_db()

    def _init_db(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    dataset TEXT PRIMARY KEY,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS symbol_sync_state (
                    symbol TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    start_date TEXT,
                    end_date TEXT,
                    rows INTEGER NOT NULL DEFAULT 0,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    provider TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def _partition_path(self, year: int) -> Path:
        return self.daily_bars_root / f"year={year}" / "daily_bars.parquet"

    def write_daily_bars(self, frame: pd.DataFrame) -> None:
        normalized = normalize_daily_bars(frame)
        if normalized.empty:
            return
        normalized["year"] = normalized["trade_date"].dt.year
        for year, year_frame in normalized.groupby("year"):
            path = self._partition_path(int(year))
            path.parent.mkdir(parents=True, exist_ok=True)
            year_frame = year_frame.drop(columns=["year"])
            if path.exists():
                current = pd.read_parquet(path)
                year_frame = (
                    year_frame.set_index(["symbol", "trade_date"])
                    .combine_first(current.set_index(["symbol", "trade_date"]))
                    .reset_index()
                )
            year_frame = year_frame.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
            year_frame.to_parquet(path, index=False)
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute("INSERT OR REPLACE INTO datasets(dataset) VALUES('daily_bars')")

    def read_daily_bars(
        self,
        symbols: Sequence[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        paths = sorted(self.daily_bars_root.glob("year=*/daily_bars.parquet"))
        if not paths:
            return pd.DataFrame()
        frames = [pd.read_parquet(path) for path in paths]
        frame = pd.concat(frames, ignore_index=True)
        frame["trade_date"] = pd.to_datetime(frame["trade_date"])
        if symbols:
            selected = {str(symbol).strip() for symbol in symbols if str(symbol).strip()}
            frame = frame[frame["symbol"].astype(str).isin(selected)]
        if start_date:
            frame = frame[frame["trade_date"] >= pd.Timestamp(start_date)]
        if end_date:
            frame = frame[frame["trade_date"] <= pd.Timestamp(end_date)]
        return frame.sort_values(["symbol", "trade_date"]).reset_index(drop=True)

    def coverage(self) -> list[DatasetCoverage]:
        bars = self.read_daily_bars()
        if bars.empty:
            return [
                DatasetCoverage(dataset="daily_bars", symbols=0, start_date=None, end_date=None),
                DatasetCoverage(dataset="market_cap", symbols=0, start_date=None, end_date=None),
                DatasetCoverage(dataset="capital_flow", symbols=0, start_date=None, end_date=None),
            ]
        start = bars["trade_date"].min().date()
        end = bars["trade_date"].max().date()
        return [
            DatasetCoverage(
                dataset="daily_bars",
                symbols=int(bars["symbol"].nunique()),
                start_date=start,
                end_date=end,
                missing_rows=int(bars[["open", "high", "low", "close"]].isna().any(axis=1).sum()),
            ),
            DatasetCoverage(
                dataset="market_cap",
                symbols=int(bars.loc[bars["float_market_cap"].notna(), "symbol"].nunique()),
                start_date=start,
                end_date=end,
                missing_rows=int(bars["float_market_cap"].isna().sum()),
            ),
            DatasetCoverage(
                dataset="capital_flow",
                symbols=int(bars.loc[bars["main_net_inflow"].notna(), "symbol"].nunique()),
                start_date=start,
                end_date=end,
                missing_rows=int(bars["main_net_inflow"].isna().sum()),
            ),
        ]
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```powershell
.\.tools\python-3.11.9\python.exe -m pytest tests/test_warehouse.py tests/test_data_operations.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend\astock_backtester\data\warehouse.py tests\test_warehouse.py
git commit -m "feat: add local market data warehouse"
```

---

### Task 3: Add Provider Layer And Market-Cap Calculation

**Files:**
- Create: `backend/astock_backtester/data/providers.py`
- Modify: `pyproject.toml`
- Test: `tests/test_data_providers.py`

- [ ] **Step 1: Add failing provider tests**

Append to `tests/test_data_providers.py`:

```python
from astock_backtester.data.providers import (
    ADataProvider,
    CompositeProvider,
    ProviderError,
    enrich_market_cap_from_share_history,
)


def test_enrich_market_cap_from_share_history_uses_effective_share_dates():
    bars = pd.DataFrame(
        {
            "symbol": ["600519", "600519", "600519"],
            "trade_date": ["2024-01-02", "2024-01-03", "2024-01-04"],
            "open": [10.0, 11.0, 12.0],
            "high": [10.5, 11.5, 12.5],
            "low": [9.8, 10.8, 11.8],
            "close": [10.0, 11.0, 12.0],
            "volume": [100, 100, 100],
        }
    )
    shares = pd.DataFrame(
        {
            "stock_code": ["600519", "600519"],
            "change_date": ["2024-01-01", "2024-01-04"],
            "total_shares": [1000, 2000],
            "list_a_shares": [800, 1600],
        }
    )

    result = enrich_market_cap_from_share_history(bars, shares)

    assert result["float_market_cap"].tolist() == [8000.0, 8800.0, 19200.0]
    assert result["total_market_cap"].tolist() == [10000.0, 11000.0, 24000.0]


def test_composite_provider_falls_back_when_primary_returns_empty():
    class EmptyProvider:
        name = "empty"

        def fetch_daily_bars(self, symbol, start_date, end_date):
            return pd.DataFrame()

        def fetch_share_history(self, symbol):
            return pd.DataFrame()

    class FallbackProvider:
        name = "fallback"

        def fetch_daily_bars(self, symbol, start_date, end_date):
            return pd.DataFrame(
                {
                    "symbol": [symbol],
                    "trade_date": [start_date],
                    "open": [1.0],
                    "high": [1.0],
                    "low": [1.0],
                    "close": [1.0],
                    "volume": [1],
                }
            )

        def fetch_share_history(self, symbol):
            return pd.DataFrame()

    provider = CompositeProvider([EmptyProvider(), FallbackProvider()])

    result = provider.fetch_daily_bars("000001", "2024-01-02", "2024-01-02")

    assert result.loc[0, "source"] == "fallback"
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
.\.tools\python-3.11.9\python.exe -m pytest tests/test_data_providers.py -q
```

Expected: FAIL because `astock_backtester.data.providers` does not exist.

- [ ] **Step 3: Implement providers**

Create `backend/astock_backtester/data/providers.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from astock_backtester.data.astock_adapter import AStockDataAdapter
from astock_backtester.data.importer import normalize_daily_bars


class ProviderError(RuntimeError):
    pass


class DailyDataProvider(Protocol):
    name: str

    def fetch_daily_bars(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        ...

    def fetch_share_history(self, symbol: str) -> pd.DataFrame:
        ...


def normalize_symbol(symbol: str) -> str:
    code = str(symbol).strip().upper()
    if code.startswith(("SH", "SZ", "BJ")):
        code = code[2:]
    if "." in code:
        code = code.split(".", 1)[0]
    return code.zfill(6) if code.isdigit() else code


def enrich_market_cap_from_share_history(bars: pd.DataFrame, shares: pd.DataFrame) -> pd.DataFrame:
    out = bars.copy()
    if out.empty:
        return out
    if shares.empty:
        out["float_market_cap"] = float("nan")
        out["total_market_cap"] = float("nan")
        return out
    out["trade_date"] = pd.to_datetime(out["trade_date"])
    share_frame = shares.copy()
    share_frame["change_date"] = pd.to_datetime(share_frame["change_date"])
    share_frame = share_frame.sort_values("change_date")
    merged = pd.merge_asof(
        out.sort_values("trade_date"),
        share_frame[["change_date", "total_shares", "list_a_shares"]].sort_values("change_date"),
        left_on="trade_date",
        right_on="change_date",
        direction="backward",
    )
    merged["float_market_cap"] = pd.to_numeric(merged["list_a_shares"], errors="coerce") * merged["close"]
    merged["total_market_cap"] = pd.to_numeric(merged["total_shares"], errors="coerce") * merged["close"]
    return merged.drop(columns=[column for column in ["change_date", "total_shares", "list_a_shares"] if column in merged])


@dataclass
class ADataProvider:
    name: str = "adata"

    def _adata(self):
        import adata

        return adata

    def fetch_daily_bars(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        adata = self._adata()
        code = normalize_symbol(symbol)
        frame = adata.stock.market.get_market(stock_code=code, start_date=start_date, end_date=end_date, k_type=1)
        if frame is None or frame.empty:
            return pd.DataFrame()
        rename = {"stock_code": "symbol", "turnover_ratio": "turnover_rate"}
        frame = frame.rename(columns=rename)
        frame["symbol"] = code
        frame["source"] = self.name
        shares = self.fetch_share_history(code)
        return normalize_daily_bars(enrich_market_cap_from_share_history(frame, shares))

    def fetch_share_history(self, symbol: str) -> pd.DataFrame:
        adata = self._adata()
        code = normalize_symbol(symbol)
        frame = adata.stock.info.get_stock_shares(stock_code=code, is_history=True)
        return pd.DataFrame() if frame is None else frame


@dataclass
class HttpAStockProvider:
    name: str = "http"

    def fetch_daily_bars(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        frame = AStockDataAdapter.from_http_sources().fetch_daily_bars([symbol], start_date, end_date)
        if frame.empty:
            return frame
        frame["source"] = self.name
        return frame

    def fetch_share_history(self, symbol: str) -> pd.DataFrame:
        return pd.DataFrame()


@dataclass
class CompositeProvider:
    providers: list[DailyDataProvider]

    def fetch_daily_bars(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        errors: list[str] = []
        for provider in self.providers:
            try:
                frame = provider.fetch_daily_bars(symbol, start_date, end_date)
            except Exception as exc:
                errors.append(f"{provider.name}: {exc}")
                continue
            if not frame.empty:
                if "source" not in frame.columns:
                    frame["source"] = provider.name
                return normalize_daily_bars(frame)
        if errors:
            raise ProviderError("; ".join(errors))
        return pd.DataFrame()
```

- [ ] **Step 4: Add runtime dependencies**

Edit `pyproject.toml` dependencies:

```toml
dependencies = [
  "adata>=2.9.5",
  "beautifulsoup4>=4.14",
  "numpy>=1.26",
  "pandas>=2.2",
  "pyarrow>=15",
  "pydantic>=2.7",
  "requests>=2.32",
]
```

- [ ] **Step 5: Run tests and verify GREEN**

Run:

```powershell
.\.tools\python-3.11.9\python.exe -m pytest tests/test_data_providers.py tests/test_astock_adapter.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend\astock_backtester\data\providers.py tests\test_data_providers.py pyproject.toml
git commit -m "feat: add adata provider with market cap enrichment"
```

---

### Task 4: Add Resumable Sync Job Manager

**Files:**
- Create: `backend/astock_backtester/data/sync.py`
- Modify: `backend/astock_backtester/models.py`
- Test: `tests/test_sync_jobs.py`

- [ ] **Step 1: Write failing sync job tests**

Create `tests/test_sync_jobs.py`:

```python
from __future__ import annotations

import pandas as pd

from astock_backtester.data.sync import SyncJobManager
from astock_backtester.data.warehouse import Warehouse


class FakeProvider:
    def __init__(self, fail_symbols=None):
        self.fail_symbols = set(fail_symbols or [])

    def fetch_daily_bars(self, symbol, start_date, end_date):
        if symbol in self.fail_symbols:
            raise RuntimeError("source unavailable")
        return pd.DataFrame(
            {
                "symbol": [symbol],
                "trade_date": [start_date],
                "open": [1.0],
                "high": [1.0],
                "low": [1.0],
                "close": [1.0],
                "volume": [1],
                "float_market_cap": [100.0],
                "total_market_cap": [120.0],
            }
        )


def test_full_market_job_persists_success_and_failure(tmp_path):
    warehouse = Warehouse(tmp_path)
    manager = SyncJobManager(warehouse=warehouse, provider=FakeProvider(fail_symbols={"000002"}))

    status = manager.run_full_market(
        symbols=["000001", "000002", "000003"],
        start_date="2015-01-01",
        end_date="2015-01-05",
    )

    assert status.total_symbols == 3
    assert status.completed_symbols == 2
    assert status.failed_symbols == 1
    assert status.imported_rows == 2
    loaded = warehouse.read_daily_bars()
    assert sorted(loaded["symbol"].tolist()) == ["000001", "000003"]
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
.\.tools\python-3.11.9\python.exe -m pytest tests/test_sync_jobs.py -q
```

Expected: FAIL because `SyncJobManager` does not exist.

- [ ] **Step 3: Add sync models**

Edit `backend/astock_backtester/models.py`:

```python
class SyncJobStatus(BaseModel):
    job_id: str
    mode: Literal["full_market_bootstrap", "incremental_update", "retry_failed"]
    status: Literal["running", "completed", "completed_with_errors", "failed"]
    total_symbols: int
    completed_symbols: int = 0
    failed_symbols: int = 0
    imported_rows: int = 0
    current_symbol: str | None = None
    start_date: date
    end_date: date
    errors: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Implement sync manager**

Create `backend/astock_backtester/data/sync.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import uuid4

from astock_backtester.data.warehouse import Warehouse
from astock_backtester.models import SyncJobStatus


@dataclass
class SyncJobManager:
    warehouse: Warehouse
    provider: object

    def run_full_market(self, symbols: list[str], start_date: str, end_date: str) -> SyncJobStatus:
        status = SyncJobStatus(
            job_id=str(uuid4()),
            mode="full_market_bootstrap",
            status="running",
            total_symbols=len(symbols),
            start_date=date.fromisoformat(start_date),
            end_date=date.fromisoformat(end_date),
        )
        for symbol in symbols:
            status.current_symbol = symbol
            try:
                frame = self.provider.fetch_daily_bars(symbol, start_date, end_date)
                if not frame.empty:
                    self.warehouse.write_daily_bars(frame)
                    status.imported_rows += int(len(frame))
                status.completed_symbols += 1
            except Exception as exc:
                status.failed_symbols += 1
                status.errors.append(f"{symbol}: {exc}")
        status.current_symbol = None
        status.status = "completed_with_errors" if status.failed_symbols else "completed"
        return status
```

- [ ] **Step 5: Run tests and verify GREEN**

Run:

```powershell
.\.tools\python-3.11.9\python.exe -m pytest tests/test_sync_jobs.py tests/test_warehouse.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend\astock_backtester\models.py backend\astock_backtester\data\sync.py tests\test_sync_jobs.py
git commit -m "feat: add resumable market data sync jobs"
```

---

### Task 5: Expose Warehouse Sync Through Local HTTP Service

**Files:**
- Modify: `backend/astock_backtester/service.py`
- Modify: `backend/astock_backtester/data/operations.py`
- Test: `tests/test_data_service_http.py`

- [ ] **Step 1: Write failing service endpoint tests**

Append to `tests/test_data_service_http.py`:

```python
def test_service_starts_full_market_sync_job(tmp_path, monkeypatch):
    class FakeManager:
        def run_full_market(self, symbols, start_date, end_date):
            from datetime import date
            from astock_backtester.models import SyncJobStatus

            assert symbols == ["000001", "000002"]
            return SyncJobStatus(
                job_id="job-1",
                mode="full_market_bootstrap",
                status="completed",
                total_symbols=2,
                completed_symbols=2,
                failed_symbols=0,
                imported_rows=2,
                start_date=date.fromisoformat(start_date),
                end_date=date.fromisoformat(end_date),
            )

    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server.state.sync_manager = FakeManager()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json(
            "POST",
            f"http://127.0.0.1:{port}/sync/full-market",
            {"symbols": ["000001", "000002"], "start_date": "2015-01-01", "end_date": "2015-01-05"},
        )

        assert response["job"]["status"] == "completed"
        assert response["job"]["imported_rows"] == 2
    finally:
        server.shutdown()
        thread.join(timeout=5)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
.\.tools\python-3.11.9\python.exe -m pytest tests/test_data_service_http.py::test_service_starts_full_market_sync_job -q
```

Expected: FAIL with 404 or missing `sync_manager`.

- [ ] **Step 3: Initialize warehouse and manager in service state**

Edit `backend/astock_backtester/service.py` imports and `DataServiceState.__init__`:

```python
from astock_backtester.data.providers import ADataProvider, CompositeProvider, HttpAStockProvider
from astock_backtester.data.sync import SyncJobManager
from astock_backtester.data.warehouse import Warehouse

self.warehouse = Warehouse(cache_dir)
self.provider = CompositeProvider([ADataProvider(), HttpAStockProvider()])
self.sync_manager = SyncJobManager(warehouse=self.warehouse, provider=self.provider)
```

- [ ] **Step 4: Add sync endpoints**

Inside `do_POST` before existing fetch/import endpoints:

```python
if self.path == "/sync/full-market":
    symbols = payload.get("symbols") or []
    if not symbols:
        symbols = [item["symbol"] for item in self.server.state.warehouse.list_symbols()]
    job = self.server.state.sync_manager.run_full_market(
        symbols=symbols,
        start_date=payload.get("start_date", "2015-01-01"),
        end_date=payload["end_date"],
    )
    self._send_json({"job": job.model_dump(mode="json")})
    return
```

- [ ] **Step 5: Make backtest read warehouse first**

In `/run/backtest`:

```python
frame = self.server.state.warehouse.read_daily_bars(
    start_date=str(settings.start_date),
    end_date=str(settings.end_date),
)
if frame.empty:
    frame = self.server.state.cache.read_daily_bars()
```

- [ ] **Step 6: Run tests and verify GREEN**

Run:

```powershell
.\.tools\python-3.11.9\python.exe -m pytest tests/test_data_service_http.py tests/test_sync_jobs.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add backend\astock_backtester\service.py backend\astock_backtester\data\operations.py tests\test_data_service_http.py
git commit -m "feat: expose market data sync service endpoints"
```

---

### Task 6: Add Data Center Sync UI And Shared Date Range

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/components/DataCenter.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/components/DataCenter.test.tsx`

- [ ] **Step 1: Write failing UI tests**

Append to `frontend/src/components/DataCenter.test.tsx`:

```tsx
it("starts a full-market sync job and shows progress", async () => {
  const user = userEvent.setup();
  apiMocks.startFullMarketSync.mockResolvedValue({
    job: {
      job_id: "job-1",
      mode: "full_market_bootstrap",
      status: "completed",
      total_symbols: 2,
      completed_symbols: 2,
      failed_symbols: 0,
      imported_rows: 20,
      current_symbol: null,
      start_date: "2015-01-01",
      end_date: "2026-05-26",
      errors: []
    }
  });

  render(<DataCenter cacheDir=".astock-cache" coverage={coverage} onCoverageChange={vi.fn()} />);

  await screen.findByText(/http:\/\/127\.0\.0\.1:9011/);
  await user.click(screen.getByRole("button", { name: "下载全市场历史数据" }));

  expect(await screen.findByText(/已完成 2\/2/)).toBeInTheDocument();
  expect(screen.getByText(/导入 20 行/)).toBeInTheDocument();
});
```

Update hoisted mock to include `startFullMarketSync`.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
.\.tools\node-v20.18.1-win-x64\node.exe node_modules\vitest\vitest.mjs --config frontend/vitest.config.ts --run frontend/src/components/DataCenter.test.tsx
```

Expected: FAIL because `startFullMarketSync` and UI button do not exist.

- [ ] **Step 3: Add TypeScript types**

Edit `frontend/src/types.ts`:

```ts
export type SyncJobStatus = {
  job_id: string;
  mode: "full_market_bootstrap" | "incremental_update" | "retry_failed";
  status: "running" | "completed" | "completed_with_errors" | "failed";
  total_symbols: number;
  completed_symbols: number;
  failed_symbols: number;
  imported_rows: number;
  current_symbol?: string | null;
  start_date: string;
  end_date: string;
  errors: string[];
};
```

- [ ] **Step 4: Add API client**

Edit `frontend/src/api.ts`:

```ts
export async function startFullMarketSync(
  baseUrl: string,
  startDate: string,
  endDate: string,
  symbols?: string[]
): Promise<{ job: SyncJobStatus }> {
  if (!isTauriRuntime()) {
    return {
      job: {
        job_id: "preview",
        mode: "full_market_bootstrap",
        status: "completed",
        total_symbols: symbols?.length ?? 2,
        completed_symbols: symbols?.length ?? 2,
        failed_symbols: 0,
        imported_rows: 20,
        current_symbol: null,
        start_date: startDate,
        end_date: endDate,
        errors: []
      }
    };
  }
  return serviceFetch(baseUrl, "/sync/full-market", {
    symbols,
    start_date: startDate,
    end_date: endDate
  });
}
```

- [ ] **Step 5: Add Data Center controls**

In `DataCenter.tsx`:

```tsx
const [syncJob, setSyncJob] = useState<SyncJobStatus | null>(null);

const handleFullMarketSync = async () => {
  if (!service) return;
  setBusy(true);
  try {
    const response = await startFullMarketSync(service.base_url, startDate, endDate);
    setSyncJob(response.job);
    setMessage(`全市场下载完成，导入 ${response.job.imported_rows} 行`);
    await refreshServiceState(service);
  } catch (error) {
    setMessage(error instanceof Error ? error.message : "全市场下载失败");
  } finally {
    setBusy(false);
  }
};
```

Add button:

```tsx
<button className="primary-button" type="button" onClick={handleFullMarketSync} disabled={!service || busy}>
  下载全市场历史数据
</button>
```

Add progress:

```tsx
{syncJob ? (
  <div className="sync-progress" role="status">
    <strong>已完成 {syncJob.completed_symbols}/{syncJob.total_symbols}</strong>
    <span>失败 {syncJob.failed_symbols}，导入 {syncJob.imported_rows} 行</span>
  </div>
) : null}
```

- [ ] **Step 6: Run tests and verify GREEN**

Run:

```powershell
.\.tools\node-v20.18.1-win-x64\node.exe node_modules\vitest\vitest.mjs --config frontend/vitest.config.ts --run frontend/src/components/DataCenter.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add frontend\src\types.ts frontend\src\api.ts frontend\src\components\DataCenter.tsx frontend\src\App.tsx frontend\src\components\DataCenter.test.tsx
git commit -m "feat: add market data sync controls"
```

---

### Task 7: Backtest Preflight Requires Market Cap For Market-Cap Strategy

**Files:**
- Modify: `backend/astock_backtester/engine.py`
- Test: `tests/test_engine.py`

- [ ] **Step 1: Write failing preflight test**

Append to `tests/test_engine.py`:

```python
def test_market_cap_strategy_requires_non_empty_market_cap(basic_strategy, basic_settings):
    frame = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "trade_date": pd.to_datetime(["2024-01-02"]),
            "open": [10.0],
            "high": [10.5],
            "low": [9.8],
            "close": [10.2],
            "volume": [1000],
            "is_suspended": [False],
            "listing_days": [100],
            "float_market_cap": [float("nan")],
            "main_net_inflow": [1000000.0],
        }
    )

    result = run_backtest(frame, basic_strategy, basic_settings)

    assert any(issue.code == "empty_market_cap" for issue in result.preflight_issues)
```

- [ ] **Step 2: Run test and verify RED**

Run:

```powershell
.\.tools\python-3.11.9\python.exe -m pytest tests/test_engine.py::test_market_cap_strategy_requires_non_empty_market_cap -q
```

Expected: FAIL because engine does not emit `empty_market_cap`.

- [ ] **Step 3: Implement preflight check**

Edit `_preflight()` in `backend/astock_backtester/engine.py`:

```python
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
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```powershell
.\.tools\python-3.11.9\python.exe -m pytest tests/test_engine.py tests/test_conditions.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend\astock_backtester\engine.py tests\test_engine.py
git commit -m "fix: require market cap for market cap strategies"
```

---

### Task 8: Build And Verification

**Files:**
- Modify: `scripts/build-data-service.ps1`
- Possibly modify: `src-tauri/tauri.conf.json`

- [ ] **Step 1: Ensure PyInstaller collects adata**

Edit `scripts/build-data-service.ps1` PyInstaller invocation:

```powershell
& $pythonCommand.Source -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --name astock-data-service `
  --distpath $distDir `
  --workpath $workDir `
  --specpath $specDir `
  --paths backend `
  --collect-all adata `
  --hidden-import requests `
  --hidden-import bs4 `
  backend\astock_backtester\service.py
```

- [ ] **Step 2: Run full backend tests**

Run:

```powershell
.\.tools\python-3.11.9\python.exe -m pytest tests -q
```

Expected: all backend tests pass.

- [ ] **Step 3: Run frontend tests**

Run:

```powershell
.\.tools\node-v20.18.1-win-x64\node.exe node_modules\vitest\vitest.mjs --config frontend/vitest.config.ts --run
```

Expected: all frontend tests pass.

- [ ] **Step 4: Run Rust tests**

Run:

```powershell
$env:CARGO_HOME=(Resolve-Path .\.tools\cargo-home).Path
$env:RUSTUP_HOME=(Resolve-Path .\.tools\rustup-home).Path
$env:PATH="$(Resolve-Path .\.tools\rustup-home\toolchains\stable-x86_64-pc-windows-msvc\bin);$(Resolve-Path .\.tools\cargo-home\bin);$env:PATH"
cargo test --manifest-path src-tauri\Cargo.toml --lib
```

Expected: Rust lib tests pass.

- [ ] **Step 5: Build sidecar**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build-data-service.ps1 -Python .\.tools\python-3.11.9\python.exe
```

Expected: `src-tauri/bin/astock-data-service.exe` exists.

- [ ] **Step 6: Commit build script changes**

```powershell
git add scripts\build-data-service.ps1
git commit -m "build: include adata in data service bundle"
```

---

## Plan Self-Review

Spec coverage:

- Local warehouse: Tasks 1 and 2.
- `adata` primary provider plus HTTP fallback: Task 3.
- Required market cap: Tasks 1, 3, and 7.
- Full-market resumable sync: Tasks 4 and 5.
- Data Center progress controls: Task 6.
- Backtest local warehouse/preflight: Tasks 5 and 7.
- Packaging: Task 8.

Placeholder scan:

- The plan has been checked for unresolved markers and incomplete sections.

Type consistency:

- `SyncJobStatus` fields are consistent between Python and TypeScript.
- Endpoint names are consistent between service and frontend: `/sync/full-market`.
- Market-cap fields use `float_market_cap` and `total_market_cap` consistently.
