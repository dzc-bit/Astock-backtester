from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import uuid4

from astock_backtester.data.warehouse import Warehouse
from astock_backtester.models import SyncJobStatus


@dataclass
class SyncJobManager:
    warehouse: Warehouse
    provider: object

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
