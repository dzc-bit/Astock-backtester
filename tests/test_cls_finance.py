from __future__ import annotations

import sys
from pathlib import Path

from astock_backtester.data.cls_finance import (
    _resolve_node_executable,
    _resolve_ths_cookie_worker,
    _subprocess_startup_kwargs,
)


def test_resolves_ths_cookie_runtime_next_to_frozen_sidecar(tmp_path, monkeypatch):
    sidecar = tmp_path / "astock-data-service.exe"
    node = tmp_path / "node.exe"
    worker = tmp_path / "ths-cookie-worker.cjs"
    sidecar.write_text("", encoding="utf-8")
    node.write_text("", encoding="utf-8")
    worker.write_text("", encoding="utf-8")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(sidecar))

    assert _resolve_node_executable() == str(node)
    assert _resolve_ths_cookie_worker() == worker


def test_ths_cookie_worker_hides_console_on_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")

    kwargs = _subprocess_startup_kwargs()

    assert kwargs["creationflags"] == 0x08000000
    assert kwargs["startupinfo"].dwFlags & 1
    assert kwargs["startupinfo"].wShowWindow == 0
