from __future__ import annotations

import json
import threading
import time
from urllib.request import ProxyHandler, Request, build_opener

from astock_backtester.service import create_server

# Loopback traffic must never be routed through developer/system proxies.
_OPENER = build_opener(ProxyHandler({}))


def _request_json(method: str, url: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with _OPENER.open(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _request_json_allow_error(method: str, url: str, payload: dict | None = None) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with _OPENER.open(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        status = getattr(exc, "code", 500)
        body = getattr(exc, "read", None)
        if callable(body):
            return int(status), json.loads(body().decode("utf-8"))
        raise


def _request_ndjson(url: str, payload: dict) -> list[dict]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    with _OPENER.open(request, timeout=10) as response:
        return [json.loads(line) for line in response.read().decode("utf-8").splitlines() if line.strip()]


def _start_server(tmp_path):
    # Use a warehouse-style subdirectory so AI user data (config/sessions) lands
    # inside tmp_path itself, never in the shared pytest root.
    warehouse = tmp_path / "本地数据仓"
    warehouse.mkdir(exist_ok=True)
    server = create_server(host="127.0.0.1", port=0, cache_dir=warehouse)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)
    return server, thread, server.server_address[1]


def test_ai_status_reports_unconfigured_by_default(tmp_path):
    server, thread, port = _start_server(tmp_path)
    try:
        status = _request_json("GET", f"http://127.0.0.1:{port}/ai/status")
        assert status["configured"] is False
        assert status["base_url"] == ""
        assert status["knowledge_documents"] >= 3
        assert len(status["tool_names"]) >= 8
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_ai_config_roundtrip_masks_key(tmp_path):
    server, thread, port = _start_server(tmp_path)
    try:
        status, saved = _request_json_allow_error(
            "POST",
            f"http://127.0.0.1:{port}/ai/config",
            {"base_url": "https://api.example.com/v1", "api_key": "sk-secret-123456", "model": "demo"},
        )
        assert status == 200
        assert saved["configured"] is True
        assert "sk-secret-123456" not in json.dumps(saved)
        view = _request_json("GET", f"http://127.0.0.1:{port}/ai/config")
        assert view["api_key_masked"].endswith("3456")
        assert view["configured"] is True

        # empty key keeps existing secret
        updated = _request_json("POST", f"http://127.0.0.1:{port}/ai/config", {"base_url": "https://api2.example.com/v1", "model": "m2"})
        assert updated["configured"] is True
        status_payload = _request_json("GET", f"http://127.0.0.1:{port}/ai/status")
        assert status_payload["configured"] is True
        assert status_payload["base_url"] == "https://api2.example.com/v1"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_ai_config_reveal_returns_full_key(tmp_path):
    server, thread, port = _start_server(tmp_path)
    try:
        _request_json(
            "POST",
            f"http://127.0.0.1:{port}/ai/config",
            {"base_url": "https://api.example.com/v1", "api_key": "sk-reveal-me-9876", "model": "demo"},
        )
        revealed = _request_json("GET", f"http://127.0.0.1:{port}/ai/config/reveal")
        assert revealed == {"api_key": "sk-reveal-me-9876"}
        status = _request_json("GET", f"http://127.0.0.1:{port}/ai/status")
        assert status["memory_count"] == 0
        assert len(status["tool_names"]) >= 11  # 本地 + a-stock-data + 查询/写 + 知识检索
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_ai_chat_stream_without_config_returns_error_event(tmp_path):
    server, thread, port = _start_server(tmp_path)
    try:
        events = _request_ndjson(
            f"http://127.0.0.1:{port}/ai/chat/stream",
            {"message": "帮我看看 600519"},
        )
        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert events[0]["code"] == "ai_not_configured"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_ai_chat_stream_with_stubbed_model(tmp_path, monkeypatch):
    server, thread, port = _start_server(tmp_path)
    _request_json(
        "POST",
        f"http://127.0.0.1:{port}/ai/config",
        {"base_url": "http://127.0.0.1:9", "api_key": "sk-test", "model": "demo"},
    )
    scripted_events = [
        {"type": "phase", "phase": "思考中（第 1/8 步）"},
        {"type": "token", "text": "本地数据正常。"},
    ]

    class StubAgent:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def run(self, *, session, user_message, system_prompt, max_steps, context=None, on_event):
            for event in scripted_events:
                on_event(event)
            session["display"].append({"role": "assistant", "content": "本地数据正常。", "tool_steps": [], "ts": "now"})
            return {}

    ai_service = server.state.ai_service()  # 先实例化，再替换实例上的 agent
    monkeypatch.setattr(ai_service, "_agent", StubAgent())
    try:
        events = _request_ndjson(f"http://127.0.0.1:{port}/ai/chat/stream", {"message": "行情如何"})
        types = [event["type"] for event in events]
        assert types[0] == "session"
        assert "phase" in types and "token" in types
        assert types[-1] == "result"
        result = events[-1]
        assert result["display"][-1]["content"] == "本地数据正常。"
        assert result["session_id"]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_ai_events_stream_heartbeat_and_publish(tmp_path, monkeypatch):
    from astock_backtester.ai import facade

    monkeypatch.setattr(facade, "HEARTBEAT_INTERVAL_SECONDS", 0.2)
    server, thread, port = _start_server(tmp_path)
    try:
        received: list[dict] = []

        def reader() -> None:
            request = Request(f"http://127.0.0.1:{port}/ai/events/stream", method="GET")
            with _OPENER.open(request, timeout=10) as response:
                while len(received) < 2:
                    line = response.readline()
                    if not line:
                        break
                    received.append(json.loads(line.decode("utf-8")))

        reader_thread = threading.Thread(target=reader, daemon=True)
        reader_thread.start()
        time.sleep(0.4)
        ai_service = server.state.ai_service()
        ai_service._broker.publish({"type": "data_fresh", "module": "news"})
        reader_thread.join(timeout=5)
        types = [event["type"] for event in received]
        assert "data_fresh" in types
        assert "heartbeat" in types
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_ai_chat_request_validation_rejects_empty_message(tmp_path):
    server, thread, port = _start_server(tmp_path)
    try:
        status, payload = _request_json_allow_error("POST", f"http://127.0.0.1:{port}/ai/chat/stream", {"message": ""})
        assert status == 400
        assert payload["code"] == "validation_error"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_ai_chat_stream_bad_session_id_isolated(tmp_path):
    server, thread, port = _start_server(tmp_path)
    try:
        # 未配置 → 仍是 ai_not_configured；session_id 清洗后不落盘
        events = _request_ndjson(
            f"http://127.0.0.1:{port}/ai/chat/stream",
            {"message": "x", "session_id": "../escape"},
        )
        assert events[0]["code"] == "ai_not_configured"
    finally:
        server.shutdown()
        thread.join(timeout=5)
