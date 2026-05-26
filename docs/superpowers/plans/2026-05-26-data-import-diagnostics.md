# Data Import Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Data Center data acquisition visible, diagnosable, and connected to the same cache used by backtests.

**Architecture:** Keep the localhost sidecar as the source of truth for Data Center coverage and backtest execution. The CLI remains available for tests and fallback browser/dev behavior, but packaged desktop flows should use the sidecar base URL once available.

**Tech Stack:** Python 3.11 service/backend, pandas cache operations, React/Vitest frontend, Tauri sidecar manager.

---

### Task 1: Service Coverage Semantics

**Files:**
- Modify: `backend/astock_backtester/data/operations.py`
- Modify: `backend/astock_backtester/service.py`
- Test: `tests/test_data_operations.py`
- Test: `tests/test_data_service_http.py`

- [ ] Add failing tests proving `/coverage/daily-bars` honors requested symbols/date range and excludes weekends from missing dates.
- [ ] Update `build_daily_bars_coverage` to accept optional symbols/start/end filters.
- [ ] Update the service endpoint to pass POST payload values to coverage builder.
- [ ] Run backend tests and confirm the new behavior passes.

### Task 2: Localhost Backtest Endpoint

**Files:**
- Create: `backend/astock_backtester/backtest_runner.py`
- Modify: `backend/astock_backtester/cli.py`
- Modify: `backend/astock_backtester/service.py`
- Test: `tests/test_data_service_http.py`

- [ ] Add a failing HTTP test for running a backtest against cached data in the service.
- [ ] Extract shared backtest enrichment/run logic out of CLI.
- [ ] Add `POST /run/backtest` using the service cache.
- [ ] Run backend tests and confirm the endpoint returns metrics.

### Task 3: Frontend Uses Service As Source Of Truth

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/DataCenter.tsx`
- Test: `frontend/src/components/DataCenter.test.tsx`
- Test: `frontend/src/__tests__/strategyEditor.test.tsx`

- [ ] Add failing UI tests for service health coverage, recent logs, and service-backed backtest execution.
- [ ] Add API helpers for service health and logs.
- [ ] Update Data Center to display service coverage and logs.
- [ ] Update App to store service status and run backtests through the sidecar when available.
- [ ] Run UI tests and confirm they pass.

### Task 4: Verification And Desktop Replacement

**Files:**
- Modify build artifacts only after source verification.

- [ ] Run backend tests.
- [ ] Run frontend tests.
- [ ] Build sidecar.
- [ ] Build Tauri release.
- [ ] Replace desktop app files with the new release.
- [ ] Verify the desktop service health endpoint and version.
