from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from typing import Callable, Any
from threading import Lock, Thread
from uuid import uuid4

import pandas as pd

from astock_backtester.data.cache import LocalCache
from astock_backtester.data.operations import fetch_capital_flow_into_cache
from astock_backtester.data.warehouse import Warehouse
from astock_backtester.models import SyncJobStatus


@dataclass
class SyncJobManager:
    warehouse: Warehouse
    provider: object
    cache: LocalCache | None = None
    capital_flow_fetcher: Callable[[list[str], str, str], dict[str, Any]] | None = None
    full_market_batch_size: int = 25
    full_market_workers: int = 4
    full_market_write_batch_rows: int = 25_000
    capital_flow_batch_size: int = 20

    def __post_init__(self) -> None:
        self._jobs: dict[str, SyncJobStatus] = {}
        self._cancelled: set[str] = set()
        self._lock = Lock()

    def run_full_market(self, symbols: list[str], start_date: str, end_date: str) -> SyncJobStatus:
        status = SyncJobStatus(
            job_id=str(uuid4()),
            mode="full_market_bootstrap",
            status="running",
            total_symbols=len(symbols),
            start_date=date.fromisoformat(start_date),
            end_date=date.fromisoformat(end_date),
        )
        for symbol in symbols:
            status.current_symbol = symbol
            try:
                frame = self.provider.fetch_daily_bars(symbol, start_date, end_date)
                if not frame.empty:
                    self.warehouse.write_daily_bars(frame)
                    status.imported_rows += int(len(frame))
                    status.completed_symbols += 1
                else:
                    status.failed_symbols += 1
                    status.errors.append(f"{symbol}: provider returned no daily rows")
            except Exception as exc:
                status.failed_symbols += 1
                status.errors.append(f"{symbol}: {exc}")
        status.current_symbol = None
        status.status = "completed_with_errors" if status.failed_symbols else "completed"
        return status

    def start_full_market(self, symbols: list[str], start_date: str, end_date: str) -> SyncJobStatus:
        status = SyncJobStatus(
            job_id=str(uuid4()),
            mode="full_market_bootstrap",
            status="running",
            total_symbols=len(symbols),
            start_date=date.fromisoformat(start_date),
            end_date=date.fromisoformat(end_date),
        )
        self._store(status)
        thread = Thread(
            target=self._run_full_market_job,
            args=(status.job_id, list(symbols), start_date, end_date),
            daemon=True,
        )
        thread.start()
        return self.get_job(status.job_id) or status

    def start_capital_flow_backfill(self, symbols: list[str], start_date: str, end_date: str) -> SyncJobStatus:
        status = SyncJobStatus(
            job_id=str(uuid4()),
            mode="capital_flow_backfill",
            status="running",
            total_symbols=len(symbols),
            start_date=date.fromisoformat(start_date),
            end_date=date.fromisoformat(end_date),
        )
        self._store(status)
        thread = Thread(
            target=self._run_capital_flow_job,
            args=(status.job_id, list(symbols), start_date, end_date),
            daemon=True,
        )
        thread.start()
        return self.get_job(status.job_id) or status

    def get_job(self, job_id: str) -> SyncJobStatus | None:
        with self._lock:
            status = self._jobs.get(job_id)
            return status.model_copy(deep=True) if status else None

    def cancel_job(self, job_id: str) -> SyncJobStatus | None:
        with self._lock:
            status = self._jobs.get(job_id)
            if status is None:
                return None
            if status.status == "running":
                status.status = "cancelling"
                self._cancelled.add(job_id)
                self._jobs[job_id] = status
            return status.model_copy(deep=True)

    def _store(self, status: SyncJobStatus) -> None:
        with self._lock:
            self._jobs[status.job_id] = status.model_copy(deep=True)

    def _mutate(self, job_id: str, **updates: object) -> None:
        with self._lock:
            status = self._jobs[job_id]
            for key, value in updates.items():
                setattr(status, key, value)
            self._jobs[job_id] = status

    def _append_error(self, job_id: str, message: str) -> None:
        with self._lock:
            status = self._jobs[job_id]
            status.errors.append(message)
            status.last_error = message
            status.recent_failures = [*status.recent_failures, {"message": message}][-20:]
            self._jobs[job_id] = status

    def _is_cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancelled

    def _finish_cancelled(self, job_id: str) -> bool:
        if not self._is_cancel_requested(job_id):
            return False
        current = self.get_job(job_id)
        if current:
            current.current_symbol = None
            current.status = "cancelled"
            self._store(current)
        return True

    def _run_full_market_job(self, job_id: str, symbols: list[str], start_date: str, end_date: str) -> None:
        try:
            pending_frames: list[pd.DataFrame] = []
            pending_rows = 0
            for batch in _chunks(symbols, self.full_market_batch_size):
                if self._finish_cancelled(job_id):
                    return
                frames: list[pd.DataFrame] = []
                with ThreadPoolExecutor(max_workers=max(1, self.full_market_workers)) as executor:
                    futures = {
                        executor.submit(self.provider.fetch_daily_bars, symbol, start_date, end_date): symbol
                        for symbol in batch
                    }
                    for future in as_completed(futures):
                        symbol = futures[future]
                        self._mutate(job_id, current_symbol=symbol)
                        current = self.get_job(job_id)
                        if current:
                            self._mutate(job_id, processed_symbols=current.processed_symbols + 1)
                        try:
                            frame = future.result()
                        except Exception as exc:
                            current = self.get_job(job_id)
                            if current:
                                self._mutate(job_id, failed_symbols=current.failed_symbols + 1)
                            self._append_error(job_id, f"{symbol}: {exc}")
                            continue
                        if frame.empty:
                            current = self.get_job(job_id)
                            if current:
                                self._mutate(job_id, failed_symbols=current.failed_symbols + 1)
                            self._append_error(job_id, f"{symbol}: provider returned no daily rows")
                            continue
                        frames.append(frame)
                        current = self.get_job(job_id)
                        if current:
                            self._mutate(job_id, completed_symbols=current.completed_symbols + 1)
                if frames:
                    pending_frames.extend(frames)
                    pending_rows += sum(int(len(frame)) for frame in frames)
                    if pending_rows >= self.full_market_write_batch_rows:
                        pending_rows = self._flush_full_market_frames(job_id, pending_frames)
                if self._finish_cancelled(job_id):
                    if pending_frames:
                        self._flush_full_market_frames(job_id, pending_frames)
                    return
            if pending_frames:
                self._flush_full_market_frames(job_id, pending_frames)
            final = self.get_job(job_id)
            if final:
                final.current_symbol = None
                final.status = "completed_with_errors" if final.failed_symbols else "completed"
                self._store(final)
        except Exception as exc:
            current = self.get_job(job_id)
            if current:
                current.current_symbol = None
                current.status = "failed"
                current.errors.append(str(exc))
                self._store(current)

    def _flush_full_market_frames(self, job_id: str, frames: list[pd.DataFrame]) -> int:
        if not frames:
            return 0
        merged = pd.concat(frames, ignore_index=True)
        frames.clear()
        self.warehouse.write_daily_bars(merged)
        current = self.get_job(job_id)
        if current:
            self._mutate(job_id, imported_rows=current.imported_rows + int(len(merged)))
        return 0

    def _run_capital_flow_job(self, job_id: str, symbols: list[str], start_date: str, end_date: str) -> None:
        try:
            if self.cache is None or self.capital_flow_fetcher is None:
                raise RuntimeError("capital-flow job is not configured")
            skip_eastmoney = False
            for batch in _chunks(symbols, self.capital_flow_batch_size):
                if self._finish_cancelled(job_id):
                    return
                current_symbol = batch[0] if len(batch) == 1 else f"{batch[0]}..{batch[-1]}"
                self._mutate(job_id, current_symbol=current_symbol)
                try:
                    result = fetch_capital_flow_into_cache(
                        cache=self.cache,
                        warehouse=self.warehouse,
                        capital_flow_fetcher=lambda requested, start, end: _call_capital_flow_fetcher(
                            self.capital_flow_fetcher,
                            list(requested),
                            start,
                            end,
                            skip_eastmoney=skip_eastmoney,
                        ),
                        symbols=batch,
                        start_date=start_date,
                        end_date=end_date,
                        refresh_coverage=False,
                    )
                    if _diagnostics_should_skip_eastmoney(result.diagnostics):
                        skip_eastmoney = True
                    current = self.get_job(job_id)
                    if not current:
                        continue
                    failure_reasons = _capital_flow_failure_reasons(batch, result)
                    completed_symbols = _completed_capital_flow_symbols(batch, result, failure_reasons)
                    updates = {
                        "processed_symbols": current.processed_symbols + len(batch),
                        "completed_symbols": current.completed_symbols + len(completed_symbols),
                        "failed_symbols": current.failed_symbols + len(failure_reasons),
                        "skipped_symbols": current.skipped_symbols + len(result.skipped_symbols),
                        "imported_rows": current.imported_rows + result.imported_rows,
                        "returned_rows": current.returned_rows + result.returned_rows,
                    }
                    self._mutate(job_id, **updates)
                    for symbol, reason in failure_reasons.items():
                        self._append_failure(job_id, symbol, reason)
                except Exception as exc:
                    current = self.get_job(job_id)
                    if current:
                        self._mutate(
                            job_id,
                            processed_symbols=current.processed_symbols + len(batch),
                            failed_symbols=current.failed_symbols + len(batch),
                        )
                    self._append_error(job_id, f"{current_symbol}: {exc}")
                if self._finish_cancelled(job_id):
                    return
            final = self.get_job(job_id)
            if final:
                final.current_symbol = None
                final.status = "completed_with_errors" if final.failed_symbols else "completed"
                self._store(final)
        except Exception as exc:
            current = self.get_job(job_id)
            if current:
                current.current_symbol = None
                current.status = "failed"
                current.errors.append(str(exc))
                self._store(current)

    def _append_failure(self, job_id: str, symbol: str, message: str) -> None:
        with self._lock:
            status = self._jobs[job_id]
            error = f"{symbol}: {message}"
            status.errors.append(error)
            status.last_error = error
            status.recent_failures = [
                *status.recent_failures,
                {"symbol": symbol, "reason": message},
            ][-20:]
            self._jobs[job_id] = status


def _call_capital_flow_fetcher(
    fetcher: Callable[[list[str], str, str], dict[str, Any]],
    symbols: list[str],
    start_date: str,
    end_date: str,
    *,
    skip_eastmoney: bool,
) -> dict[str, Any]:
    try:
        return fetcher(symbols, start_date, end_date, skip_eastmoney=skip_eastmoney)  # type: ignore[misc]
    except TypeError as exc:
        if "skip_eastmoney" not in str(exc):
            raise
        return fetcher(symbols, start_date, end_date)


def _diagnostics_should_skip_eastmoney(diagnostics: list[dict[str, Any]]) -> bool:
    return any(
        item.get("code") == "provider_attempt_failed"
        and item.get("provider") == "eastmoney"
        and item.get("error_code") == "network_error"
        for item in diagnostics
    )


def _capital_flow_failure_reasons(
    batch: list[str],
    result: Any,
) -> dict[str, str]:
    selected = {str(symbol) for symbol in batch}
    reasons: dict[str, str] = {}
    for failure in getattr(result, "failures", []):
        if not isinstance(failure, dict):
            continue
        symbol = failure.get("symbol")
        if not symbol or str(symbol) not in selected:
            continue
        reasons.setdefault(str(symbol), _failure_message(failure))
    for diagnostic in getattr(result, "diagnostics", []):
        if not isinstance(diagnostic, dict) or diagnostic.get("code") != "date_coverage_shortfall":
            continue
        symbol = diagnostic.get("symbol")
        if not symbol or str(symbol) not in selected:
            continue
        reasons.setdefault(str(symbol), _failure_message(diagnostic))
    for symbol in getattr(result, "missing_symbols", []):
        symbol_text = str(symbol)
        if symbol_text in selected:
            reasons.setdefault(symbol_text, "capital-flow rows missing for requested range")
    return reasons


def _completed_capital_flow_symbols(
    batch: list[str],
    result: Any,
    failure_reasons: dict[str, str],
) -> list[str]:
    selected = {str(symbol) for symbol in batch}
    completed = {
        str(symbol)
        for symbol in [*getattr(result, "fetched_symbols", []), *getattr(result, "skipped_symbols", [])]
        if str(symbol) in selected
    }
    if not completed and not failure_reasons and _diagnostics_include_not_needed(getattr(result, "diagnostics", [])):
        completed = selected
    return sorted(symbol for symbol in completed if symbol not in failure_reasons)


def _diagnostics_include_not_needed(diagnostics: list[dict[str, Any]]) -> bool:
    return any(isinstance(item, dict) and item.get("code") == "capital_flow_backfill_not_needed" for item in diagnostics)


def _failure_message(item: dict[str, Any]) -> str:
    return str(item.get("error") or item.get("message") or item.get("code") or "capital-flow request failed")


def _chunks(items: list[str], size: int) -> list[list[str]]:
    chunk_size = max(1, size)
    return [items[index : index + chunk_size] for index in range(0, len(items), chunk_size)]


def _failure_symbols(failures: list[dict[str, Any]]) -> set[str]:
    return {
        str(item.get("symbol"))
        for item in failures
        if isinstance(item, dict) and item.get("symbol")
    }
