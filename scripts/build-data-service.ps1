param(
  [string]$Python = $env:ASTOCK_BACKTESTER_PYTHON
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$bundledPython = Join-Path $repoRoot ".tools\python-3.11.9\python.exe"
$projectPython = Join-Path $repoRoot ".tools\python-build\Scripts\python.exe"
if (-not $Python) {
  if (Test-Path $bundledPython) {
    $Python = $bundledPython
  } elseif (Test-Path $projectPython) {
    $Python = $projectPython
  } else {
    $Python = "python"
  }
}

$distDir = Join-Path $repoRoot "src-tauri\bin"
$workDir = Join-Path $repoRoot ".pyinstaller\build"
$specDir = Join-Path $repoRoot ".pyinstaller\spec"
$cacheDir = Join-Path $repoRoot ".pyinstaller\cache"
$targetExe = Join-Path $distDir "astock-data-service.exe"
$targetNodeExe = Join-Path $distDir "node.exe"
$targetThsWorker = Join-Path $distDir "ths-cookie-worker.cjs"
$targetXhrSyncWorker = Join-Path $distDir "xhr-sync-worker.js"
$bundledNode = Join-Path $repoRoot ".tools\node-v20.18.1-win-x64\node.exe"
$esbuildBin = Join-Path $repoRoot "node_modules\esbuild\bin\esbuild"
$jsdomXhrSyncWorker = Join-Path $repoRoot "node_modules\jsdom\lib\jsdom\living\xhr\xhr-sync-worker.js"
$watchlistCsv = Join-Path $repoRoot "backend\astock_backtester\data\potential_risk_watchlist.csv"

New-Item -ItemType Directory -Force $distDir | Out-Null
New-Item -ItemType Directory -Force $workDir | Out-Null
New-Item -ItemType Directory -Force $specDir | Out-Null
New-Item -ItemType Directory -Force $cacheDir | Out-Null

$pythonCommand = Get-Command $Python -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
  throw "Python executable not found: $Python. Install Python 3.11+ or set ASTOCK_BACKTESTER_PYTHON."
}

if (Test-Path $targetExe) {
  Remove-Item -LiteralPath $targetExe -Force
}

Push-Location $repoRoot
try {
  $env:PYINSTALLER_CONFIG_DIR = $cacheDir
  & $pythonCommand.Source -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name astock-data-service `
    --distpath $distDir `
    --workpath $workDir `
    --specpath $specDir `
    --paths backend `
    --add-data "${watchlistCsv};astock_backtester\data" `
    --collect-all adata `
    --collect-all akshare `
    --collect-all curl_cffi `
    --hidden-import curl_cffi.requests `
    --hidden-import requests `
    --hidden-import bs4 `
    backend\astock_backtester\service.py
  if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
  }
} finally {
  Pop-Location
}

if (-not (Test-Path $targetExe)) {
  throw "astock-data-service.exe was not created"
}

if (-not (Test-Path $bundledNode)) {
  throw "Bundled Node.js executable not found: $bundledNode"
}
Copy-Item -LiteralPath $bundledNode -Destination $targetNodeExe -Force

if (-not (Test-Path $esbuildBin)) {
  throw "esbuild not found: $esbuildBin"
}
if (-not (Test-Path $jsdomXhrSyncWorker)) {
  throw "jsdom xhr-sync-worker.js not found: $jsdomXhrSyncWorker"
}
$cookieWorkerEntry = Join-Path $workDir "ths-cookie-worker-entry.cjs"
@'
const { JSDOM, VirtualConsole } = require("jsdom");

const THS_CHAMELEON_URL = "https://s.thsi.cn/js/chameleon/chameleon.1.7.min.1781803.js";
const THS_MARKET_BOARD_URL = "http://q.10jqka.com.cn/index/index/board";

(async () => {
  const timeoutMs = Math.max(200, Number(process.env.THS_COOKIE_TIMEOUT_MS || "1200"));
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("error", () => {});
  virtualConsole.on("warn", () => {});
  const dom = new JSDOM(
    `<!doctype html><html><head><script src="${THS_CHAMELEON_URL}"></script></head><body></body></html>`,
    {
      url: THS_MARKET_BOARD_URL,
      resources: "usable",
      runScripts: "dangerously",
      pretendToBeVisual: true,
      virtualConsole,
      userAgent: "Mozilla/5.0"
    }
  );
  const deadline = Date.now() + timeoutMs;
  let cookie = "";
  try {
    while (Date.now() < deadline) {
      cookie = dom.window.document.cookie || "";
      if (/(?:^|;\s*)v=/.test(cookie)) {
        process.stdout.write(cookie);
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 25));
    }
  } finally {
    dom.window.close();
  }
  process.exit(1);
})().catch(() => process.exit(1));
'@ | Set-Content -LiteralPath $cookieWorkerEntry -Encoding UTF8
& $bundledNode $esbuildBin $cookieWorkerEntry `
  --bundle `
  --platform=node `
  --format=cjs `
  --external:canvas `
  --external:./xhr-sync-worker.js `
  --outfile=$targetThsWorker
if ($LASTEXITCODE -ne 0) {
  throw "esbuild failed to create ths-cookie-worker.cjs"
}
if (-not (Test-Path $targetThsWorker)) {
  throw "ths-cookie-worker.cjs was not created"
}
Copy-Item -LiteralPath $jsdomXhrSyncWorker -Destination $targetXhrSyncWorker -Force
