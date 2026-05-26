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
