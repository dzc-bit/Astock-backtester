param(
  [Parameter(Mandatory = $true)][string]$Version,
  [Parameter(Mandatory = $true)][string]$AssetName,
  [Parameter(Mandatory = $true)][string]$Notes,
  [string]$Tag = "",
  [string]$ReleaseAssetName = "",
  [string]$OutputPath = "release-assets\latest.json"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

if (-not $Tag) {
  $Tag = "v$Version"
}

if (-not $ReleaseAssetName) {
  $ReleaseAssetName = $AssetName
}

$signaturePath = Join-Path $repoRoot "src-tauri\target\release\bundle\nsis\$AssetName.sig"
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
      url = "https://github.com/dzc-bit/Astock-backtester/releases/download/$Tag/$ReleaseAssetName"
    }
  }
}

$latestJson = $latest | ConvertTo-Json -Depth 5
$resolvedOutput = Join-Path $repoRoot $OutputPath
New-Item -ItemType Directory -Force (Split-Path -Parent $resolvedOutput) | Out-Null
[System.IO.File]::WriteAllText($resolvedOutput, $latestJson, [System.Text.UTF8Encoding]::new($false))
