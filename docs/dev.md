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

This environment has a bundled `node.exe`, but no global `npm`, `npx`, `pnpm`, `yarn`, or `corepack` command was available during implementation. For a normal Windows checkout, install Node.js LTS and use the standard `npm` commands above.

For this Codex desktop workspace only, a local npm tarball was downloaded to the gitignored `.tools\npm-10.9.0` directory and run with the bundled Node:

```powershell
$nodeDir = "C:\Users\大帝之资\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin"
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

The Python backend must be importable in the environment that launches Tauri. During development, run:

```powershell
python -m pip install -e ".[dev]"
```

before starting the desktop app.

The Tauri bridge calls `python -m astock_backtester.cli` with `PYTHONPATH=backend` in development. Packaged sidecar bundling is a later hardening step after the development bridge is verified.

For a normal Windows checkout, install Rust with rustup and install the Windows build tools required by Tauri. This Codex workspace used a gitignored project-local Rust toolchain under `.tools\cargo-home` and `.tools\rustup-home`; `npm run tauri -- build --debug --no-bundle` compiled the desktop app binary here. Full NSIS/MSI installer bundling still requires the matching Windows bundling tools on PATH; without them `tauri build --debug` fails after the executable is built.
