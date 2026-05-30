# Realtime Market Snapshot THS Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fragile Eastmoney-only realtime breadth and sector chain with a Tonghuashun-first market summary and hot-topic pipeline, then ship desktop version `1.0.0`.

**Architecture:** Keep the existing `RealtimeMarketProvider` entrypoint, but add Tonghuashun-specific fetch and parse helpers inside `backend/astock_backtester/data/realtime.py`. The provider will use an explicit priority chain for breadth and strong sectors, with tests locking the exact fallback order and message/source strings.

**Tech Stack:** Python 3.11, requests, pandas, BeautifulSoup-style HTML parsing via standard parsing helpers already available in the repo, pytest, React/Tauri release pipeline.

---

### Task 1: Add failing tests for Tonghuashun-first fallback order

**Files:**
- Modify: `tests/test_data_service_http.py`

- [ ] **Step 1: Write the failing tests**

Add tests that expect:

1. Tonghuashun market summary breadth to win over local history.
2. Tonghuashun hot-reason topic aggregation to win over Eastmoney and local.
3. Tonghuashun industry HTML ranking to be used when hot-reason is unavailable.

Use the existing fake requester style and assert `source`, `message`, `breadth`, and `strong_sectors`.

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run:

```powershell
.\.tools\python-3.11.9\python.exe -m pytest tests/test_data_service_http.py -k "tonghuashun or hot_reason or market_summary" -q
```

Expected: FAIL because the current provider has no Tonghuashun-first logic.

- [ ] **Step 3: Commit the failing tests**

```powershell
git add tests/test_data_service_http.py
git commit -m "test: cover Tonghuashun realtime fallback order"
```

### Task 2: Add failing tests for topic normalization and aggregation

**Files:**
- Modify: `tests/test_data_operations.py`

- [ ] **Step 1: Write the failing tests**

Add focused unit tests for:

1. Splitting topic reasons like `算力租赁+Token工厂+AI政务`.
2. Dropping empty/general tokens.
3. Ranking aggregated topics by frequency and strength.

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run:

```powershell
.\.tools\python-3.11.9\python.exe -m pytest tests/test_data_operations.py -k "topic or reason or strong_sector" -q
```

Expected: FAIL because the normalization helpers do not exist yet.

- [ ] **Step 3: Commit the failing tests**

```powershell
git add tests/test_data_operations.py
git commit -m "test: cover Tonghuashun topic aggregation"
```

### Task 3: Implement Tonghuashun topic and industry helpers

**Files:**
- Modify: `backend/astock_backtester/data/realtime.py`

- [ ] **Step 1: Add the minimal Tonghuashun helper functions**

Implement:

1. Market summary fetch/parse helper.
2. Hot-reason fetch helper.
3. Topic normalization and aggregation helpers.
4. Industry HTML ranking fetch/parse helper.

Keep them private to `RealtimeMarketProvider` or module-private.

- [ ] **Step 2: Wire strong-sector priority to Tonghuashun-first**

Priority:

1. `ths-hot-reason`
2. `ths-industry-html`
3. `eastmoney-sector`
4. `eastmoney-industry-sector`
5. `sina-sector`
6. local history

- [ ] **Step 3: Wire breadth priority to Tonghuashun-first**

Priority:

1. `ths-market-summary`
2. `eastmoney-a-share-live`
3. local history

- [ ] **Step 4: Update message/source composition**

Return source strings and message copy that accurately reflect the path taken.

- [ ] **Step 5: Run the targeted tests**

Run:

```powershell
.\.tools\python-3.11.9\python.exe -m pytest tests/test_data_service_http.py tests/test_data_operations.py -q
```

Expected: PASS for the new Tonghuashun tests and existing realtime tests.

- [ ] **Step 6: Commit**

```powershell
git add backend/astock_backtester/data/realtime.py tests/test_data_service_http.py tests/test_data_operations.py
git commit -m "feat: add Tonghuashun realtime sector and breadth fallbacks"
```

### Task 4: Validate the real local service response against live upstreams

**Files:**
- Modify: `backend/astock_backtester/data/realtime.py` if live verification reveals a parsing gap

- [ ] **Step 1: Start a local data service instance and fetch the realtime snapshot**

Run:

```powershell
$env:PYTHONPATH='backend'
@'
import tempfile, threading
from urllib.request import urlopen
from astock_backtester.service import create_server
server = create_server(host="127.0.0.1", port=0, cache_dir=tempfile.mkdtemp())
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    port = server.server_address[1]
    print(urlopen(f"http://127.0.0.1:{port}/realtime/market-snapshot", timeout=15).read().decode("utf-8"))
finally:
    server.shutdown()
    thread.join(timeout=5)
'@ | .\.tools\python-3.11.9\python.exe -
```

Expected: non-null `breadth`, non-empty `strong_sectors`, message referencing Tonghuashun when Eastmoney is unavailable.

- [ ] **Step 2: If parsing mismatches live HTML, fix the parser and re-run**

Run the same command again until the output matches the expected structure.

- [ ] **Step 3: Commit if live parsing required code changes**

```powershell
git add backend/astock_backtester/data/realtime.py
git commit -m "fix: align Tonghuashun realtime parsers with live HTML"
```

### Task 5: Update docs for the new realtime data chain

**Files:**
- Modify: `README.md`
- Modify: `项目说明书.md`

- [ ] **Step 1: Update README realtime source descriptions**

Document:

1. Tonghuashun market summary for red/green breadth.
2. Tonghuashun hot-reason aggregation for strong topics.
3. Tonghuashun industry HTML ranking fallback.
4. Eastmoney/local fallback order.

- [ ] **Step 2: Update the project manual source table**

Reflect the new upstream chain in the button/interface section.

- [ ] **Step 3: Run a quick grep verification**

Run:

```powershell
rg -n "同花顺|东方财富|红绿家数|强势板块|昨日强势追踪" README.md 项目说明书.md
```

Expected: updated source descriptions present in both docs.

- [ ] **Step 4: Commit**

```powershell
git add README.md 项目说明书.md
git commit -m "docs: document Tonghuashun realtime fallback chain"
```

### Task 6: Bump to version 1.0.0

**Files:**
- Modify: `package.json`
- Modify: `package-lock.json`
- Modify: `pyproject.toml`
- Modify: `src-tauri/Cargo.toml`
- Modify: `src-tauri/Cargo.lock`
- Modify: `src-tauri/tauri.conf.json`

- [ ] **Step 1: Update all version files to `1.0.0`**

Keep them fully aligned.

- [ ] **Step 2: Run a version grep check**

Run:

```powershell
rg -n "\"1\\.0\\.0\"|version = \"1\\.0\\.0\"" package.json package-lock.json pyproject.toml src-tauri
```

Expected: all required files show `1.0.0`.

- [ ] **Step 3: Commit**

```powershell
git add package.json package-lock.json pyproject.toml src-tauri/Cargo.toml src-tauri/Cargo.lock src-tauri/tauri.conf.json
git commit -m "chore: bump release version to 1.0.0"
```

### Task 7: Verify tests and build release artifacts

**Files:**
- No source edits unless verification fails

- [ ] **Step 1: Run backend verification**

Run:

```powershell
.\.tools\python-3.11.9\python.exe -m pytest tests/test_build_scripts.py tests/test_data_operations.py tests/test_data_service_http.py -q
```

Expected: PASS.

- [ ] **Step 2: Build frontend**

Run:

```powershell
.\.tools\node-v20.18.1-win-x64\node.exe node_modules\vite\bin\vite.js build --config frontend\vite.config.ts
```

Expected: build succeeds.

- [ ] **Step 3: Build the Python sidecar**

Run:

```powershell
$env:ASTOCK_BACKTESTER_PYTHON = "C:\Users\大帝之资\Documents\New project 6\.tools\python-3.11.9\python.exe"
powershell -ExecutionPolicy Bypass -File scripts\build-data-service.ps1
Remove-Item Env:\ASTOCK_BACKTESTER_PYTHON
```

Expected: `src-tauri\bin\astock-data-service.exe` exists.

- [ ] **Step 4: Build the signed Tauri installer**

Run:

```powershell
$repo = "C:\Users\大帝之资\Documents\New project 6"
$node = Join-Path $repo ".tools\node-v20.18.1-win-x64\node.exe"
$cargoBin = Join-Path $repo ".tools\rustup-home\toolchains\stable-x86_64-pc-windows-msvc\bin"
$rustupBin = Join-Path $repo ".tools\cargo-home\bin"
$env:PATH = "$cargoBin;$rustupBin;$env:PATH"
$env:CARGO_HOME = Join-Path $repo ".tools\cargo-home"
$env:RUSTUP_HOME = Join-Path $repo ".tools\rustup-home"
$env:TAURI_SIGNING_PRIVATE_KEY = Get-Content -Raw (Join-Path $repo "运行产物\签名密钥\a-stock-backtester-v017.key")
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = ""
@'
{
  "build": {
    "beforeBuildCommand": ""
  }
}
'@ | Set-Content -Path (Join-Path $repo ".tools\tauri.build.override.json") -Encoding UTF8
& $node "node_modules\@tauri-apps\cli\tauri.js" build --ci --config (Join-Path $repo ".tools\tauri.build.override.json")
Remove-Item Env:\TAURI_SIGNING_PRIVATE_KEY
Remove-Item Env:\TAURI_SIGNING_PRIVATE_KEY_PASSWORD
Remove-Item Env:\CARGO_HOME
Remove-Item Env:\RUSTUP_HOME
Remove-Item (Join-Path $repo ".tools\tauri.build.override.json") -Force
```

Expected: `src-tauri\target\release\bundle\nsis\A股策略回测工作台_1.0.0_x64-setup.exe` and `.sig` exist.

- [ ] **Step 5: Generate updater metadata**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\write-latest-json.ps1 -Version "1.0.0" -AssetName "A股策略回测工作台_1.0.0_x64-setup.exe" -Notes "Promote Tonghuashun realtime market summary and hot-topic sources, add HTML-based industry fallback, and ship desktop release 1.0.0."
```

Expected: `release-assets\latest.json` updated to `1.0.0`.

- [ ] **Step 6: Commit any release metadata changes**

```powershell
git add release-assets\latest.json
git commit -m "build: generate 1.0.0 updater metadata"
```

### Task 8: Update the installed desktop app and publish

**Files:**
- No source edits unless publish validation fails

- [ ] **Step 1: Install the new desktop build locally**

Run:

```powershell
$installer = "C:\Users\大帝之资\Documents\New project 6\src-tauri\target\release\bundle\nsis\A股策略回测工作台_1.0.0_x64-setup.exe"
Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match 'a-stock-backtester|A股策略|astock-data-service' } | Stop-Process -Force
Start-Process -FilePath $installer -ArgumentList '/S' -Wait
```

Expected: silent install completes with exit code `0`.

- [ ] **Step 2: Verify installed version**

Run:

```powershell
Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -eq 'A股策略回测工作台' } | Select-Object DisplayName,DisplayVersion,InstallLocation
```

Expected: `DisplayVersion` is `1.0.0`.

- [ ] **Step 3: Push git and tag release**

Run:

```powershell
git push origin master
git tag -f v1.0.0
git push origin refs/tags/v1.0.0
```

Expected: push succeeds.

- [ ] **Step 4: Publish GitHub release assets**

If `gh` is available and authenticated:

```powershell
gh release create v1.0.0 "src-tauri\target\release\bundle\nsis\A股策略回测工作台_1.0.0_x64-setup.exe" "src-tauri\target\release\bundle\nsis\A股策略回测工作台_1.0.0_x64-setup.exe.sig" "release-assets\latest.json" --title "v1.0.0" --notes "Promote Tonghuashun realtime market summary and hot-topic sources, add HTML-based industry fallback, and ship desktop release 1.0.0."
```

If `gh` is unavailable, stop and report the authentication/tooling gap explicitly.

- [ ] **Step 5: Final verification**

Run:

```powershell
git status --short
```

Expected: no unexpected modified tracked files remain.
