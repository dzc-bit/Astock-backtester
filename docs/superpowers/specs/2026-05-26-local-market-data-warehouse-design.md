# 2015 Local Market Data Warehouse Design

## Goal

Build a local-first A-share historical data warehouse starting from 2015-01-01, then make the desktop app update that warehouse through public data interfaces and run backtests only against local data.

## Scope

This design covers the first complete data foundation for the backtesting app:

- Download full-market A-share daily bars from 2015-01-01 through the current date.
- Store the downloaded data locally in a format that supports incremental update and fast backtest reads.
- Use `1nchaos/adata` as the primary data provider.
- Keep the existing HTTP fetcher as a fallback provider for missing symbols or failed `adata` requests.
- Add Data Center workflows for full-market initial download, incremental update, progress visibility, and coverage checks.
- Make backtests read from the local warehouse instead of calling network providers during a run.

The user explicitly wants to start the full-market download directly. We will not gate the implementation on a small sample validation step, but the implementation must still be resumable and observable so failures do not lose progress.

## Current Problems

The current app has a working local service and cache, but it is still too thin for serious backtesting:

- The cache currently contains only a small number of rows unless manually fetched.
- The existing fetch path is symbol/date based and not designed for full-market historical bootstrapping.
- Backtest settings can point at dates that are not covered by the local cache.
- Strategy conditions exist in the engine, but the UI only exposes a small subset of parameter edits.
- Public data sources are unstable; `adata` can return daily bars and stock lists, but some optional datasets such as capital flow can be empty for a requested range.

## Data Architecture

The local data warehouse becomes the source of truth for backtesting.

### Core Datasets

`daily_bars` is required:

- `symbol`
- `trade_date`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `amount`
- `change_pct`
- `change`
- `turnover_rate`
- `pre_close`
- `source`
- `updated_at`

`stock_universe` is required:

- `symbol`
- `name`
- `exchange`
- `list_date`
- `is_active`
- `updated_at`

`trade_calendar` is required:

- `trade_date`
- `is_trade_day`
- `day_week`
- `source`
- `updated_at`

Enhanced datasets are optional in this phase:

- `capital_flow`
- `market_cap`
- `industry`
- `st_status`
- `suspension_status`

Daily bars, stock universe, and trade calendar must be enough to run a basic full-market backtest. Enhanced datasets can improve strategy filters, but missing enhanced data must not block a strategy that does not use those fields.

### Storage Format

Use Parquet partitioned by year for daily bars:

- `.astock-cache/warehouse/daily_bars/year=2015/*.parquet`
- `.astock-cache/warehouse/daily_bars/year=2016/*.parquet`
- continuing through the current year

Use SQLite for metadata and job state:

- `.astock-cache/warehouse/metadata.sqlite`

SQLite tables:

- `datasets`: dataset-level coverage and update timestamps.
- `symbols`: stock universe metadata.
- `calendar`: trading calendar metadata.
- `sync_jobs`: current and historical import/update jobs.
- `symbol_sync_state`: per-symbol date coverage, retry count, last error, and provider used.

The existing `LocalCache` can keep its current simple parquet path for compatibility, but the warehouse reader becomes the preferred source for service endpoints and backtest runs.

## Provider Architecture

Add a provider interface for data sources:

- `list_symbols()`
- `trade_calendar(year)`
- `fetch_daily_bars(symbol, start_date, end_date)`
- optional `fetch_capital_flow(symbol, start_date, end_date)`
- optional `fetch_market_cap(symbol, start_date, end_date)`

Implement providers:

- `ADataProvider`: primary provider using `adata`.
- `HttpAStockProvider`: fallback provider wrapping the current HTTP fetcher.
- `CompositeProvider`: tries `ADataProvider` first, then fallback when the primary returns empty data or raises a transient error.

The provider layer normalizes all provider output into the app's schema before storage. Provider-specific column names must not leak into the engine or UI.

## Full-Market Initial Download

The initial download starts from 2015-01-01 and targets all active A-share symbols from `adata.stock.info.all_code()`.

Workflow:

1. Refresh stock universe.
2. Refresh trade calendars from 2015 through the current year.
3. Create a `sync_jobs` row with mode `full_market_bootstrap`.
4. For each symbol, compute the requested start date as the later of 2015-01-01 and the symbol listing date.
5. Fetch daily bars for that symbol through the current date.
6. Normalize rows and write them immediately to the yearly parquet partitions.
7. Update `symbol_sync_state` after each symbol.
8. Continue on failures and record the error instead of aborting the whole job.

The user asked to start full-market directly, so the UI action should begin this job without requiring a separate sample run. The implementation should still make progress durable after every symbol.

## Incremental Updates

The Data Center gets an "update to latest" workflow.

For each active symbol:

1. Read the latest local `trade_date`.
2. If no data exists, start at the later of 2015-01-01 and list date.
3. If data exists, start from the next trading day after the latest local date.
4. Fetch only the missing range.
5. Append or merge rows into partitioned parquet.
6. Update coverage metadata.

The update should skip symbols that are already current through the latest known trading day.

## Data Center UI

Data Center should expose the data warehouse, not just service health.

Required controls:

- Date range, defaulting to 2015-01-01 through the current date.
- Stock universe selector: full market, manual symbols, or imported list.
- Primary action: `下载全市场历史数据`.
- Secondary action: `更新到最新`.
- Progress panel showing total symbols, completed symbols, failed symbols, imported rows, current symbol, elapsed time, and last errors.
- Coverage table showing daily bars coverage by date range and symbol count.
- A retry action for failed symbols.

The UI must make it clear that backtesting uses local data and that network providers are used only during data import/update.

## Backtest Integration

Backtests should read local data through the warehouse reader.

Before running:

- Validate that the selected date range is covered by `daily_bars`.
- Validate that selected symbols have daily bars in the requested range.
- Validate that strategy-required fields exist.
- If a strategy depends on optional data such as `main_net_inflow` and that data is missing, return a clear preflight issue instead of failing mid-run.

Backtest settings date inputs should use the same date-selection style as Data Center and should default to the Data Center selected range.

## Strategy Editor Integration

This data project does not need to finish the entire strategy builder, but it must stop treating conditions as cosmetic.

Required for this phase:

- Keep existing engine condition evaluation.
- Expose condition enable/disable.
- Expose editable parameters for conditions already present in the default strategy.
- Show when a condition requires optional data that is currently missing.

Full drag-and-drop condition composition can be a later phase.

## Error Handling

Public data interfaces can fail, return empty data, or rate limit.

The app should handle that by:

- Retrying transient provider failures with bounded retry count.
- Falling back from `adata` to the existing HTTP provider for daily bars.
- Recording per-symbol errors in `symbol_sync_state`.
- Continuing the full-market job when one symbol fails.
- Showing recent errors in Data Center.
- Allowing failed symbols to be retried later.

An empty response is not always a fatal error. For a delisted or newly listed stock outside the requested date range, it can be valid. For an active stock with expected trading dates, it should be recorded as a missing-data warning.

## File Size And Cleanup Policy

The app should keep source code and warehouse data separate:

- Source repository must not track downloaded market data.
- `.astock-cache/warehouse` remains local and ignored by Git.
- Build outputs such as `src-tauri/target`, `.pyinstaller`, `dist`, `release-assets`, and `src-tauri/bin` remain ignored.
- The desktop install may include a Python sidecar, but full-market historical data should be created in the app cache directory, not bundled into the installer.

This keeps GitHub updates small while allowing the local app to own a large data warehouse.

## Testing Strategy

Unit tests:

- Provider normalization from `adata` columns to app schema.
- Composite provider fallback behavior.
- Warehouse write/read/merge by year partition.
- Incremental date-range calculation.
- Coverage calculation using trading calendar.
- Backtest preflight for missing daily bars and optional fields.

Service tests:

- Start a sync job.
- Query job status.
- Retry failed symbols.
- Run backtest from warehouse data.

Frontend tests:

- Data Center shows full-market download and update actions.
- Progress panel renders job status.
- Backtest settings pick up Data Center date range.
- Missing optional strategy data is shown before running.

Manual verification:

- Start a full-market job from 2015-01-01.
- Confirm job persists progress after several symbols.
- Stop and restart service.
- Confirm the job can continue without losing completed symbols.
- Run a backtest using only local data.

## Delivery Plan

This should be implemented in phases that each produce a usable improvement:

1. Warehouse storage and provider layer.
2. Full-market bootstrap job with resumable state.
3. Data Center progress UI and retry controls.
4. Incremental update workflow.
5. Backtest reader and preflight integration.
6. Strategy parameter UI improvements for currently supported conditions.
7. Package desktop app, replace the desktop installation, and push the updated branch to GitHub.

The first operational milestone is successful full-market daily-bar import from 2015-01-01 into local storage, even if optional enhanced datasets are still incomplete.
