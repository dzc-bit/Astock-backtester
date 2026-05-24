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

Verify a signed debug installer and updater signature:

```powershell
$env:TAURI_SIGNING_PRIVATE_KEY = Get-Content -Raw "$env:USERPROFILE\.tauri\a-stock-receiver.key"
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = ""
npm run tauri -- build --debug --ci
Remove-Item Env:\TAURI_SIGNING_PRIVATE_KEY
```

The Python backend must be importable in the environment that launches Tauri. During development, run:

```powershell
python -m pip install -e ".[dev]"
```

before starting the desktop app.

The Tauri bridge calls `python -m astock_backtester.cli` with `PYTHONPATH=backend` in development. Packaged sidecar bundling is a later hardening step after the development bridge is verified.

For a normal Windows checkout, install:

- Node.js LTS with npm.
- Rust with rustup, using the `x86_64-pc-windows-msvc` toolchain.
- Visual Studio Build Tools 2022 with the C++ workload (`Microsoft.VisualStudio.Workload.VCTools`) and Windows 10/11 SDK.

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
$env:TAURI_SIGNING_PRIVATE_KEY = Get-Content -Raw "$env:USERPROFILE\.tauri\a-stock-receiver.key"
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = ""
cmd /S /C "call `"C:\BuildTools\VC\Auxiliary\Build\vcvars64.bat`" && set `"PATH=$tools;$cargoBin;$nodeDir;%PATH%`" && set `"RUSTUP_HOME=$env:RUSTUP_HOME`" && set `"CARGO_HOME=$env:CARGO_HOME`" && set `"npm_config_cache=$env:npm_config_cache`" && set `"CARGO_PROFILE_DEV_DEBUG=0`" && `"$nodeDir\node.exe`" `"$npm`" run tauri -- build --debug --ci"
Remove-Item Env:\TAURI_SIGNING_PRIVATE_KEY
```

## Release And Updates

Windows update signing, release asset requirements, `latest.json`, and installed-user update flow are documented in `docs/release.md`.
