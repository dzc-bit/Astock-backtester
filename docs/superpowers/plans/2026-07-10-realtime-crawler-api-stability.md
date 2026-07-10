# Realtime Crawler and API Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make realtime information acquisition and long-running local APIs resilient to transient upstream failures, exhausted time budgets, stalled streams, and client disconnects.

**Architecture:** Keep source-specific parsing in `realtime.py`, add one bounded transport helper for retry and TLS-fingerprint fallback, and make provider orchestration cooperatively deadline-aware. Consolidate frontend NDJSON lifecycle handling and make the service treat disconnected clients as normal termination.

**Tech Stack:** Python 3.11, requests, curl_cffi, React 18, TypeScript, Fetch streams, Vitest, pytest, Tauri 2.

---

### Task 1: Release Version Consistency

**Files:**
- Modify: `pyproject.toml`
- Modify: `tests/test_build_scripts.py`

- [ ] Add a test that loads the Python, npm, Cargo, and Tauri versions and expects one value.
- [ ] Run the test and confirm it fails with Python `1.3.1` versus desktop `1.3.3`.
- [ ] Change the Python package version to `1.3.3`.
- [ ] Run the focused test and confirm it passes.

### Task 2: Bounded Public HTTP Transport

**Files:**
- Create: `backend/astock_backtester/data/http_transport.py`
- Modify: `backend/astock_backtester/data/realtime.py`
- Modify: `backend/astock_backtester/data/news.py`
- Modify: `backend/astock_backtester/models.py`
- Create: `tests/test_http_transport.py`
- Create: `tests/test_news_provider.py`
- Modify: `tests/test_data_service_http.py`

- [ ] Add failing tests for one transient retry, no retry for terminal 4xx, production-only curl fallback, and remaining-budget timeout clamping.
- [ ] Run focused tests and confirm failures are caused by the missing transport helper.
- [ ] Implement the minimal transport helper and structured attempt diagnostics.
- [ ] Route Tonghuashun breadth and sector HTML requests through the helper.
- [ ] Add a failing provider test proving a cancelled/deadline-expired sector chain does not start the next source.
- [ ] Add request-scoped cancellation checks between breadth and sector sources.
- [ ] Route the existing Eastmoney/CLS news sources through the bounded transport, expose diagnostics, and stop the chain after a 12-second total budget.
- [ ] Run transport and realtime provider tests.

### Task 3: NDJSON Client Lifecycle

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/api.stream.test.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/__tests__/strategyEditor.test.tsx`

- [ ] Add failing tests for idle timeout and external abort on both stream APIs.
- [ ] Implement a shared NDJSON response reader with resettable idle timeout and signal forwarding.
- [ ] Pass an AbortSignal from the realtime refresh effect and abort it during cleanup.
- [ ] Run stream and application tests.

### Task 4: Service Disconnect Handling

**Files:**
- Modify: `backend/astock_backtester/service.py`
- Modify: `tests/test_data_service_http.py`

- [ ] Add a failing handler test where `_write_ndjson` raises `BrokenPipeError`.
- [ ] Implement a dedicated client-disconnect predicate and stop stream production without secondary writes.
- [ ] Run the service HTTP tests.

### Task 5: Initial Bundle Split

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/__tests__/strategyEditor.test.tsx`

- [ ] Add or update a UI test that observes a result loading fallback before the lazy component resolves.
- [ ] Convert `ResultsOverview` to a lazy import with a compact fallback.
- [ ] Run UI tests and production build.
- [ ] Confirm the initial JS chunk no longer includes the Recharts result module.

### Task 6: Full Verification

**Files:**
- Verify only.

- [ ] Run `python -m pytest tests -q`.
- [ ] Run `npm run test:ui -- --run` with the bundled Node directory on PATH.
- [ ] Run `npm run typecheck` and `npm run build`.
- [ ] Run `cargo test --manifest-path src-tauri/Cargo.toml` with the project Rust environment.
- [ ] Run `git diff --check` and inspect the final worktree.

### Task 7: News Acquisition Fan-Out and Reuse

**Files:**
- Modify: `backend/astock_backtester/data/news.py`
- Modify: `backend/astock_backtester/data/news_summary.py`
- Modify: `tests/test_news_provider.py`
- Modify: `tests/test_news_summary.py`

- [ ] Add a failing test proving a blocked Eastmoney source cannot prevent a healthy 7x24 feed from completing within the total budget.
- [ ] Add failing tests proving overlapping news and summary calls share one refresh and a failed refresh returns a bounded, explicitly labeled recent-success result.
- [ ] Add a failing test for an Eastmoney link whose `title` attribute appears before `href`.
- [ ] Run the focused tests and confirm each failure represents the missing behavior.
- [ ] Run independent sources concurrently, serialize provider refreshes, cache complete responses briefly, and retain only successful responses for stale fallback.
- [ ] Parse rolling links with BeautifulSoup and propagate source diagnostics into news summaries.
- [ ] Run the focused news tests and confirm they pass.

### Task 8: Complete JSON API Lifecycle

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/api.timeout.test.ts`
- Modify: `backend/astock_backtester/service.py`
- Modify: `tests/test_data_service_http.py`

- [ ] Add a failing frontend test where response headers arrive but JSON body decoding stalls until the request timeout.
- [ ] Keep the timeout armed through `response.json()` and map an abort during body decoding to the existing timeout error.
- [ ] Add a failing service test where a normal JSON response write raises `BrokenPipeError`.
- [ ] Treat JSON client disconnects as normal completion at the write boundary.
- [ ] Run focused frontend and service tests.

### Task 9: Second-Pass Full Verification

**Files:**
- Verify only.

- [ ] Run all Python and frontend tests.
- [ ] Run TypeScript typecheck, production build, focused Ruff, and Rust tests.
- [ ] Run `git diff --check` and inspect all tracked and untracked changes.

### Task 10: Live-Source and Review Corrections

**Files:**
- Modify: `backend/astock_backtester/data/news.py`
- Modify: `backend/astock_backtester/data/realtime.py`
- Modify: `backend/astock_backtester/service.py`
- Modify: `tests/test_news_provider.py`
- Modify: `tests/test_realtime_transport.py`
- Modify: `tests/test_data_service_http.py`

- [ ] Replace the retired CLS endpoint with the verified public Eastmoney 7x24 feed and test its structured payload.
- [ ] Add an adversarial interleaving test between cancellation validation and sector-row publication.
- [ ] Commit worker rows only from an accepted in-budget future and remove request-scoped provider fields.
- [ ] Add tests distinguishing client socket disconnects from upstream connection resets.
- [ ] Translate socket disconnects only at the HTTP I/O boundary.
- [ ] Add a clock-controlled test proving short cache reuse cannot extend the recent-success TTL.
- [ ] Re-run focused and full verification plus packaged sidecar live probes.
