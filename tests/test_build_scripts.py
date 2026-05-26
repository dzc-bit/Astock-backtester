from __future__ import annotations

from pathlib import Path


def test_build_data_service_prefers_bundled_python_before_system_python():
    script = Path("scripts/build-data-service.ps1").read_text(encoding="utf-8")

    bundled_python = '.tools\\python-3.11.9\\python.exe'
    assert bundled_python in script
    assert script.index(bundled_python) < script.index('$Python = "python"')
