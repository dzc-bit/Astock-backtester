from __future__ import annotations

import json
from pathlib import Path


def test_build_data_service_prefers_bundled_python_before_system_python():
    script = Path("scripts/build-data-service.ps1").read_text(encoding="utf-8")

    bundled_python = '.tools\\python-3.11.9\\python.exe'
    assert bundled_python in script
    assert script.index(bundled_python) < script.index('$Python = "python"')


def test_build_data_service_targets_tauri_bin_executable():
    script = Path("scripts/build-data-service.ps1").read_text(encoding="utf-8")

    assert 'Join-Path $repoRoot "src-tauri\\bin"' in script
    assert 'Join-Path $distDir "astock-data-service.exe"' in script
    assert "--distpath $distDir" in script


def test_tauri_bundle_builds_data_service_before_packaging():
    config = json.loads(Path("src-tauri/tauri.conf.json").read_text(encoding="utf-8"))

    assert config["build"]["beforeBuildCommand"] == "npm run build && npm run build:data-service"
    assert config["bundle"]["resources"] == ["bin"]


def test_write_latest_json_supports_distinct_release_asset_name():
    script = Path("scripts/write-latest-json.ps1").read_text(encoding="utf-8")

    assert "[string]$ReleaseAssetName = \"\"" in script
    assert "if (-not $ReleaseAssetName)" in script
    assert "$ReleaseAssetName = $AssetName" in script
    assert "url = \"https://github.com/dzc-bit/Astock-backtester/releases/download/$Tag/$ReleaseAssetName\"" in script


def test_service_manager_defines_and_uses_packaged_sidecar_relative_helper():
    source = Path("src-tauri/src/service_manager.rs").read_text(encoding="utf-8")

    assert "fn packaged_service_relative_path() -> PathBuf" in source
    assert "resource_dir.join(packaged_service_relative_path())" in source


def test_service_manager_resolves_release_cache_dir_from_app_local_data():
    source = Path("src-tauri/src/service_manager.rs").read_text(encoding="utf-8")

    assert "app_local_data_dir()" in source
