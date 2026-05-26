# Data Import Diagnostics Design

## Goal

Make Data Center use the same localhost data service for health, coverage, fetch/import results, and backtest execution so data imported through the service is visible and usable immediately.

## Root Cause Summary

Direct service calls can fetch `600519` daily bars and the running desktop sidecar already reports cached data through `/health`. The UI still depends on a separate Python CLI path for top-level coverage and backtest execution, which can diverge from the sidecar cache in the packaged desktop app. The coverage endpoint also ignores requested symbols/date ranges and reports weekend dates as missing.

## Design

- Service coverage accepts selected symbols and date range, filters cached rows to that selection, and treats weekdays as expected trading days instead of all calendar days.
- Data Center loads `/health` after `ensure_data_service`, uses the returned service coverage as the displayed coverage, and sends that coverage to the parent app state.
- Fetch/import actions update coverage from the service result instead of asking the parent to reload through the CLI.
- Recent service logs are loaded and shown in Data Center so failed fetches expose the real server-side message.
- Backtest execution can run through the same localhost service and cache path using a new `/run/backtest` endpoint, with the existing CLI kept as a fallback.

## Out Of Scope For This Pass

The full strategy-condition editor is not included here. This pass focuses on making imported data visible, diagnosable, and usable for backtests.
