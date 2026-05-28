from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from threading import Lock, Thread
from uuid import uuid4

from astock_backtester.data.warehouse import Warehouse
from astock_backtester.models import SyncJobStatus


@dataclass
class SyncJobManager:
    warehouse: Warehouse
    provider: object

    def __post_init__(self) -> None:
        self._jobs: dict[str, SyncJobStatus] = {}
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

    def get_job(self, job_id: str) -> SyncJobStatus | None:
        with self._lock:
            status = self._jobs.get(job_id)
            return status.model_copy(deep=True) if status else None

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
            self._jobs[job_id] = status

    def _run_full_market_job(self, job_id: str, symbols: list[str], start_date: str, end_date: str) -> None:
        try:
            for symbol in symbols:
                self._mutate(job_id, current_symbol=symbol)
                try:
                    frame = self.provider.fetch_daily_bars(symbol, start_date, end_date)
                    imported_rows = 0
                    if not frame.empty:
                        self.warehouse.write_daily_bars(frame)
                        imported_rows = int(len(frame))
                    current = self.get_job(job_id)
                    if current:
                        self._mutate(
                            job_id,
                            completed_symbols=current.completed_symbols + 1,
                            imported_rows=current.imported_rows + imported_rows,
                        )
                except Exception as exc:
                    current = self.get_job(job_id)
                    if current:
                        self._mutate(job_id, failed_symbols=current.failed_symbols + 1)
                    self._append_error(job_id, f"{symbol}: {exc}")
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
