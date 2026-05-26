# Hybrid Data Service Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Windows desktop update that starts a localhost data service from the Tauri app, fills missing A-share historical data into the local cache, and publishes a signed updater release that the installed app can detect.

**Architecture:** Keep backtests cache-only. Add a Python HTTP service for cache coverage, fetch, import, and logs. Tauri owns service startup, port selection, and packaged sidecar resolution. The frontend Data Center talks to the localhost service after asking Tauri for the active port. Release packaging builds a Windows sidecar executable, bundles it as a Tauri resource, bumps the app version, and regenerates `latest.json`.

**Tech Stack:** Python 3.11, pandas, pydantic, stdlib `http.server`, PyInstaller, React, TypeScript, Vitest, Tauri 2, Rust stdlib process/networking, GitHub Releases, NSIS.

---

## References

- Product spec: `docs/superpowers/specs/2026-05-24-hybrid-data-service-release-design.md`
- Existing desktop/update docs: `docs/dev.md`, `docs/release.md`
- Existing backend entrypoint: `backend/astock_backtester/cli.py`
- Existing cache adapter: `backend/astock_backtester/data/cache.py`
- Existing fetch adapter: `backend/astock_backtester/data/astock_adapter.py`

## Scope Check

This is one vertical slice, not multiple unrelated projects. The service, Tauri bridge, Data Center UI, and release pipeline all serve the same user-visible feature: local-first data management with publishable updates. Keep it in one plan, but execute in this order:

1. Fix cache semantics so partial refreshes do not destroy existing data.
2. Expose those operations through a local Python HTTP service.
3. Make Tauri start/manage the service in development and packaged builds.
4. Wire the Data Center UI to the managed service.
5. Bump versions, build the sidecar, generate updater metadata, verify, and publish.

## File Structure

Modify or create these files:

- `backend/astock_backtester/models.py`: add service payload models and richer coverage shapes.
- `backend/astock_backtester/data/importer.py`: stop defaulting missing capital-flow data to zero.
- `backend/astock_backtester/data/cache.py`: merge incoming bars into cache and calculate per-dataset/per-symbol coverage.
- `backend/astock_backtester/data/operations.py`: shared pure functions for coverage, fetch, import, and service health.
- `backend/astock_backtester/service.py`: localhost HTTP service entrypoint and request handling.
- `tests/test_data_operations.py`: backend tests for merge semantics and coverage.
- `tests/test_data_service_http.py`: HTTP endpoint tests.
- `pyproject.toml`: add sidecar build dependency and keep Python version aligned.
- `.gitignore`: ignore sidecar build artifacts.
- `scripts/build-data-service.ps1`: build the Python sidecar executable into `src-tauri/bin`.
- `scripts/write-latest-json.ps1`: generate updater metadata from a concrete installer and signature.
- `package.json`: add sidecar/release helper scripts and bump the version.
- `src-tauri/Cargo.toml`: bump the version only if no new Rust crate is needed.
- `src-tauri/tauri.conf.json`: bundle the sidecar resource, bump version, and keep updater config.
- `src-tauri/src/python_runtime.rs`: resolve the Python runtime for development commands.
- `src-tauri/src/service_manager.rs`: start, track, and health-check the localhost data service.
- `src-tauri/src/commands.rs`: expose `ensure_data_service` and reuse shared Python resolution.
- `src-tauri/src/lib.rs`: register service manager state and Tauri commands.
- `frontend/src/types.ts`: add service status, coverage detail, fetch/import result types.
- `frontend/src/api.ts`: add Tauri command and localhost fetch helpers.
- `frontend/src/components/DataCenter.tsx`: show service state, symbol/date controls, import/fetch actions, and logs.
- `frontend/src/components/DataCenter.test.tsx`: focused UI tests for the new interactions.
- `frontend/src/App.tsx`: pass the cache directory into `DataCenter`.
- `frontend/src/styles.css`: style the service panel and action controls.
- `docs/dev.md`: document the sidecar build and verification commands.
- `docs/release.md`: document sidecar packaging, version bump, `latest.json`, and release upload.
- `README.md`: update installation notes to mention app-managed data refresh and in-app updates.
- `release-assets/latest.json`: replace the stale example with the new version after the real build.

## Task 1: Fix Cache Semantics And Add Shared Data Operations

**Files:**
- Modify: `backend/astock_backtester/models.py`
- Modify: `backend/astock_backtester/data/importer.py`
- Modify: `backend/astock_backtester/data/cache.py`
- Create: `backend/astock_backtester/data/operations.py`
- Create: `tests/test_data_operations.py`

- [ ] **Step 1: Write failing backend tests for merge semantics and coverage details**

Create `tests/test_data_operations.py`:

```python
import pandas as pd

from astock_backtester.data.cache import LocalCache
from astock_backtester.data.operations import (
    build_daily_bars_coverage,
    fetch_and_cache_daily_bars,
    health_payload,
)


def _bars(rows):
    return pd.DataFrame(rows)


def test_cache_merge_preserves_existing_optional_values(tmp_path):
    cache = LocalCache(tmp_path)
    cache.write_daily_bars(
        _bars(
            [
                {
                    "symbol": "600519",
                    "trade_date": "2024-01-02",
                    "open": 10,
                    "high": 11,
                    "low": 9.8,
                    "close": 10.5,
                    "volume": 1000,
                    "float_market_cap": 8_800_000_000,
                    "main_net_inflow": 2_000_000,
                }
            ]
        )
    )

    cache.write_daily_bars(
        _bars(
            [
                {
                    "symbol": "600519",
                    "trade_date": "2024-01-02",
                    "open": 10,
                    "high": 11.2,
                    "low": 9.7,
                    "close": 10.8,
                    "volume": 1500,
                    "main_net_inflow": float("nan"),
                }
            ]
        )
    )

    row = cache.read_daily_bars().iloc[0]
    assert row["close"] == 10.8
    assert row["high"] == 11.2
    assert row["float_market_cap"] == 8_800_000_000
    assert row["main_net_inflow"] == 2_000_000


def test_importer_keeps_missing_capital_flow_as_missing_value():
    cache = LocalCache(".astock-cache-test-ignore")
    frame = _bars(
        [
            {
                "symbol": "600519",
                "trade_date": "2024-01-02",
                "open": 10,
                "high": 11,
                "low": 9.8,
                "close": 10.5,
                "volume": 1000,
            }
        ]
    )
    normalized = cache.read_daily_bars() if False else frame
    from astock_backtester.data.importer import normalize_daily_bars

    result = normalize_daily_bars(normalized)
    assert pd.isna(result.loc[0, "main_net_inflow"])


def test_build_daily_bars_coverage_reports_missing_ranges_and_optional_fields(tmp_path):
    cache = LocalCache(tmp_path)
    cache.write_daily_bars(
        _bars(
            [
                {
                    "symbol": "600519",
                    "trade_date": "2024-01-02",
                    "open": 10,
                    "high": 11,
                    "low": 9.8,
                    "close": 10.5,
                    "volume": 1000,
                    "float_market_cap": 8_800_000_000,
                    "main_net_inflow": float("nan"),
                },
                {
                    "symbol": "600519",
                    "trade_date": "2024-01-03",
                    "open": 10.5,
                    "high": 11.4,
                    "low": 10.2,
                    "close": 11.1,
                    "volume": 1200,
                    "float_market_cap": 8_800_000_000,
                    "main_net_inflow": 3_000_000,
                },
            ]
        )
    )

    response = build_daily_bars_coverage(
        cache=cache,
        symbols=["600519", "000001"],
        start_date="2024-01-02",
        end_date="2024-01-05",
    )

    assert response.summary[0].dataset == "daily_bars"
    item = next(item for item in response.items if item.symbol == "600519")
    assert item.start_date.isoformat() == "2024-01-02"
    assert item.end_date.isoformat() == "2024-01-03"
    assert item.missing_dates == ["2024-01-04", "2024-01-05"]
    assert item.missing_capital_flow_dates == ["2024-01-02"]
    missing_symbol = next(item for item in response.items if item.symbol == "000001")
    assert missing_symbol.missing_dates == ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]


def test_fetch_and_cache_daily_bars_reports_partial_success(tmp_path):
    cache = LocalCache(tmp_path)

    class FakeAdapter:
        def fetch_daily_bars(self, symbols, start_date, end_date):
            assert symbols == ["600519", "000001"]
            return _bars(
                [
                    {
                        "symbol": "600519",
                        "trade_date": "2024-01-02",
                        "open": 10,
                        "high": 11,
                        "low": 9.8,
                        "close": 10.5,
                        "volume": 1000,
                    }
                ]
            )

    result = fetch_and_cache_daily_bars(
        cache=cache,
        symbols=["600519", "000001"],
        start_date="2024-01-02",
        end_date="2024-01-03",
        adapter=FakeAdapter(),
    )

    assert result.imported_rows == 1
    assert result.symbols_with_data == ["600519"]
    assert result.symbols_missing == ["000001"]


def test_health_payload_uses_concrete_cache_path(tmp_path):
    cache = LocalCache(tmp_path)

    payload = health_payload(cache=cache, service_version="0.1.1", port=9001)

    assert payload.ready is True
    assert payload.port == 9001
    assert payload.cache_dir == str(tmp_path)
```

- [ ] **Step 2: Run the backend test file and confirm failure**

Run:

```powershell
python -m pytest tests/test_data_operations.py -q
```

Expected: FAIL because `astock_backtester.data.operations` does not exist and cache merge coverage behavior is not implemented yet.

- [ ] **Step 3: Add service payload models**

Append these models near `DatasetCoverage` in `backend/astock_backtester/models.py`:

```python
class ServiceHealth(BaseModel):
    ready: bool
    service_version: str
    cache_dir: str
    port: int
    message: str


class DailyBarsCoverageItem(BaseModel):
    symbol: str
    start_date: date | None
    end_date: date | None
    row_count: int
    missing_dates: list[date] = Field(default_factory=list)
    missing_capital_flow_dates: list[date] = Field(default_factory=list)
    missing_market_cap_dates: list[date] = Field(default_factory=list)


class DailyBarsCoverageResponse(BaseModel):
    summary: list[DatasetCoverage]
    items: list[DailyBarsCoverageItem]


class FetchResult(BaseModel):
    imported_rows: int
    symbols_with_data: list[str]
    symbols_missing: list[str]
    coverage: list[DatasetCoverage]
    message: str


class ImportResult(BaseModel):
    imported_rows: int
    coverage: list[DatasetCoverage]
    message: str


class ServiceLogEntry(BaseModel):
    level: Literal["info", "error"]
    message: str
    timestamp: str
```

- [ ] **Step 4: Stop turning missing capital-flow into zero**

Change the optional defaults block in `backend/astock_backtester/data/importer.py` to:

```python
    optional_defaults = {
        "turnover_rate": 0.0,
        "float_market_cap": float("nan"),
        "main_net_inflow": float("nan"),
        "is_st": False,
        "is_suspended": False,
        "listing_days": 9999,
    }
```

- [ ] **Step 5: Make cache writes merge by symbol/date instead of destructive replace**

Replace `write_daily_bars` and `coverage` in `backend/astock_backtester/data/cache.py` with:

```python
    def write_daily_bars(self, frame: pd.DataFrame) -> None:
        incoming = normalize_daily_bars(frame)
        current = self.read_daily_bars()
        if current.empty:
            merged = incoming
        else:
            key_cols = ["symbol", "trade_date"]
            current_indexed = current.set_index(key_cols)
            incoming_indexed = incoming.set_index(key_cols)
            merged = (
                incoming_indexed.combine_first(current_indexed)
                .sort_index()
                .reset_index()
            )
        try:
            merged.to_parquet(self.daily_bars_path, index=False)
            if self.daily_bars_pickle_path.exists():
                self.daily_bars_pickle_path.unlink()
        except ImportError:
            merged.to_pickle(self.daily_bars_pickle_path)
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO datasets(dataset, updated_at) VALUES('daily_bars', CURRENT_TIMESTAMP)"
            )

    def coverage(self) -> list[DatasetCoverage]:
        bars = self.read_daily_bars()
        if bars.empty:
            return [
                DatasetCoverage(dataset="daily_bars", symbols=0, start_date=None, end_date=None),
                DatasetCoverage(dataset="capital_flow", symbols=0, start_date=None, end_date=None),
                DatasetCoverage(dataset="market_cap", symbols=0, start_date=None, end_date=None),
            ]
        start_date = bars["trade_date"].min().date()
        end_date = bars["trade_date"].max().date()
        return [
            DatasetCoverage(
                dataset="daily_bars",
                symbols=int(bars["symbol"].nunique()),
                start_date=start_date,
                end_date=end_date,
                missing_rows=int(bars[["open", "high", "low", "close"]].isna().any(axis=1).sum()),
            ),
            DatasetCoverage(
                dataset="capital_flow",
                symbols=int(bars.loc[bars["main_net_inflow"].notna(), "symbol"].nunique()),
                start_date=start_date,
                end_date=end_date,
                missing_rows=int(bars["main_net_inflow"].isna().sum()),
            ),
            DatasetCoverage(
                dataset="market_cap",
                symbols=int(bars.loc[bars["float_market_cap"].notna(), "symbol"].nunique()),
                start_date=start_date,
                end_date=end_date,
                missing_rows=int(bars["float_market_cap"].isna().sum()),
            ),
        ]
```

- [ ] **Step 6: Create shared service operations**

Create `backend/astock_backtester/data/operations.py`:

```python
from __future__ import annotations

from datetime import date
from typing import Sequence

import pandas as pd

from astock_backtester.data.astock_adapter import AStockDataAdapter
from astock_backtester.data.cache import LocalCache
from astock_backtester.data.importer import read_daily_bars
from astock_backtester.models import (
    DailyBarsCoverageItem,
    DailyBarsCoverageResponse,
    FetchResult,
    ImportResult,
    ServiceHealth,
)


def _date_strings(start_date: str, end_date: str) -> list[date]:
    return [
        item.date()
        for item in pd.date_range(start=pd.Timestamp(start_date), end=pd.Timestamp(end_date), freq="D")
    ]


def health_payload(cache: LocalCache, service_version: str, port: int) -> ServiceHealth:
    return ServiceHealth(
        ready=True,
        service_version=service_version,
        cache_dir=str(cache.root),
        port=port,
        message="local data service is ready",
    )


def build_daily_bars_coverage(
    cache: LocalCache,
    symbols: Sequence[str],
    start_date: str,
    end_date: str,
) -> DailyBarsCoverageResponse:
    bars = cache.read_daily_bars()
    requested_days = _date_strings(start_date, end_date)
    items: list[DailyBarsCoverageItem] = []
    for symbol in symbols:
        symbol_frame = bars[
            (bars["symbol"] == symbol)
            & (bars["trade_date"] >= pd.Timestamp(start_date))
            & (bars["trade_date"] <= pd.Timestamp(end_date))
        ].copy()
        present_dates = {
            item.date()
            for item in symbol_frame["trade_date"].tolist()
        } if not symbol_frame.empty else set()
        missing_dates = [item for item in requested_days if item not in present_dates]
        missing_flow_dates = [
            item.date()
            for item in symbol_frame.loc[symbol_frame["main_net_inflow"].isna(), "trade_date"].tolist()
        ]
        missing_cap_dates = [
            item.date()
            for item in symbol_frame.loc[symbol_frame["float_market_cap"].isna(), "trade_date"].tolist()
        ]
        items.append(
            DailyBarsCoverageItem(
                symbol=symbol,
                start_date=None if symbol_frame.empty else symbol_frame["trade_date"].min().date(),
                end_date=None if symbol_frame.empty else symbol_frame["trade_date"].max().date(),
                row_count=int(len(symbol_frame)),
                missing_dates=missing_dates,
                missing_capital_flow_dates=missing_flow_dates,
                missing_market_cap_dates=missing_cap_dates,
            )
        )
    return DailyBarsCoverageResponse(summary=cache.coverage(), items=items)


def import_and_cache_daily_bars(cache: LocalCache, source: str, path: str | None = None) -> ImportResult:
    if source == "sample":
        from astock_backtester.sample_data import sample_daily_bars

        frame = sample_daily_bars()
    elif source == "file" and path:
        frame = read_daily_bars(path)
    else:
        raise ValueError("source must be 'sample' or 'file' with a path")
    cache.write_daily_bars(frame)
    return ImportResult(
        imported_rows=int(len(frame)),
        coverage=cache.coverage(),
        message="daily bars imported into local cache",
    )


def fetch_and_cache_daily_bars(
    cache: LocalCache,
    symbols: Sequence[str],
    start_date: str,
    end_date: str,
    adapter: AStockDataAdapter | None = None,
) -> FetchResult:
    data_adapter = adapter or AStockDataAdapter.from_http_sources()
    frame = data_adapter.fetch_daily_bars(symbols, start_date, end_date)
    if frame.empty:
        raise ValueError("a-stock-data returned no daily bars for the requested symbols and date range")
    cache.write_daily_bars(frame)
    symbols_with_data = sorted(frame["symbol"].astype(str).unique().tolist())
    missing = sorted(symbol for symbol in symbols if symbol not in symbols_with_data)
    return FetchResult(
        imported_rows=int(len(frame)),
        symbols_with_data=symbols_with_data,
        symbols_missing=missing,
        coverage=cache.coverage(),
        message="daily bars fetched and merged into local cache",
    )
```

- [ ] **Step 7: Run the backend test file again**

Run:

```powershell
python -m pytest tests/test_data_operations.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 1**

Run:

```powershell
git add backend/astock_backtester/models.py backend/astock_backtester/data/importer.py backend/astock_backtester/data/cache.py backend/astock_backtester/data/operations.py tests/test_data_operations.py
git commit -m "feat: add cache-safe data service operations"
```

## Task 2: Expose Cache Operations Through A Local Python HTTP Service

**Files:**
- Create: `backend/astock_backtester/service.py`
- Create: `tests/test_data_service_http.py`

- [ ] **Step 1: Write failing HTTP service tests**

Create `tests/test_data_service_http.py`:

```python
import json
import threading
from urllib.request import Request, urlopen

from astock_backtester.service import create_server


def _request_json(method: str, url: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def test_service_health_and_logs(tmp_path):
    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        health = _request_json("GET", f"http://127.0.0.1:{port}/health")
        logs = _request_json("GET", f"http://127.0.0.1:{port}/logs/recent")
        assert health["ready"] is True
        assert health["port"] == port
        assert isinstance(logs["items"], list)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_service_coverage_endpoint_returns_symbol_items(tmp_path):
    server = create_server(host="127.0.0.1", port=0, cache_dir=tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        response = _request_json(
            "POST",
            f"http://127.0.0.1:{port}/coverage/daily-bars",
            {
                "symbols": ["600519"],
                "start_date": "2024-01-02",
                "end_date": "2024-01-05",
            },
        )
        assert response["summary"][0]["dataset"] == "daily_bars"
        assert response["items"][0]["symbol"] == "600519"
    finally:
        server.shutdown()
        thread.join(timeout=5)
```

- [ ] **Step 2: Run the HTTP service tests and confirm failure**

Run:

```powershell
python -m pytest tests/test_data_service_http.py -q
```

Expected: FAIL because `astock_backtester.service` does not exist yet.

- [ ] **Step 3: Implement the service**

Create `backend/astock_backtester/service.py`:

```python
from __future__ import annotations

import argparse
import json
from collections import deque
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from astock_backtester.data.cache import LocalCache
from astock_backtester.data.operations import (
    build_daily_bars_coverage,
    fetch_and_cache_daily_bars,
    health_payload,
    import_and_cache_daily_bars,
)


SERVICE_VERSION = "0.1.1"


class ServiceState:
    def __init__(self, cache_dir: str, port: int) -> None:
        self.cache = LocalCache(cache_dir)
        self.port = port
        self.logs: deque[dict[str, str]] = deque(maxlen=200)

    def log(self, level: str, message: str) -> None:
        self.logs.appendleft(
            {
                "level": level,
                "message": message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )


class DataServiceHandler(BaseHTTPRequestHandler):
    server: "DataServiceServer"

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_OPTIONS(self) -> None:
        self._send_json({"ok": True})

    def do_GET(self) -> None:
        if self.path == "/health":
            payload = health_payload(
                cache=self.server.state.cache,
                service_version=SERVICE_VERSION,
                port=self.server.state.port,
            ).model_dump(mode="json")
            self._send_json(payload)
            return
        if self.path == "/logs/recent":
            self._send_json({"items": list(self.server.state.logs)})
            return
        self._send_json({"code": "not_found", "message": self.path}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        try:
            payload = self._read_json()
            if self.path == "/coverage/daily-bars":
                response = build_daily_bars_coverage(
                    cache=self.server.state.cache,
                    symbols=payload["symbols"],
                    start_date=payload["start_date"],
                    end_date=payload["end_date"],
                )
                self._send_json(response.model_dump(mode="json"))
                return
            if self.path == "/fetch/daily-bars":
                response = fetch_and_cache_daily_bars(
                    cache=self.server.state.cache,
                    symbols=payload["symbols"],
                    start_date=payload["start_date"],
                    end_date=payload["end_date"],
                )
                self.server.state.log("info", response.message)
                self._send_json(response.model_dump(mode="json"))
                return
            if self.path == "/import/daily-bars":
                response = import_and_cache_daily_bars(
                    cache=self.server.state.cache,
                    source=payload["source"],
                    path=payload.get("path"),
                )
                self.server.state.log("info", response.message)
                self._send_json(response.model_dump(mode="json"))
                return
            self._send_json({"code": "not_found", "message": self.path}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.server.state.log("error", str(exc))
            self._send_json({"code": "request_failed", "message": str(exc)}, HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: object) -> None:
        return


class DataServiceServer(ThreadingHTTPServer):
    def __init__(self, host: str, port: int, cache_dir: str) -> None:
        super().__init__((host, port), DataServiceHandler)
        self.state = ServiceState(cache_dir=cache_dir, port=self.server_address[1])


def create_server(host: str, port: int, cache_dir: str) -> DataServiceServer:
    return DataServiceServer(host=host, port=port, cache_dir=cache_dir)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--cache-dir", required=True)
    args = parser.parse_args()

    server = create_server(host=args.host, port=args.port, cache_dir=args.cache_dir)
    server.state.log("info", "local data service started")
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the HTTP service tests again**

Run:

```powershell
python -m pytest tests/test_data_service_http.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

Run:

```powershell
git add backend/astock_backtester/service.py tests/test_data_service_http.py
git commit -m "feat: add localhost data service"
```

## Task 3: Bundle And Manage The Service From Tauri

**Files:**
- Modify: `pyproject.toml`
- Modify: `.gitignore`
- Create: `scripts/build-data-service.ps1`
- Modify: `package.json`
- Modify: `src-tauri/tauri.conf.json`
- Create: `src-tauri/src/python_runtime.rs`
- Create: `src-tauri/src/service_manager.rs`
- Modify: `src-tauri/src/commands.rs`
- Modify: `src-tauri/src/lib.rs`

- [ ] **Step 1: Write failing Rust unit tests for service command resolution**

Create `src-tauri/src/service_manager.rs` with tests first:

```rust
#[cfg(test)]
mod tests {
    use super::{build_service_args, health_request};

    #[test]
    fn health_request_targets_localhost_health_endpoint() {
        let raw = health_request(9123);
        assert!(raw.contains("GET /health HTTP/1.1"));
        assert!(raw.contains("Host: 127.0.0.1:9123"));
    }

    #[test]
    fn build_service_args_uses_expected_host_port_and_cache_dir() {
        let args = build_service_args(9010, ".astock-cache");
        assert_eq!(
            args,
            vec![
                "-m".to_string(),
                "astock_backtester.service".to_string(),
                "--host".to_string(),
                "127.0.0.1".to_string(),
                "--port".to_string(),
                "9010".to_string(),
                "--cache-dir".to_string(),
                ".astock-cache".to_string(),
            ]
        );
    }
}
```

- [ ] **Step 2: Run the Rust test target and confirm failure**

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml service_manager -- --nocapture
```

Expected: FAIL because `service_manager.rs` and its exported functions do not exist yet.

- [ ] **Step 3: Add the sidecar build dependency and ignore build output**

Modify `pyproject.toml`:

```toml
[project.optional-dependencies]
dev = [
  "pytest>=8.2",
  "ruff>=0.5",
  "pyinstaller>=6.11",
]
```

Append to `.gitignore`:

```text
.pyinstaller/
src-tauri/bin/
```

- [ ] **Step 4: Add the sidecar build script**

Create `scripts/build-data-service.ps1`:

```powershell
param(
  [string]$Python = $env:ASTOCK_BACKTESTER_PYTHON
)

if (-not $Python) {
  $Python = "python"
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$distDir = Join-Path $repoRoot "src-tauri\bin"
$workDir = Join-Path $repoRoot ".pyinstaller\build"
$specDir = Join-Path $repoRoot ".pyinstaller\spec"

New-Item -ItemType Directory -Force $distDir | Out-Null
New-Item -ItemType Directory -Force $workDir | Out-Null
New-Item -ItemType Directory -Force $specDir | Out-Null

& $Python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --name astock-data-service `
  --distpath $distDir `
  --workpath $workDir `
  --specpath $specDir `
  --paths backend `
  backend\astock_backtester\service.py

if (-not (Test-Path (Join-Path $distDir "astock-data-service.exe"))) {
  throw "astock-data-service.exe was not created"
}
```

- [ ] **Step 5: Make npm/Tauri builds produce and bundle the sidecar**

Modify `package.json`:

```json
{
  "version": "0.1.1",
  "scripts": {
    "dev": "vite --host 127.0.0.1 --config frontend/vite.config.ts",
    "test:ui": "vitest --config frontend/vitest.config.ts",
    "build": "vite build --config frontend/vite.config.ts",
    "build:data-service": "powershell -ExecutionPolicy Bypass -File scripts/build-data-service.ps1",
    "release:latest-json": "powershell -ExecutionPolicy Bypass -File scripts/write-latest-json.ps1",
    "tauri": "tauri"
  }
}
```

Modify the relevant parts of `src-tauri/tauri.conf.json`:

```json
{
  "version": "0.1.1",
  "build": {
    "beforeDevCommand": "npm run dev",
    "devUrl": "http://127.0.0.1:1420",
    "beforeBuildCommand": "npm run build && npm run build:data-service",
    "frontendDist": "../dist"
  },
  "bundle": {
    "active": true,
    "useLocalToolsDir": true,
    "targets": ["nsis"],
    "createUpdaterArtifacts": true,
    "resources": ["bin/astock-data-service.exe"]
  }
}
```

- [ ] **Step 6: Add shared Python runtime resolution for development commands**

Create `src-tauri/src/python_runtime.rs`:

```rust
use std::process::Command;

pub fn python_command() -> Result<Command, String> {
    if let Ok(path) = std::env::var("ASTOCK_BACKTESTER_PYTHON") {
        return Ok(Command::new(path));
    }
    if Command::new("python").arg("--version").output().is_ok() {
        return Ok(Command::new("python"));
    }
    if Command::new("py").args(["-3", "--version"]).output().is_ok() {
        let mut command = Command::new("py");
        command.arg("-3");
        return Ok(command);
    }
    Err("python runtime was not found; set ASTOCK_BACKTESTER_PYTHON for desktop builds".to_string())
}
```

- [ ] **Step 7: Implement the Tauri service manager**

Create `src-tauri/src/service_manager.rs`:

```rust
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager};

use crate::python_runtime::python_command;

#[derive(Clone, serde::Serialize)]
pub struct DataServiceStatus {
    pub running: bool,
    pub port: u16,
    pub base_url: String,
    pub cache_dir: String,
    pub message: String,
}

pub struct ManagedService {
    child: Child,
    port: u16,
    cache_dir: String,
}

#[derive(Default)]
pub struct DataServiceManager {
    service: Option<ManagedService>,
}

pub fn build_service_args(port: u16, cache_dir: &str) -> Vec<String> {
    vec![
        "-m".to_string(),
        "astock_backtester.service".to_string(),
        "--host".to_string(),
        "127.0.0.1".to_string(),
        "--port".to_string(),
        port.to_string(),
        "--cache-dir".to_string(),
        cache_dir.to_string(),
    ]
}

pub fn health_request(port: u16) -> String {
    format!("GET /health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n")
}

fn choose_port() -> Result<u16, String> {
    let listener = TcpListener::bind("127.0.0.1:0").map_err(|err| format!("bind port failed: {err}"))?;
    let port = listener.local_addr().map_err(|err| format!("read port failed: {err}"))?.port();
    drop(listener);
    Ok(port)
}

fn wait_for_health(port: u16) -> Result<(), String> {
    let deadline = Instant::now() + Duration::from_secs(8);
    while Instant::now() < deadline {
        if let Ok(mut stream) = TcpStream::connect(("127.0.0.1", port)) {
            let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
            let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
            let _ = stream.write_all(health_request(port).as_bytes());
            let mut raw = String::new();
            let _ = stream.read_to_string(&mut raw);
            if raw.contains("200 OK") {
                return Ok(());
            }
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    Err(format!("localhost data service did not become healthy on port {port}"))
}

fn packaged_service_path(app: &AppHandle) -> Result<PathBuf, String> {
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|err| format!("resource dir unavailable: {err}"))?;
    Ok(resource_dir.join("bin").join("astock-data-service.exe"))
}

impl DataServiceManager {
    pub fn ensure_running(&mut self, app: &AppHandle, cache_dir: &str) -> Result<DataServiceStatus, String> {
        if let Some(existing) = self.service.as_mut() {
            if existing.child.try_wait().map_err(|err| err.to_string())?.is_none() {
                return Ok(DataServiceStatus {
                    running: true,
                    port: existing.port,
                    base_url: format!("http://127.0.0.1:{}", existing.port),
                    cache_dir: existing.cache_dir.clone(),
                    message: "local data service already running".to_string(),
                });
            }
            self.service = None;
        }

        let port = choose_port()?;
        let mut command = if cfg!(debug_assertions) {
            let mut python = python_command()?;
            python.args(build_service_args(port, cache_dir));
            python.env("PYTHONPATH", "backend");
            python
        } else {
            let mut packaged = Command::new(packaged_service_path(app)?);
            packaged.args([
                "--host",
                "127.0.0.1",
                "--port",
                &port.to_string(),
                "--cache-dir",
                cache_dir,
            ]);
            packaged
        };

        command.stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::piped());
        let child = command
            .spawn()
            .map_err(|err| format!("failed to start localhost data service: {err}"))?;

        wait_for_health(port)?;
        self.service = Some(ManagedService {
            child,
            port,
            cache_dir: cache_dir.to_string(),
        });

        Ok(DataServiceStatus {
            running: true,
            port,
            base_url: format!("http://127.0.0.1:{port}"),
            cache_dir: cache_dir.to_string(),
            message: "local data service started".to_string(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::{build_service_args, health_request};

    #[test]
    fn health_request_targets_localhost_health_endpoint() {
        let raw = health_request(9123);
        assert!(raw.contains("GET /health HTTP/1.1"));
        assert!(raw.contains("Host: 127.0.0.1:9123"));
    }

    #[test]
    fn build_service_args_uses_expected_host_port_and_cache_dir() {
        let args = build_service_args(9010, ".astock-cache");
        assert_eq!(
            args,
            vec![
                "-m".to_string(),
                "astock_backtester.service".to_string(),
                "--host".to_string(),
                "127.0.0.1".to_string(),
                "--port".to_string(),
                "9010".to_string(),
                "--cache-dir".to_string(),
                ".astock-cache".to_string(),
            ]
        );
    }
}
```

- [ ] **Step 8: Register the service manager and new command**

Modify `src-tauri/src/commands.rs`:

```rust
use serde_json::Value;
use std::io::Write;
use std::process::Stdio;
use std::sync::Mutex;
use tauri::{AppHandle, State};

use crate::python_runtime::python_command;
use crate::service_manager::{DataServiceManager, DataServiceStatus};

#[tauri::command]
pub fn ensure_data_service(
    app: AppHandle,
    cache_dir: String,
    manager: State<Mutex<DataServiceManager>>,
) -> Result<DataServiceStatus, String> {
    let mut manager = manager.lock().map_err(|_| "data service manager lock poisoned".to_string())?;
    manager.ensure_running(&app, &cache_dir)
}

#[tauri::command]
pub fn backend_command(payload: Value) -> Result<Value, String> {
    let mut command = python_command()?;
    let mut child = command
        .args(["-m", "astock_backtester.cli"])
        .env("PYTHONPATH", "backend")
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

Modify `src-tauri/src/lib.rs`:

```rust
mod commands;
mod python_runtime;
mod service_manager;

use std::sync::Mutex;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_process::init())
        .manage(Mutex::new(service_manager::DataServiceManager::default()))
        .setup(|app| {
            #[cfg(desktop)]
            app.handle()
                .plugin(tauri_plugin_updater::Builder::new().build())?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::backend_command,
            commands::ensure_data_service
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

- [ ] **Step 9: Run the Rust tests and sidecar build script**

Run:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml service_manager -- --nocapture
python -m pip install -e ".[dev]"
powershell -ExecutionPolicy Bypass -File scripts/build-data-service.ps1
```

Expected:

- Rust unit tests PASS.
- `src-tauri\bin\astock-data-service.exe` exists.

- [ ] **Step 10: Run a Tauri no-bundle build to verify the new command wiring**

Run:

```powershell
npm run tauri -- build --debug --no-bundle
```

Expected: PASS with the sidecar resource bundled and no missing-command compile errors.

- [ ] **Step 11: Commit Task 3**

Run:

```powershell
git add pyproject.toml .gitignore scripts/build-data-service.ps1 package.json src-tauri/tauri.conf.json src-tauri/src/python_runtime.rs src-tauri/src/service_manager.rs src-tauri/src/commands.rs src-tauri/src/lib.rs
git commit -m "feat: manage bundled localhost data service"
```

## Task 4: Wire The Data Center UI To The Managed Local Service

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/components/DataCenter.tsx`
- Create: `frontend/src/components/DataCenter.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Write failing UI tests for service status and fetch/import actions**

Create `frontend/src/components/DataCenter.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DataCenter } from "./DataCenter";

const api = vi.hoisted(() => ({
  ensureDataService: vi.fn(),
  loadDailyBarsCoverage: vi.fn(),
  fetchDailyBars: vi.fn(),
  importDailyBars: vi.fn()
}));

vi.mock("../api", () => api);

describe("DataCenter", () => {
  it("shows local service status and coverage details", async () => {
    api.ensureDataService.mockResolvedValue({
      running: true,
      port: 9010,
      base_url: "http://127.0.0.1:9010",
      cache_dir: ".astock-cache",
      message: "local data service started"
    });
    api.loadDailyBarsCoverage.mockResolvedValue({
      summary: [{ dataset: "daily_bars", symbols: 1, start_date: "2024-01-02", end_date: "2024-01-03", missing_rows: 0 }],
      items: [
        {
          symbol: "600519",
          start_date: "2024-01-02",
          end_date: "2024-01-03",
          row_count: 2,
          missing_dates: ["2024-01-04"],
          missing_capital_flow_dates: ["2024-01-02"],
          missing_market_cap_dates: []
        }
      ]
    });

    render(<DataCenter coverage={[]} cacheDir=".astock-cache" onRefresh={vi.fn()} />);

    expect(await screen.findByText("本地服务已连接")).toBeInTheDocument();
    expect(await screen.findByText("600519")).toBeInTheDocument();
    expect(screen.getByText(/2024-01-04/)).toBeInTheDocument();
  });

  it("fetches missing bars and refreshes coverage", async () => {
    const user = userEvent.setup();
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    api.ensureDataService.mockResolvedValue({
      running: true,
      port: 9010,
      base_url: "http://127.0.0.1:9010",
      cache_dir: ".astock-cache",
      message: "local data service started"
    });
    api.loadDailyBarsCoverage.mockResolvedValue({ summary: [], items: [] });
    api.fetchDailyBars.mockResolvedValue({
      imported_rows: 2,
      symbols_with_data: ["600519"],
      symbols_missing: [],
      coverage: [],
      message: "daily bars fetched and merged into local cache"
    });

    render(<DataCenter coverage={[]} cacheDir=".astock-cache" onRefresh={onRefresh} />);

    await user.clear(await screen.findByLabelText("股票代码"));
    await user.type(screen.getByLabelText("股票代码"), "600519");
    await user.click(screen.getByRole("button", { name: "补全缺失数据" }));

    await waitFor(() => expect(api.fetchDailyBars).toHaveBeenCalledTimes(1));
    expect(onRefresh).toHaveBeenCalledTimes(1);
    expect(await screen.findByText(/merged into local cache/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the Data Center UI test and confirm failure**

Run:

```powershell
npm run test:ui -- --run frontend/src/components/DataCenter.test.tsx
```

Expected: FAIL because the new API functions and `cacheDir` prop do not exist yet.

- [ ] **Step 3: Add frontend service types**

Append to `frontend/src/types.ts`:

```ts
export type DataServiceStatus = {
  running: boolean;
  port: number;
  base_url: string;
  cache_dir: string;
  message: string;
};

export type DailyBarsCoverageItem = {
  symbol: string;
  start_date: string | null;
  end_date: string | null;
  row_count: number;
  missing_dates: string[];
  missing_capital_flow_dates: string[];
  missing_market_cap_dates: string[];
};

export type DailyBarsCoverageResponse = {
  summary: DatasetCoverage[];
  items: DailyBarsCoverageItem[];
};

export type FetchResult = {
  imported_rows: number;
  symbols_with_data: string[];
  symbols_missing: string[];
  coverage: DatasetCoverage[];
  message: string;
};

export type ImportResult = {
  imported_rows: number;
  coverage: DatasetCoverage[];
  message: string;
};
```

- [ ] **Step 4: Add Tauri command and localhost fetch helpers**

Replace `frontend/src/api.ts` with:

```ts
import { invoke } from "@tauri-apps/api/core";
import type {
  BacktestResult,
  BacktestSettingsConfig,
  DataServiceStatus,
  DatasetCoverage,
  DailyBarsCoverageResponse,
  FetchResult,
  ImportResult,
  StrategyConfig
} from "./types";

type BackendResponse<T> = ({ ok: true } & T) | { ok: false; error: { code: string; message: string } };

function isTauriRuntime(): boolean {
  return Boolean((window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__);
}

async function callBackend<T>(payload: Record<string, unknown>): Promise<T> {
  const response = await invoke<BackendResponse<T>>("backend_command", { payload });
  if (!response.ok) {
    throw new Error(response.error.message);
  }
  return response;
}

async function serviceFetch<T>(baseUrl: string, path: string, payload?: Record<string, unknown>): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    method: payload ? "POST" : "GET",
    headers: { "Content-Type": "application/json" },
    body: payload ? JSON.stringify(payload) : undefined
  });
  const json = await response.json();
  if (!response.ok) {
    throw new Error(json.message ?? "local data service request failed");
  }
  return json as T;
}

export async function ensureDataService(cacheDir: string): Promise<DataServiceStatus> {
  if (!isTauriRuntime()) {
    return {
      running: true,
      port: 9010,
      base_url: "http://127.0.0.1:9010",
      cache_dir: cacheDir,
      message: "browser preview uses mock local service"
    };
  }
  return invoke<DataServiceStatus>("ensure_data_service", { cacheDir });
}

export async function loadCoverage(cacheDir: string): Promise<DatasetCoverage[]> {
  const response = await callBackend<{ coverage: DatasetCoverage[] }>({ command: "coverage", cache_dir: cacheDir });
  return response.coverage;
}

export async function loadDailyBarsCoverage(
  baseUrl: string,
  symbols: string[],
  startDate: string,
  endDate: string
): Promise<DailyBarsCoverageResponse> {
  return serviceFetch<DailyBarsCoverageResponse>(baseUrl, "/coverage/daily-bars", {
    symbols,
    start_date: startDate,
    end_date: endDate
  });
}

export async function fetchDailyBars(
  baseUrl: string,
  symbols: string[],
  startDate: string,
  endDate: string
): Promise<FetchResult> {
  return serviceFetch<FetchResult>(baseUrl, "/fetch/daily-bars", {
    symbols,
    start_date: startDate,
    end_date: endDate
  });
}

export async function importDailyBars(
  baseUrl: string,
  source: "sample" | "file",
  path?: string
): Promise<ImportResult> {
  return serviceFetch<ImportResult>(baseUrl, "/import/daily-bars", { source, path });
}

export async function runConfiguredBacktest(strategy: StrategyConfig, settings: BacktestSettingsConfig): Promise<BacktestResult> {
  const response = await callBackend<{ result: BacktestResult }>({
    command: "run_backtest",
    strategy,
    settings,
    cache_dir: ".astock-cache"
  });
  return response.result;
}
```

- [ ] **Step 5: Rebuild the Data Center component around service status and actions**

Replace `frontend/src/components/DataCenter.tsx` with:

```tsx
import { useEffect, useState } from "react";
import {
  ensureDataService,
  fetchDailyBars,
  importDailyBars,
  loadDailyBarsCoverage
} from "../api";
import type { DataServiceStatus, DatasetCoverage, DailyBarsCoverageItem } from "../types";

type Props = {
  cacheDir: string;
  coverage: DatasetCoverage[];
  onRefresh: () => Promise<void> | void;
};

const today = "2024-01-08";

export function DataCenter({ cacheDir, coverage, onRefresh }: Props) {
  const [service, setService] = useState<DataServiceStatus | null>(null);
  const [symbolsInput, setSymbolsInput] = useState("600519");
  const [startDate, setStartDate] = useState("2024-01-02");
  const [endDate, setEndDate] = useState(today);
  const [importPath, setImportPath] = useState("");
  const [items, setItems] = useState<DailyBarsCoverageItem[]>([]);
  const [message, setMessage] = useState("正在连接本地数据服务");

  const symbols = symbolsInput
    .split(/[,\s]+/)
    .map((item) => item.trim())
    .filter(Boolean);

  const refreshDetails = async (activeService: DataServiceStatus) => {
    const response = await loadDailyBarsCoverage(activeService.base_url, symbols, startDate, endDate);
    setItems(response.items);
  };

  useEffect(() => {
    let cancelled = false;
    void ensureDataService(cacheDir)
      .then(async (status) => {
        if (cancelled) {
          return;
        }
        setService(status);
        setMessage("本地服务已连接");
        await refreshDetails(status);
      })
      .catch((error: Error) => {
        if (!cancelled) {
          setMessage(error.message);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [cacheDir]);

  const handleFetch = async () => {
    if (!service) {
      return;
    }
    const result = await fetchDailyBars(service.base_url, symbols, startDate, endDate);
    setMessage(result.message);
    await onRefresh();
    await refreshDetails(service);
  };

  const handleImportSample = async () => {
    if (!service) {
      return;
    }
    const result = await importDailyBars(service.base_url, "sample");
    setMessage(result.message);
    await onRefresh();
    await refreshDetails(service);
  };

  const handleImportFile = async () => {
    if (!service || !importPath.trim()) {
      return;
    }
    const result = await importDailyBars(service.base_url, "file", importPath.trim());
    setMessage(result.message);
    await onRefresh();
    await refreshDetails(service);
  };

  return (
    <section className="surface data-center">
      <div className="section-title">
        <div>
          <span className="section-kicker">数据健康</span>
          <h2>数据中心</h2>
        </div>
        <button className="secondary-button" type="button" onClick={() => service && refreshDetails(service)}>刷新覆盖范围</button>
      </div>

      <div className="data-service-panel">
        <div className="service-summary">
          <strong>{service ? "本地服务已连接" : "本地服务未连接"}</strong>
          <span>{service ? `${service.base_url} · ${service.cache_dir}` : message}</span>
        </div>
        <div className="service-form">
          <label>
            股票代码
            <input value={symbolsInput} onChange={(event) => setSymbolsInput(event.target.value)} />
          </label>
          <label>
            开始日期
            <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
          </label>
          <label>
            结束日期
            <input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
          </label>
          <label>
            导入文件路径
            <input value={importPath} onChange={(event) => setImportPath(event.target.value)} placeholder="C:\data\daily.csv" />
          </label>
        </div>
        <div className="service-actions">
          <button className="primary-button" type="button" onClick={handleFetch}>补全缺失数据</button>
          <button className="secondary-button" type="button" onClick={handleImportSample}>导入示例数据</button>
          <button className="secondary-button" type="button" onClick={handleImportFile}>导入本地文件</button>
        </div>
        <p className="muted-code">{message}</p>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>数据集</th>
              <th>股票数</th>
              <th>覆盖日期</th>
              <th>缺失行</th>
            </tr>
          </thead>
          <tbody>
            {coverage.map((item) => (
              <tr key={item.dataset}>
                <td>{item.dataset}</td>
                <td>{item.symbols}</td>
                <td>{item.start_date ?? "-"} 至 {item.end_date ?? "-"}</td>
                <td>{item.missing_rows}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="coverage-details">
        {items.map((item) => (
          <article key={item.symbol} className="coverage-item">
            <strong>{item.symbol}</strong>
            <span>{item.start_date ?? "-"} 至 {item.end_date ?? "-"}</span>
            <span>缺失日期: {item.missing_dates.length ? item.missing_dates.join(", ") : "无"}</span>
            <span>缺失资金流: {item.missing_capital_flow_dates.length ? item.missing_capital_flow_dates.join(", ") : "无"}</span>
            <span>缺失市值: {item.missing_market_cap_dates.length ? item.missing_market_cap_dates.join(", ") : "无"}</span>
          </article>
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 6: Pass the cache directory from the app shell**

Modify the `DataCenter` call in `frontend/src/App.tsx`:

```tsx
        <DataCenter cacheDir=".astock-cache" coverage={coverage} onRefresh={refreshCoverage} />
```

- [ ] **Step 7: Add styles for the service panel**

Append to `frontend/src/styles.css`:

```css
.data-service-panel {
  display: grid;
  gap: 12px;
  padding: 14px;
  border: 1px solid #d7e1e8;
  border-radius: 8px;
  background: #f8fbfd;
  margin-bottom: 16px;
}

.service-summary {
  display: grid;
  gap: 4px;
}

.service-form {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.service-form label,
.coverage-item {
  display: grid;
  gap: 6px;
}

.service-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.coverage-details {
  display: grid;
  gap: 10px;
  margin-top: 14px;
}

.coverage-item {
  padding: 12px;
  border: 1px solid #d7e1e8;
  border-radius: 8px;
  background: #ffffff;
}

@media (max-width: 960px) {
  .service-form {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 640px) {
  .service-form {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 8: Run the focused UI test suite**

Run:

```powershell
npm run test:ui -- --run frontend/src/components/DataCenter.test.tsx frontend/src/__tests__/strategyEditor.test.tsx frontend/src/components/UpdatePanel.test.tsx
```

Expected: PASS.

- [ ] **Step 9: Commit Task 4**

Run:

```powershell
git add frontend/src/types.ts frontend/src/api.ts frontend/src/components/DataCenter.tsx frontend/src/components/DataCenter.test.tsx frontend/src/App.tsx frontend/src/styles.css
git commit -m "feat: connect data center to localhost service"
```

## Task 5: Bump Versions, Regenerate Release Assets, And Verify The Desktop Update

**Files:**
- Create: `scripts/write-latest-json.ps1`
- Modify: `package.json`
- Modify: `pyproject.toml`
- Modify: `src-tauri/Cargo.toml`
- Modify: `src-tauri/tauri.conf.json`
- Modify: `release-assets/latest.json`
- Modify: `docs/dev.md`
- Modify: `docs/release.md`
- Modify: `README.md`

- [ ] **Step 1: Add a concrete `latest.json` generator**

Create `scripts/write-latest-json.ps1`:

```powershell
param(
  [Parameter(Mandatory = $true)][string]$Version,
  [Parameter(Mandatory = $true)][string]$AssetName,
  [Parameter(Mandatory = $true)][string]$Notes,
  [string]$Tag = "",
  [string]$OutputPath = "release-assets\latest.json"
)

if (-not $Tag) {
  $Tag = "v$Version"
}

$signaturePath = "src-tauri\target\release\bundle\nsis\$AssetName.sig"
if (-not (Test-Path $signaturePath)) {
  throw "signature file not found: $signaturePath"
}

$signature = (Get-Content -Raw $signaturePath).Trim()
$latest = @{
  version = $Version
  notes = $Notes
  pub_date = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
  platforms = @{
    "windows-x86_64" = @{
      signature = $signature
      url = "https://github.com/dzc-bit/A_stock_receiver/releases/download/$Tag/$AssetName"
    }
  }
}

$latestJson = $latest | ConvertTo-Json -Depth 5
New-Item -ItemType Directory -Force (Split-Path -Parent $OutputPath) | Out-Null
[System.IO.File]::WriteAllText((Resolve-Path "." | Join-Path -ChildPath $OutputPath), $latestJson, [System.Text.UTF8Encoding]::new($false))
```

- [ ] **Step 2: Align all version fields to `0.1.1`**

Modify these version fields:

```json
// package.json
"version": "0.1.1"
```

```toml
# pyproject.toml
version = "0.1.1"
```

```toml
# src-tauri/Cargo.toml
version = "0.1.1"
```

```json
// src-tauri/tauri.conf.json
"version": "0.1.1"
```

- [ ] **Step 3: Update release and development docs**

Append these concrete sections:

```markdown
## Build The Local Data Service Sidecar

Before a release build, create the Windows service executable:

```powershell
python -m pip install -e ".[dev]"
powershell -ExecutionPolicy Bypass -File scripts/build-data-service.ps1
```

Expected output:

- `src-tauri\bin\astock-data-service.exe`
```

Add this to `docs/release.md`:

```markdown
## Release Order

1. Bump `package.json`, `pyproject.toml`, `src-tauri/Cargo.toml`, and `src-tauri/tauri.conf.json` to the same version.
2. Build the sidecar with `scripts/build-data-service.ps1`.
3. Build the signed NSIS installer.
4. Generate `release-assets/latest.json` with `scripts/write-latest-json.ps1`.
5. Create the GitHub Release and upload the installer plus `latest.json`.
6. Verify `https://github.com/dzc-bit/A_stock_receiver/releases/latest/download/latest.json` returns the new version.
```

Update `README.md` installation/ability sections to mention:

```markdown
- 应用会启动本机 `127.0.0.1` 数据服务来补齐缺失历史数据。
- 回测引擎仍然只读取本地缓存，不在回测过程中联网。
- 新版本通过 GitHub Release 发布后，应用内“检查更新”可以检测并安装。
```

- [ ] **Step 4: Build and sign the release artifacts**

Run:

```powershell
python -m pytest tests -q
npm run test:ui -- --run
npm run build:data-service
npm run build
$env:TAURI_SIGNING_PRIVATE_KEY = Get-Content -Raw "$env:USERPROFILE\.tauri\a-stock-receiver.key"
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = ""
npm run tauri -- build --ci
Remove-Item Env:\TAURI_SIGNING_PRIVATE_KEY
```

Expected:

- backend tests PASS
- UI tests PASS
- `src-tauri\bin\astock-data-service.exe` exists
- signed NSIS installer and `.sig` file exist under `src-tauri\target\release\bundle\nsis`

- [ ] **Step 5: Generate the updater metadata for the concrete installer**

Run:

```powershell
$assetName = "A股策略回测工作台_0.1.1_x64-setup.exe"
powershell -ExecutionPolicy Bypass -File scripts/write-latest-json.ps1 -Version "0.1.1" -AssetName $assetName -Notes "新增本地数据服务与数据中心缺口补数"
```

Expected: `release-assets\latest.json` exists and references `v0.1.1` plus the concrete installer URL.

- [ ] **Step 6: Inspect git status before the final release commit**

Run:

```powershell
git status --short --branch
```

Expected: only intentional source/docs/release-asset changes are present. Generated `src-tauri/bin` and build directories remain ignored.

- [ ] **Step 7: Commit the release-ready version**

Run:

```powershell
git add scripts/write-latest-json.ps1 package.json pyproject.toml src-tauri/Cargo.toml src-tauri/tauri.conf.json release-assets/latest.json docs/dev.md docs/release.md README.md
git commit -m "feat: release hybrid data service update"
```

- [ ] **Step 8: Push the branch and tag the release**

Run:

```powershell
git push origin codex/a-stock-backtester
git tag v0.1.1
git push origin v0.1.1
```

Expected: branch and tag are both available on `origin`.

- [ ] **Step 9: Create the GitHub Release and upload assets**

If `gh` is available and authenticated, run:

```powershell
gh release create v0.1.1 src-tauri\target\release\bundle\nsis\A股策略回测工作台_0.1.1_x64-setup.exe release-assets\latest.json --title "v0.1.1" --notes "新增本地数据服务与数据中心缺口补数"
```

If `gh` is still unavailable in this workspace, create the release in the GitHub web UI using the pushed `v0.1.1` tag and upload these two files exactly:

- `src-tauri\target\release\bundle\nsis\A股策略回测工作台_0.1.1_x64-setup.exe`
- `release-assets\latest.json`

- [ ] **Step 10: Verify the installed-update path**

Run:

```powershell
Invoke-WebRequest "https://github.com/dzc-bit/A_stock_receiver/releases/latest/download/latest.json" | Select-Object -ExpandProperty Content
```

Expected: the JSON body contains `"version":"0.1.1"` and the Windows installer URL for `A股策略回测工作台_0.1.1_x64-setup.exe`.

## Self-Review Checklist

- Spec coverage:
  - Localhost service on `127.0.0.1`: Task 2 and Task 3.
  - Cache-only backtest path: preserved; Task 1 avoids destructive overwrites.
  - Data Center coverage/import/fetch/logs: Task 4.
  - Windows sidecar packaging: Task 3.
  - Version bump, signed installer, `latest.json`, GitHub Release: Task 5.
- Placeholder scan:
  - No `TODO`, `TBD`, “implement later”, or abstract “handle edge cases” steps remain.
- Type consistency:
  - Backend `ServiceHealth`, `DailyBarsCoverageResponse`, `FetchResult`, `ImportResult` match frontend `DataServiceStatus`, `DailyBarsCoverageResponse`, `FetchResult`, `ImportResult` by field name.

## Implementation Notes

- Keep `backend_command` for backtest/configured CLI calls. Do not reroute backtests through HTTP.
- `write_daily_bars` changing from destructive replace to merge is intentional; it is required for “补全缺失数据”.
- The Data Center file import uses a typed path string in this release. Do not introduce a file-dialog plugin unless the current implementation proves insufficient.
- The bundled sidecar must remain loopback-only. Do not bind to `0.0.0.0`.
- Real app-update validation requires a newer GitHub Release than the installed version. Local build verification alone does not prove updater discovery.
