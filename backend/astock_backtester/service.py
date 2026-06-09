from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import deque
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
import requests

from astock_backtester.data.briefing import MarketBriefingProvider
from astock_backtester.data.cache import LocalCache
from astock_backtester.data.capital_flow_crawler import CapitalFlowCrawler
from astock_backtester.data.cls_finance import ClsFinanceProvider
from astock_backtester.data.importer import read_daily_bars
from astock_backtester.data.operations import (
    build_daily_bars_coverage,
    build_service_health,
    fetch_capital_flow_into_cache,
    fetch_daily_bars_into_cache,
    import_daily_bars_into_cache,
)
from astock_backtester.data.providers import ADataProvider, AkshareProvider, CompositeProvider, HttpAStockProvider
from astock_backtester.data.market_commentary import MarketCommentaryProvider, build_local_brief_commentary
from astock_backtester.data.news import MarketNewsProvider
from astock_backtester.data.news_summary import MarketNewsSummaryProvider
from astock_backtester.data.realtime import RealtimeMarketProvider, unavailable_market_snapshot
from astock_backtester.data.risk import RiskAlertProvider
from astock_backtester.data.sync import SyncJobManager
from astock_backtester.data.warehouse import Warehouse
from astock_backtester.backtest_runner import run_configured_backtest
from astock_backtester.condition_parser import validate_condition_text, validate_exit_condition_text
from astock_backtester.models import BacktestSettings, ClsFinanceResponse, StrategyConfig
from astock_backtester.recommended_strategies import recommended_strategies


class DataServiceState:
    def __init__(self, cache_dir: str | Path, port: int) -> None:
        self.cache = LocalCache(cache_dir)
        self.warehouse = Warehouse(cache_dir)
        self.akshare_provider = AkshareProvider()
        self.provider = CompositeProvider([ADataProvider(), self.akshare_provider, HttpAStockProvider()])
        self.capital_flow_crawler = CapitalFlowCrawler()
        self.sync_manager = SyncJobManager(
            warehouse=self.warehouse,
            provider=self.provider,
            cache=self.cache,
            capital_flow_fetcher=self._fetch_capital_flow,
        )
        self.realtime_provider = RealtimeMarketProvider(self.warehouse)
        self.news_provider = MarketNewsProvider()
        self.news_summary_provider = MarketNewsSummaryProvider(self.news_provider)
        self.briefing_provider = MarketBriefingProvider()
        self.finance_provider = ClsFinanceProvider()
        self.commentary_provider = MarketCommentaryProvider(
            self.realtime_provider,
            self.news_provider,
            briefing_provider=self.briefing_provider,
        )
        self.risk_provider = RiskAlertProvider(self.warehouse)
        self.port = port
        self.started_at = datetime.now(timezone.utc)
        self.instance_id = str(uuid4())
        self.process_id = os.getpid()
        self.executable_path = str(Path(sys.executable).resolve())
        self.executable_sha256 = self._hash_executable(self.executable_path)
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

    def _fetch_capital_flow(
        self,
        symbols: list[str],
        start_date: str,
        end_date: str,
        *,
        skip_eastmoney: bool = False,
    ) -> dict[str, Any]:
        try:
            return self.capital_flow_crawler.fetch_many_fund_flows(
                symbols,
                start_date,
                end_date,
                timeout=15,
                skip_eastmoney=skip_eastmoney,
            )
        except TypeError as exc:
            if "skip_eastmoney" not in str(exc):
                raise
            return self.capital_flow_crawler.fetch_many_fund_flows(
                symbols,
                start_date,
                end_date,
                timeout=15,
            )

    def _hash_executable(self, path: str) -> str | None:
        try:
            digest = hashlib.sha256()
            with open(path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        except OSError:
            return None

    def identity_payload(self) -> dict[str, Any]:
        return {
            "ok": True,
            "cache_path": str(self.cache.root.resolve()),
            "port": self.port,
            "process_id": self.process_id,
            "executable_path": self.executable_path,
            "executable_sha256": self.executable_sha256,
            "started_at": self.started_at.isoformat(),
            "instance_id": self.instance_id,
        }


def _retained_realtime_snapshot(provider: Any, exc: Exception):
    retained = getattr(provider, "_last_successful_snapshot", None)
    if retained is None:
        return None
    snapshot = retained.model_copy(deep=True)
    snapshot.status = "stale"
    snapshot.updated_at = datetime.now(timezone.utc)
    snapshot.source = (
        snapshot.source
        if snapshot.source.endswith("+service-retained-last-success")
        else f"{snapshot.source}+service-retained-last-success"
    )
    snapshot.message = "实时行情接口暂不可用，沿用最近成功行情快照。"
    snapshot.diagnostics = [
        *snapshot.diagnostics,
        f"实时行情接口失败：{exc}",
        f"沿用最近成功行情快照：{retained.updated_at.isoformat()}。",
    ]
    return snapshot


def _require_ohlc_rows(frame: pd.DataFrame) -> pd.DataFrame:
    ohlc_columns = ["open", "high", "low", "close"]
    if frame.empty or not all(column in frame for column in ohlc_columns):
        return pd.DataFrame()
    return frame.dropna(subset=ohlc_columns).reset_index(drop=True)


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
        self.wfile.write((json.dumps(self._jsonable(payload), ensure_ascii=False, default=str) + "\n").encode("utf-8"))
        self.wfile.flush()

    def _jsonable(self, value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, dict):
            return {key: self._jsonable(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._jsonable(item) for item in value]
        if isinstance(value, tuple):
            return [self._jsonable(item) for item in value]
        return value

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _read_backtest_frame(self, settings: BacktestSettings) -> Any:
        frame = self.server.state.warehouse.read_daily_bars(
            start_date=str(settings.start_date),
            end_date=str(settings.end_date),
            require_ohlc=True,
        )
        if frame.empty:
            frame = _require_ohlc_rows(self.server.state.cache.read_daily_bars())
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

    def _run_realtime_snapshot_stream(self) -> None:
        self._send_ndjson_headers()
        try:
            event_source = getattr(self.server.state.realtime_provider, "market_snapshot_events", None)
            if callable(event_source):
                for event in event_source():
                    self._write_ndjson(event)
            else:
                snapshot = self.server.state.realtime_provider.market_snapshot()
                self._write_ndjson({"type": "result", "snapshot": snapshot})
        except Exception as exc:
            self.server.state.log("error", f"realtime market snapshot stream failed: {exc}")
            snapshot = _retained_realtime_snapshot(self.server.state.realtime_provider, exc)
            if snapshot is None:
                snapshot = unavailable_market_snapshot(
                    "实时行情接口暂不可用，已保留页面最近数据。",
                    diagnostics=[f"实时行情接口失败：{exc}"],
                )
            self._write_ndjson({"type": "error", "message": str(exc), "code": "request_failed"})
            self._write_ndjson({"type": "result", "snapshot": snapshot})

    def do_OPTIONS(self) -> None:
        self._send_json({"ok": True})

    def do_GET(self) -> None:
        if self.path == "/ping":
            self._send_json({"ok": True})
            return
        if self.path == "/identity":
            self._send_json(self.server.state.identity_payload())
            return
        if self.path == "/health":
            health = build_service_health(
                self.server.state.cache,
                self.server.state.warehouse,
                port=self.server.state.port,
                process_id=self.server.state.process_id,
                executable_path=self.server.state.executable_path,
                executable_sha256=self.server.state.executable_sha256,
                started_at=self.server.state.started_at,
                instance_id=self.server.state.instance_id,
            )
            self._send_json(health.model_dump(mode="json"))
            return
        if self.path == "/logs/recent":
            self._send_json({"items": list(self.server.state.logs)})
            return
        if self.path == "/realtime/market-snapshot/stream":
            self._run_realtime_snapshot_stream()
            return
        if self.path == "/realtime/market-snapshot":
            try:
                snapshot = self.server.state.realtime_provider.market_snapshot()
            except Exception as exc:
                self.server.state.log("error", f"realtime market snapshot failed: {exc}")
                snapshot = _retained_realtime_snapshot(self.server.state.realtime_provider, exc)
                if snapshot is None:
                    snapshot = unavailable_market_snapshot(
                        "实时行情接口暂不可用，已保留页面最近数据。",
                        diagnostics=[f"实时行情接口失败：{exc}"],
                    )
            self._send_json(snapshot.model_dump(mode="json"))
            return
        if self.path == "/market/news":
            news = self.server.state.news_provider.latest_news()
            self._send_json(news.model_dump(mode="json"))
            return
        if self.path == "/market/commentary":
            try:
                commentary = self.server.state.commentary_provider.current_commentary()
            except (TimeoutError, RuntimeError, requests.RequestException) as exc:
                self.server.state.log("error", f"market commentary failed: {exc}")
                commentary = build_local_brief_commentary(
                    diagnostics=[f"行情评价接口失败：{exc}"],
                )
            self._send_json(commentary.model_dump(mode="json"))
            return
        if self.path == "/market/finance":
            try:
                finance = self.server.state.finance_provider.current_board()
            except Exception as exc:
                self.server.state.log("error", f"market finance failed: {exc}")
                finance = ClsFinanceResponse(
                    updated_at=datetime.now(timezone.utc),
                    diagnostics=[f"财联社看盘接口失败：{exc}"],
                )
            self._send_json(finance.model_dump(mode="json"))
            return
        if self.path == "/market/news-summary":
            summary = self.server.state.news_summary_provider.latest_summary()
            self._send_json(summary.model_dump(mode="json"))
            return
        if self.path == "/market/fupan":
            briefing = self.server.state.briefing_provider.latest_fupan()
            self._send_json(briefing.model_dump(mode="json"))
            return
        if self.path == "/market/zaopan":
            briefing = self.server.state.briefing_provider.latest_zaopan()
            self._send_json(briefing.model_dump(mode="json"))
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
                        self.server.state.warehouse,
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
                    warehouse=self.server.state.warehouse,
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
                    warehouse=self.server.state.warehouse,
                    fetcher=self._fetch_daily_bars_from_provider,
                    capital_flow_fetcher=self._fetch_capital_flow_from_crawler,
                    symbols=payload["symbols"],
                    start_date=payload["start_date"],
                    end_date=payload["end_date"],
                )
                for entry in result.logs:
                    self.server.state.log(entry.level, entry.message)
                self._send_json(result.model_dump(mode="json"))
                return
            if self.path == "/fetch/capital-flow":
                symbols = payload.get("symbols") or []
                if not symbols:
                    symbols = self._capital_flow_backfill_symbols()
                    if not symbols:
                        raise ValueError("No symbols available for capital-flow backfill.")
                    job = self.server.state.sync_manager.start_capital_flow_backfill(
                        symbols=symbols,
                        start_date=payload["start_date"],
                        end_date=payload["end_date"],
                    )
                    self.server.state.log(
                        "info",
                        f"Capital-flow backfill {job.status}: {job.completed_symbols}/{job.total_symbols} symbols",
                    )
                    self._send_json(
                        {
                            "status": "ok",
                            "imported_rows": 0,
                            "returned_rows": 0,
                            "requested_symbols": symbols,
                            "fetched_symbols": [],
                            "missing_symbols": [],
                            "skipped_symbols": [],
                            "coverage": [
                                item.model_dump(mode="json")
                                for item in self.server.state.warehouse.coverage()
                            ],
                            "logs": [
                                {
                                    "level": "info",
                                    "message": f"Capital-flow backfill started for {len(symbols)} symbols",
                                }
                            ],
                            "diagnostics": [
                                {
                                    "code": "capital_flow_backfill_job_started",
                                    "source": "capital_flow_crawler",
                                    "job_id": job.job_id,
                                    "requested_symbols": len(symbols),
                                }
                            ],
                            "failures": [],
                            "job": job.model_dump(mode="json"),
                        }
                    )
                    return
                result = fetch_capital_flow_into_cache(
                    cache=self.server.state.cache,
                    warehouse=self.server.state.warehouse,
                    capital_flow_fetcher=self._fetch_capital_flow_from_crawler,
                    symbols=symbols,
                    start_date=payload["start_date"],
                    end_date=payload["end_date"],
                )
                for entry in result.logs:
                    self.server.state.log(entry.level, entry.message)
                self._send_json(result.model_dump(mode="json"))
                return
            if self.path.startswith("/sync/jobs/") and self.path.endswith("/cancel"):
                job_id = self.path.removesuffix("/cancel").rsplit("/", 1)[-1]
                cancel_method = getattr(self.server.state.sync_manager, "cancel_job", None)
                if not callable(cancel_method):
                    self._send_json({"code": "not_found", "message": job_id}, HTTPStatus.NOT_FOUND)
                    return
                job = cancel_method(job_id)
                if job is None:
                    self._send_json({"code": "not_found", "message": job_id}, HTTPStatus.NOT_FOUND)
                    return
                self.server.state.log("info", f"Sync job cancellation requested: {job_id}")
                self._send_json({"job": job.model_dump(mode="json")})
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

    def _fetch_daily_bars_from_provider(self, symbols: list[str], start_date: str, end_date: str) -> pd.DataFrame:
        frames = [
            frame
            for symbol in symbols
            if not (frame := self.server.state.provider.fetch_daily_bars(symbol, start_date, end_date)).empty
        ]
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    def _fetch_capital_flow_from_crawler(self, symbols: list[str], start_date: str, end_date: str) -> dict[str, Any]:
        return self.server.state._fetch_capital_flow(symbols, start_date, end_date)

    def _capital_flow_backfill_symbols(self) -> list[str]:
        symbols: set[str] = set()
        try:
            symbols.update(str(symbol) for symbol in self.server.state.provider.list_symbols())
        except Exception:
            pass
        frame = self.server.state.warehouse.read_daily_bars()
        if not frame.empty and "symbol" in frame:
            symbols.update(str(symbol) for symbol in frame["symbol"].dropna().astype(str).unique())
        return sorted(symbol for symbol in symbols if symbol)


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
