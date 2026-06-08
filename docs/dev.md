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
$env:PYTHONPATH = "backend"
'{"command":"demo_backtest"}' | python -m astock_backtester.cli
```

In this Codex desktop environment, the system `python` command is not on PATH. The bundled Python used for verification is:

```powershell
$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe
```

The bundled Python can run the backend tests, but it does not include `pyarrow`. The local cache falls back to a pickle file when Parquet support is unavailable, while preserving the Parquet path for environments with `pyarrow` installed.

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

This environment has a bundled `node.exe`, but no global `npm`, `npx`, `pnpm`, `yarn`, or `corepack` command was available during implementation. For a normal Windows checkout, install Node.js LTS and use the standard `npm` commands above.

For this Codex desktop workspace only, a local npm tarball was downloaded to the gitignored `.tools\npm-10.9.0` directory and run with the bundled Node:

```powershell
$nodeDir = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin"
$npm = ".tools\npm-10.9.0\package\bin\npm-cli.js"
$env:PATH = "$nodeDir;$env:PATH"
& "$nodeDir\node.exe" $npm install
& "$nodeDir\node.exe" $npm run test:ui -- --run
& "$nodeDir\node.exe" $npm run build
```

## Desktop

Run a Tauri debug build:

```powershell
npm run tauri -- build --debug
```

Verify the desktop app binary without creating an installer:

```powershell
npm run tauri -- build --debug --no-bundle
```

Run Rust unit tests after changing desktop commands, path handling, or service lifecycle code:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml
```

The desktop command `workspace_diagnostics` reports the resolved project root, canonical root, `.astock-cache` alias, `运行产物\本地数据仓`, and saved-strategy path. Use it when checking that the app is still using `D:\New project 6` as the real business root instead of writing business data to `AppData`.

Verify a signed debug installer and updater signature:

```powershell
$projectKey = "D:\New project 6\运行产物\签名密钥\a-stock-backtester-v017.key"
if (-not (Test-Path $projectKey)) { throw "Tauri signing key not found at project runtime key path" }
$env:TAURI_SIGNING_PRIVATE_KEY = Get-Content -Raw $projectKey
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = ""
npm run tauri -- build --debug --ci
Remove-Item Env:\TAURI_SIGNING_PRIVATE_KEY
```

The Python backend must be importable in the environment that launches Tauri. During development, run:

```powershell
python -m pip install -e ".[dev]"
```

before starting the desktop app.

In development, the Tauri bridge can still call `python -m astock_backtester.cli` with `PYTHONPATH=backend`.
Release builds must bundle the packaged sidecar at `src-tauri\bin\astock-data-service.exe`;
the installed app starts that binary from the application resource directory.

## Build The Local Data Service Sidecar

Before a release build, create the Windows service executable:

```powershell
python -m pip install -e ".[dev]"
powershell -ExecutionPolicy Bypass -File scripts/build-data-service.ps1
```

Expected output:

- `src-tauri\bin\astock-data-service.exe`

The Tauri release build runs `npm run build:data-service` through `build.beforeBuildCommand`, but running it explicitly first makes missing Python or PyInstaller problems easier to diagnose.

For a normal Windows checkout, install:

- Node.js LTS with npm.
- Rust with rustup, using the `x86_64-pc-windows-msvc` toolchain.
- Visual Studio Build Tools 2022 with the C++ workload (`Microsoft.VisualStudio.Workload.VCTools`) and Windows 10/11 SDK.

For this `D:\New project 6` workspace, prefer the project-local tools when PATH is incomplete:

```powershell
& 'D:\New project 6\.tools\node-v20.18.1-win-x64\node.exe' 'D:\New project 6\node_modules\vitest\vitest.mjs' --config frontend/vitest.config.ts --run
& 'D:\New project 6\.tools\node-v20.18.1-win-x64\node.exe' 'D:\New project 6\node_modules\typescript\bin\tsc' --noEmit
& 'D:\New project 6\.tools\node-v20.18.1-win-x64\node.exe' 'D:\New project 6\node_modules\vite\bin\vite.js' build --config frontend/vite.config.ts
& 'D:\New project 6\.tools\rustup-home\toolchains\stable-x86_64-pc-windows-msvc\bin\cargo.exe' test --manifest-path src-tauri\Cargo.toml
```

Keep all upstream market URLs and scraping logic inside backend provider modules. React components should consume structured service responses only. `/coverage/daily-bars` uses the A 股交易日历; do not replace it with plain weekday `freq="B"` logic because legal holidays such as Spring Festival, Qingming, Labor Day and National Day must not appear as missing trade dates. Version 1.1.1 ships 2024, 2025, and 2026 holiday ranges; refresh `backend/astock_backtester/data/trading_calendar.py` from exchange notices before a later cross-year release.

For realtime market data, the heavy public-market crawler may remember successful breadth internally for diagnostics, but a current request failure must return failure to the snapshot state machine. Do not let retained breadth qualify `/realtime/market-snapshot` as `live`; only indexes, complete current breadth, and current live sectors together form a complete intraday snapshot. For Tonghuashun briefing, both fupan and zaopan fallbacks must use explicit `market-fallback` or `local-brief` sources, with `source_url` set only when a real public-market or Tonghuashun link is available.

For capital-flow work, keep `CapitalFlowCrawler` as a low-level read-only provider. It may return rows, `failures`, and `diagnostics`, but it must not write `LocalCache` or `Warehouse`. The service-level operations own writes: `/fetch/daily-bars` merges crawler `main_net_inflow` into freshly fetched daily bars, and `/fetch/capital-flow` backfills existing local daily rows only. If Eastmoney disconnects after a previous success, the crawler may reuse in-process recent successful rows for the same symbol/date range, but it must still return the original failure plus `recent_success_cache_used`. When changing this path, run:

```powershell
python -m pytest tests/test_capital_flow_crawler.py tests/test_data_operations.py tests/test_data_service_http.py -q
& 'D:\New project 6\.tools\node-v20.18.1-win-x64\node.exe' 'D:\New project 6\node_modules\vitest\vitest.mjs' --config frontend\vitest.config.ts --run frontend\src\components\DataCenter.test.tsx frontend\src\api.timeout.test.ts
```

The app is configured for NSIS bundles. `bundle.useLocalToolsDir` is enabled in `src-tauri\tauri.conf.json`, so Tauri caches NSIS under `src-tauri\target\.tauri` instead of the user profile cache. If the first installer build runs on a network-restricted machine, allow access to Tauri's GitHub binary releases or pre-populate that cache.

This Codex workspace used a gitignored project-local Rust/npm setup under `.tools`. Because the elevated Codex sandbox maps the workspace through `C:\Users\CodexSandboxOffline\.codex\.sandbox\cwd\...`, MSVC debug PDB writes can fail in debug builds. For this environment only, load the MSVC environment and disable dev debug symbols for the build process:

```powershell
$tools = (Resolve-Path .tools).Path
$nodeDir = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin"
$cargoBin = Join-Path $tools "cargo-home\bin"
$npm = Join-Path $tools "npm-10.9.0\package\bin\npm-cli.js"
$env:RUSTUP_HOME = Join-Path $tools "rustup-home"
$env:CARGO_HOME = Join-Path $tools "cargo-home"
$env:npm_config_cache = Join-Path $tools "npm-cache"
$env:CARGO_PROFILE_DEV_DEBUG = "0"
$projectKey = "D:\New project 6\运行产物\签名密钥\a-stock-backtester-v017.key"
if (-not (Test-Path $projectKey)) { throw "Tauri signing key not found at project runtime key path" }
$env:TAURI_SIGNING_PRIVATE_KEY = Get-Content -Raw $projectKey
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = ""
cmd /S /C "call `"C:\BuildTools\VC\Auxiliary\Build\vcvars64.bat`" && set `"PATH=$tools;$cargoBin;$nodeDir;%PATH%`" && set `"RUSTUP_HOME=$env:RUSTUP_HOME`" && set `"CARGO_HOME=$env:CARGO_HOME`" && set `"npm_config_cache=$env:npm_config_cache`" && set `"CARGO_PROFILE_DEV_DEBUG=0`" && `"$nodeDir\node.exe`" `"$npm`" run tauri -- build --debug --ci"
Remove-Item Env:\TAURI_SIGNING_PRIVATE_KEY
```

## Release And Updates

Windows update signing, release asset requirements, `latest.json`, sidecar replacement checks, and installed-user update flow are documented in `docs/release.md`.
