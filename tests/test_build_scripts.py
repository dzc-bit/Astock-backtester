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
    assert 'Join-Path $distDir "node.exe"' in script
    assert 'Join-Path $distDir "ths-cookie-worker.cjs"' in script
    assert 'Join-Path $distDir "xhr-sync-worker.js"' in script
    assert "--distpath $distDir" in script


def test_build_data_service_bundles_ths_cookie_worker_for_desktop_score():
    script = Path("scripts/build-data-service.ps1").read_text(encoding="utf-8")

    assert "esbuild" in script
    assert "jsdom" in script
    assert "ths-cookie-worker.cjs" in script
    assert "xhr-sync-worker.js" in script


def test_build_data_service_collects_curl_cffi_native_dependencies():
    script = Path("scripts/build-data-service.ps1").read_text(encoding="utf-8")

    assert "--collect-all curl_cffi" in script
    assert "--hidden-import curl_cffi.requests" in script


def test_tauri_bundle_builds_data_service_before_packaging():
    config = json.loads(Path("src-tauri/tauri.conf.json").read_text(encoding="utf-8"))

    before_build = config["build"]["beforeBuildCommand"]
    assert before_build == (
        ".\\.tools\\node-v20.18.1-win-x64\\npm.cmd run build && "
        ".\\.tools\\node-v20.18.1-win-x64\\npm.cmd run build:data-service"
    )
    assert config["bundle"]["resources"] == ["bin"]


def test_vite_config_resolves_real_frontend_root_from_config_dir():
    config = Path("frontend/vite.config.ts").read_text(encoding="utf-8")

    assert 'const frontendRoot = realpathSync(fileURLToPath(new URL(".", import.meta.url)));' in config
    assert "root: frontendRoot" in config
    assert 'outDir: resolve(frontendRoot, "../dist")' in config


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


def test_service_manager_resolves_release_cache_dir_from_d_drive_workspace_data_dir():
    source = Path("src-tauri/src/service_manager.rs").read_text(encoding="utf-8")

    assert 'join("运行产物").join("本地数据仓")' in source
    assert "app_local_data_dir()" not in source
