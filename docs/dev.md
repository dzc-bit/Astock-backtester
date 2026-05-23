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
C:\Users\大帝之资\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe
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

This environment has a bundled `node.exe`, but no `npm`, `npx`, `pnpm`, `yarn`, or `corepack` command was available during implementation. Frontend tests and Vite build require a package manager before they can be verified here.

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

The Tauri bridge calls `python -m astock_backtester.cli` with `PYTHONPATH=backend` in development. Packaged sidecar bundling is a later hardening step after the development bridge is verified.

This environment did not have `cargo`, `rustc`, `rustup`, or the Tauri CLI available, so desktop packaging could not be verified locally.
