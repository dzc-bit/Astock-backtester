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
from astock_backtester.data.providers import ADataProvider, CompositeProvider, HttpAStockProvider
from astock_backtester.data.news import MarketNewsProvider
from astock_backtester.data.realtime import RealtimeMarketProvider
from astock_backtester.data.risk import RiskAlertProvider
from astock_backtester.data.sync import SyncJobManager
from astock_backtester.data.warehouse import Warehouse
from astock_backtester.backtest_runner import run_configured_backtest
from astock_backtester.condition_parser import validate_condition_text, validate_exit_condition_text
from astock_backtester.models import BacktestSettings, StrategyConfig
from astock_backtester.recommended_strategies import recommended_strategies


class DataServiceState:
    def __init__(self, cache_dir: str | Path, port: int) -> None:
        self.cache = LocalCache(cache_dir)
        self.warehouse = Warehouse(cache_dir)
        self.provider = CompositeProvider([ADataProvider(), HttpAStockProvider()])
        self.sync_manager = SyncJobManager(warehouse=self.warehouse, provider=self.provider)
        self.realtime_provider = RealtimeMarketProvider(self.warehouse)
        self.news_provider = MarketNewsProvider()
        self.risk_provider = RiskAlertProvider(self.warehouse)
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

    def _send_ndjson_headers(self, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def _write_ndjson(self, payload: dict[str, Any]) -> None:
        self.wfile.write((json.dumps(payload, ensure_ascii=False, default=str) + "\n").encode("utf-8"))
        self.wfile.flush()

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _read_backtest_frame(self, settings: BacktestSettings) -> Any:
        frame = self.server.state.warehouse.read_daily_bars(
            start_date=str(settings.start_date),
            end_date=str(settings.end_date),
        )
        if frame.empty:
            frame = self.server.state.cache.read_daily_bars()
        if frame.empty:
            raise ValueError("No cached daily bars found. Import or fetch data before running a configured backtest.")
        return frame

    def _run_backtest_stream(self, payload: dict[str, Any]) -> None:
        self._send_ndjson_headers()
        try:
            self._write_ndjson({"type": "phase", "phase": "校验参数"})
            strategy = StrategyConfig.model_validate(payload["strategy"])
            settings = BacktestSettings.model_validate(payload["settings"])
            self._write_ndjson({"type": "phase", "phase": "读取本地数据"})
            frame = self._read_backtest_frame(settings)
            self._write_ndjson({"type": "phase", "phase": "计算指标与撮合交易"})

            def write_backtest_event(event: dict[str, Any]) -> None:
                payload = dict(event)
                trade = payload.get("trade")
                if trade is not None and hasattr(trade, "model_dump"):
                    payload["trade"] = trade.model_dump(mode="json")
                self._write_ndjson(payload)

            result = run_configured_backtest(
                frame,
                strategy,
                settings,
                on_event=write_backtest_event,
            )
            self._write_ndjson({"type": "phase", "phase": "生成结果"})
            self._write_ndjson({"type": "result", "result": result.model_dump(mode="json")})
        except Exception as exc:
            self.server.state.log("error", str(exc))
            self._write_ndjson({"type": "error", "message": str(exc), "code": "request_failed"})

    def do_OPTIONS(self) -> None:
        self._send_json({"ok": True})

    def do_GET(self) -> None:
        if self.path == "/ping":
            self._send_json({"ok": True})
            return
        if self.path == "/health":
            health = build_service_health(
                self.server.state.cache,
                self.server.state.warehouse,
                port=self.server.state.port,
            )
            self._send_json(health.model_dump(mode="json"))
            return
        if self.path == "/logs/recent":
            self._send_json({"items": list(self.server.state.logs)})
            return
        if self.path == "/realtime/market-snapshot":
            snapshot = self.server.state.realtime_provider.market_snapshot()
            self._send_json(snapshot.model_dump(mode="json"))
            return
        if self.path == "/market/news":
            news = self.server.state.news_provider.latest_news()
            self._send_json(news.model_dump(mode="json"))
            return
        if self.path == "/risk/alerts":
            alerts = self.server.state.risk_provider.current_alerts()
            self._send_json(alerts.model_dump(mode="json"))
            return
        if self.path == "/strategy/recommended":
            self._send_json(recommended_strategies(self.server.state.warehouse.coverage()).model_dump(mode="json"))
            return
        if self.path.startswith("/sync/jobs/"):
            job_id = self.path.rsplit("/", 1)[-1]
            job = self.server.state.sync_manager.get_job(job_id)
            if job is None:
                self._send_json({"code": "not_found", "message": job_id}, HTTPStatus.NOT_FOUND)
                return
            self._send_json({"job": job.model_dump(mode="json")})
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
            if self.path == "/sync/full-market":
                symbols = payload.get("symbols") or self.server.state.provider.list_symbols()
                if not symbols:
                    raise ValueError("No symbols available for full-market sync.")
                start_method = getattr(self.server.state.sync_manager, "start_full_market", None)
                if callable(start_method):
                    job = start_method(
                        symbols=symbols,
                        start_date=payload.get("start_date", "2015-01-01"),
                        end_date=payload["end_date"],
                    )
                else:
                    job = self.server.state.sync_manager.run_full_market(
                        symbols=symbols,
                        start_date=payload.get("start_date", "2015-01-01"),
                        end_date=payload["end_date"],
                    )
                self.server.state.log(
                    "info",
                    f"Full-market sync {job.status}: {job.completed_symbols}/{job.total_symbols} symbols",
                )
                self._send_json({"job": job.model_dump(mode="json")})
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
                frame = self._read_backtest_frame(settings)
                result = run_configured_backtest(frame, strategy, settings)
                self._send_json({"result": result.model_dump(mode="json")})
                return
            if self.path == "/run/backtest/stream":
                self._run_backtest_stream(payload)
                return
            if self.path == "/strategy/conditions/validate":
                mode = str(payload.get("mode", "entry")).strip().lower()
                if mode == "exit":
                    result = validate_exit_condition_text(str(payload.get("text", "")))
                else:
                    result = validate_condition_text(str(payload.get("text", "")))
                self._send_json(result.model_dump(mode="json"))
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
