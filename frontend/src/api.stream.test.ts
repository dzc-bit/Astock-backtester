import { afterEach, describe, expect, it, vi } from "vitest";
import { runBacktestStreamWithDataService } from "./api";
import type { BacktestResult, BacktestSettingsConfig, StrategyConfig, Trade } from "./types";

const strategy: StrategyConfig = {
  name: "测试策略",
  market_filters: [],
  entry_groups: [],
  exit_rules: [],
  score_threshold: null
};

const settings: BacktestSettingsConfig = {
  start_date: "2024-01-02",
  end_date: "2024-01-08",
  initial_cash: 100000,
  stock_pool: "all",
  custom_symbols: [],
  benchmark_symbol: "000300.SH",
  position_sizing_mode: "fixed_ratio",
  position_size_pct: 0.5,
  fixed_holding_days: 3,
  take_profit_pct: 0.08,
  stop_loss_pct: -0.05,
  max_positions: 2,
  max_daily_buys: 1,
  fee_rate: 0.0003,
  stamp_tax_rate: 0.0005,
  slippage_rate: 0.0005,
  min_listing_days: 60,
  exclude_st: true,
  conservative_execution: true
};

const blockedTrade: Trade = {
  symbol: "AAA",
  buy_signal_date: "2024-01-04",
  buy_date: "2024-01-05",
  buy_price: 12,
  shares: 0,
  planned_amount: 50000,
  buy_amount: 0,
  target_position_pct: 0.5,
  actual_position_pct: 0,
  buy_reason: ["涨停无法买入"],
  sell_reason: [],
  blocked_reason: "limit_up"
};

const result: BacktestResult = {
  metrics: {
    total_return_pct: 0,
    annualized_return_pct: 0,
    max_drawdown_pct: 0,
    win_rate_pct: 0,
    trade_count: 0,
    average_trade_return_pct: 0,
    average_position_pct: 0,
    max_position_pct: 0
  },
  equity_curve: [],
  trades: [blockedTrade],
  preflight_issues: []
};

function jsonLineStream(lines: string[]): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      const encoder = new TextEncoder();
      controller.enqueue(encoder.encode(`${lines.join("\n")}\n`));
      controller.close();
    }
  });
}

describe("backtest stream", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    Reflect.deleteProperty(window, "__TAURI_INTERNALS__");
  });

  it("forwards blocked trade events to the trade handler", async () => {
    Object.defineProperty(window, "__TAURI_INTERNALS__", {
      configurable: true,
      value: {}
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          jsonLineStream([
            JSON.stringify({ type: "trade_blocked", trade: blockedTrade }),
            JSON.stringify({ type: "result", result })
          ]),
          { status: 200 }
        )
      )
    );
    const trades: Trade[] = [];

    await expect(
      runBacktestStreamWithDataService("http://127.0.0.1:9010", strategy, settings, {
        onTrade: (trade) => trades.push(trade)
      })
    ).resolves.toEqual(result);

    expect(trades).toEqual([blockedTrade]);
  });
});
