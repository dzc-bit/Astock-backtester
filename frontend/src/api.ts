import { invoke } from "@tauri-apps/api/core";
import type { BacktestResult, BacktestSettingsConfig, DatasetCoverage, StrategyConfig } from "./types";

type BackendResponse<T> = ({ ok: true } & T) | { ok: false; error: { code: string; message: string } };

const demoResult: BacktestResult = {
  metrics: {
    total_return_pct: 0.032,
    annualized_return_pct: 0.032,
    max_drawdown_pct: -0.018,
    win_rate_pct: 0.6,
    trade_count: 1,
    average_trade_return_pct: 0.011
  },
  equity_curve: [
    { trade_date: "2024-01-02", equity: 100000, cash: 100000, market_value: 0, drawdown_pct: 0 },
    { trade_date: "2024-01-05", equity: 102300, cash: 51000, market_value: 51300, drawdown_pct: 0 },
    { trade_date: "2024-01-08", equity: 103200, cash: 103200, market_value: 0, drawdown_pct: 0 }
  ],
  trades: [
    {
      symbol: "AAA",
      buy_signal_date: "2024-01-04",
      buy_date: "2024-01-05",
      sell_date: "2024-01-08",
      buy_price: 12,
      sell_price: 10.2,
      shares: 4000,
      buy_reason: ["float market cap 8800000000 in [1000000000, 30000000000]", "3d main net inflow 6000000 >= 3000000"],
      sell_reason: ["fixed holding days reached"],
      pnl: -7200,
      pnl_pct: -0.15
    }
  ],
  preflight_issues: []
};

function isTauriRuntime(): boolean {
  return Boolean((window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__);
}

async function callBackend<T>(payload: Record<string, unknown>): Promise<T> {
  if (!isTauriRuntime()) {
    if (payload.command === "coverage") {
      return {
        coverage: [
          { dataset: "daily_bars", symbols: 2, start_date: "2024-01-02", end_date: "2024-01-08", missing_rows: 0 },
          { dataset: "capital_flow", symbols: 2, start_date: "2024-01-02", end_date: "2024-01-08", missing_rows: 0 }
        ]
      } as T;
    }
    return { result: demoResult } as T;
  }
  const response = await invoke<BackendResponse<T>>("backend_command", { payload });
  if (!response.ok) {
    throw new Error(response.error.message);
  }
  return response;
}

export async function loadCoverage(cacheDir: string): Promise<DatasetCoverage[]> {
  const response = await callBackend<{ coverage: DatasetCoverage[] }>({ command: "coverage", cache_dir: cacheDir });
  return response.coverage;
}

export async function runConfiguredBacktest(strategy: StrategyConfig, settings: BacktestSettingsConfig): Promise<BacktestResult> {
  const response = await callBackend<{ result: BacktestResult }>({
    command: "run_backtest",
    strategy,
    settings,
    cache_dir: ".astock-cache"
  });
  return response.result;
}
