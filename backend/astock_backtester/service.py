from __future__ import annotations

import argparse
import json
from collections import deque
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from astock_backtester.data.astock_adapter import AStockDataAdapter
from astock_backtester.data.cache import LocalCache
from astock_backtester.data.importer import read_daily_bars
from astock_backtester.data.operations import (
    build_daily_bars_coverage,
    build_service_health,
    fetch_daily_bars_into_cache,
    import_daily_bars_into_cache,
)
from astock_backtester.backtest_runner import run_configured_backtest
from astock_backtester.models import BacktestSettings, StrategyConfig


class DataServiceState:
    def __init__(self, cache_dir: str | Path, port: int) -> None:
        self.cache = LocalCache(cache_dir)
        self.port = port
        self.logs: deque[dict[str, str]] = deque(maxlen=100)
        self.log("info", "local data service started")

    def log(self, level: str, message: str) -> None:
        self.logs.appendleft(
            {
                "level": level,
                "message": message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )


class DataServiceServer(ThreadingHTTPServer):
    def __init__(self, host: str, port: int, cache_dir: str | Path) -> None:
        super().__init__((host, port), DataServiceHandler)
        self.state = DataServiceState(cache_dir, self.server_address[1])


class DataServiceHandler(BaseHTTPRequestHandler):
    server: DataServiceServer

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_OPTIONS(self) -> None:
        self._send_json({"ok": True})

    def do_GET(self) -> None:
        if self.path == "/health":
            health = build_service_health(self.server.state.cache, port=self.server.state.port)
            self._send_json(health.model_dump(mode="json"))
            return
        if self.path == "/logs/recent":
            self._send_json({"items": list(self.server.state.logs)})
            return
        self._send_json({"code": "not_found", "message": self.path}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        try:
            payload = self._read_json()
            if self.path == "/coverage/daily-bars":
                self._send_json(
                    build_daily_bars_coverage(
                        self.server.state.cache,
                        symbols=payload.get("symbols"),
                        start_date=payload.get("start_date"),
                        end_date=payload.get("end_date"),
                    ).model_dump(mode="json")
                )
                return
            if self.path == "/import/daily-bars":
                if payload.get("source") == "sample":
                    from astock_backtester.sample_data import sample_daily_bars

                    frame = sample_daily_bars()
                else:
                    frame = read_daily_bars(payload["path"])
                result = import_daily_bars_into_cache(
                    cache=self.server.state.cache,
                    frame=frame,
                    source=str(payload.get("source", "file")),
                )
                for entry in result.logs:
                    self.server.state.log(entry.level, entry.message)
                self._send_json(result.model_dump(mode="json"))
                return
            if self.path == "/fetch/daily-bars":
                result = fetch_daily_bars_into_cache(
                    cache=self.server.state.cache,
                    fetcher=AStockDataAdapter.from_http_sources().fetch_daily_bars,
                    symbols=payload["symbols"],
                    start_date=payload["start_date"],
                    end_date=payload["end_date"],
                )
                for entry in result.logs:
                    self.server.state.log(entry.level, entry.message)
                self._send_json(result.model_dump(mode="json"))
                return
            if self.path == "/run/backtest":
                strategy = StrategyConfig.model_validate(payload["strategy"])
                settings = BacktestSettings.model_validate(payload["settings"])
                frame = self.server.state.cache.read_daily_bars()
                if frame.empty:
                    raise ValueError("No cached daily bars found. Import or fetch data before running a configured backtest.")
                result = run_configured_backtest(frame, strategy, settings)
                self._send_json({"result": result.model_dump(mode="json")})
                return
            self._send_json({"code": "not_found", "message": self.path}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.server.state.log("error", str(exc))
            self._send_json({"code": "request_failed", "message": str(exc)}, HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: object) -> None:
        return


def create_server(host: str, port: int, cache_dir: str | Path) -> DataServiceServer:
    return DataServiceServer(host, port, cache_dir)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--cache-dir", required=True)
    args = parser.parse_args()
    server = create_server(args.host, args.port, args.cache_dir)
    server.serve_forever()


if __name__ == "__main__":
    main()
