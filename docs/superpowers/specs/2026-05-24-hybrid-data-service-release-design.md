# Hybrid Data Service Release Design

## Goal

Ship the next Windows app update with a local-first data center that can fill missing A-share historical data through a Tauri-managed localhost data service. The update must also be publishable through the existing GitHub Release updater path, so users who click "check update" can see the new version.

## Current State

The app already has a Python backend, React/Tauri frontend, local cache storage under `.astock-cache`, and A-share HTTP source adapters based on the `simonlin1212/a-stock-data` style. Existing sources include Baidu daily K-line bars and optional Eastmoney metadata/fund-flow enrichment. The updater currently points at the GitHub release asset URL for `latest.json`, but the published release assets still describe version `0.1.0`, so pushing branch commits alone cannot trigger an app update.

## Chosen Approach

Use a Tauri-managed local Python data service. The service listens only on `127.0.0.1` and exposes data-management endpoints for the app. Backtests continue to read only local cache files. Data Center becomes the user-facing control surface for checking coverage, importing local files, and fetching missing data through the localhost service.

This approach is intentionally more involved than invoking Python commands directly, but it creates a clearer boundary between UI, app shell, and data operations. It also leaves room for future data sources, diagnostics, and external local integrations without changing the backtest engine.

## Architecture

The feature is split into four units:

- Frontend Data Center: shows service health, cache coverage, missing ranges, fetch/import controls, progress, and errors.
- Tauri service manager: starts or locates the localhost service, tracks its port, exposes safe commands to the frontend, and shuts the service down with the app where practical.
- Python data service: implements HTTP endpoints for health, coverage, import, fetch, and recent logs.
- Python data layer: owns cache reads/writes and external data adapters for Baidu/Eastmoney-compatible historical data.

The service binds to loopback only. It must not listen on `0.0.0.0`. Port selection should prefer a stable configured port if available and fall back to an available dynamic port to avoid collisions. Tauri is the source of truth for the active port exposed to the frontend.

## Data Flow

Backtest flow:

1. User configures a strategy and date range.
2. Backtest engine reads required bars from `.astock-cache`.
3. If cache data is missing, the backtest returns a clear missing-data error instead of fetching from the network.

Data Center coverage flow:

1. Frontend asks Tauri for data-service status.
2. Tauri ensures the local service is available and returns the active port/status.
3. Frontend requests coverage for selected symbols and date range.
4. Service scans the local cache and returns available ranges, missing ranges, and field completeness.

Data fill flow:

1. User requests missing data fill in Data Center.
2. Frontend sends symbols/date range/source options to the local service through Tauri-managed access.
3. Service fetches from external sources, writes successful daily bars and optional enrichment into `.astock-cache`, and leaves existing valid cache data intact.
4. Service returns a result with per-symbol success, partial success, skipped items, and failures.
5. Frontend refreshes coverage and shows the result.

Import flow:

1. User selects sample, CSV, or Parquet import.
2. Frontend calls the local service import endpoint.
3. Service validates required columns, normalizes symbols and dates, writes cache data, and returns import counts and validation errors.

## Service Endpoints

The first version should keep endpoints small and specific:

- `GET /health`: returns service version, cache path, and readiness.
- `POST /coverage/daily-bars`: returns local coverage for symbols and date range.
- `POST /fetch/daily-bars`: fetches external daily bars and optional enrichment, then updates cache.
- `POST /import/daily-bars`: imports local sample/CSV/Parquet data into cache.
- `GET /logs/recent`: returns recent service events useful for Data Center diagnostics.

The endpoint payloads should use JSON and stable field names. Errors should include a machine-readable code and a short user-facing message.

## Data Source Behavior

Baidu daily bars are treated as the primary OHLCV source. Eastmoney enrichment is optional and should never make the entire daily-bar fetch fail by itself. If enrichment fails, the service stores available OHLCV data and reports the missing optional fields.

The service must distinguish true zero values from missing values. All-missing fund-flow responses must be reported as unavailable data, not silently converted into zero.

Cache writes should be idempotent for the same symbol/date range. Re-fetching an existing range should update rows from the selected source without duplicating rows.

## Error Handling

The app should present actionable states:

- Service not running: Tauri tries to start it and shows failure details if startup fails.
- Port conflict: service manager selects another available loopback port.
- External source failure: existing cache remains usable and the result lists failed symbols/sources.
- Partial fetch success: successful symbols are cached; failed symbols remain marked as missing.
- Invalid import file: no partial cache write for rows that fail required validation.
- Missing cache for backtest: user is directed to Data Center to fill the required range.

No private signing keys, API credentials, or local cache files should be written into the repository.

## Frontend Changes

Data Center should show:

- Local service state and active cache path.
- Coverage summary for selected symbols/date range.
- Missing data actions: fill missing, refetch selected range, import file.
- Per-source result details for Baidu/Eastmoney.
- Recent service log entries for troubleshooting.

The UI should stay operational when offline for local coverage and imports. Network-dependent fetch actions should fail clearly when unavailable.

## Packaging And Release

The release must bump the app version, expected as `0.1.1` unless a different version is chosen before implementation. Version fields must stay aligned across:

- `package.json`
- `src-tauri/Cargo.toml`
- `src-tauri/tauri.conf.json`

The packaged app should include a Windows sidecar executable built from the Python data-service entrypoint, so the installed app can start the localhost service without requiring users to install Python separately. If sidecar packaging is blocked by build tooling, the fallback is to keep the release unreleased and document the blocker rather than shipping an installer that cannot start its data service. The build must generate a signed Windows installer and an updater `latest.json` that points to the GitHub Release installer asset for the same version.

Publishing requires:

1. Build and test the app.
2. Generate signed updater metadata.
3. Create GitHub Release `v0.1.1`.
4. Upload the installer and `latest.json`.
5. Push code and tag.
6. Verify the release URL used by the updater returns the new `latest.json`.

Pushing a branch is not enough for the updater. The updater reads release assets from GitHub.

## Testing

Backend tests should cover:

- Service health and JSON response shape.
- Coverage from empty, partial, and complete cache.
- Fetch writes cache and reports optional enrichment failures separately.
- Import validation and cache write behavior.
- Missing values are not converted into zero.

Tauri/frontend tests or focused manual verification should cover:

- Data Center can start or discover the service.
- Coverage refresh updates after fetch/import.
- Failed service startup and failed external fetch show useful messages.
- Backtest still reads from cache only.

Release verification should cover:

- Version fields match.
- Installer is produced.
- `latest.json` references the new version and installer URL.
- Existing "check update" path can see the release metadata.

## Out Of Scope

This release does not add a cloud backend, scheduled background market sync, realtime quotes, authentication, or a public network API. It also does not make the backtest engine fetch network data directly.
