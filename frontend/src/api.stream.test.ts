import { afterEach, describe, expect, it, vi } from "vitest";
import { loadRealtimeMarketSnapshotStream, runBacktestStreamWithDataService } from "./api";
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

describe("realtime market snapshot stream", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    Reflect.deleteProperty(window, "__TAURI_INTERNALS__");
  });

  it("emits renderable partial snapshots before the final realtime result", async () => {
    Object.defineProperty(window, "__TAURI_INTERNALS__", {
      configurable: true,
      value: {}
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          jsonLineStream([
            JSON.stringify({
              type: "indexes",
              updated_at: "2026-05-27T10:30:00Z",
              market_phase: "trading",
              indexes: [{ symbol: "sh000001", name: "上证指数", last: 3100, source: "fake-live" }]
            }),
            JSON.stringify({
              type: "breadth",
              updated_at: "2026-05-27T10:30:01Z",
              market_phase: "trading",
              breadth: { up: 3200, down: 1700, flat: 200, total: 5100, source: "fake-live" }
            }),
            JSON.stringify({
              type: "sectors",
              updated_at: "2026-05-27T10:30:02Z",
              market_phase: "trading",
              strong_sectors: [{ name: "半导体", change_pct: 0.036, leading_symbol: "688001", source: "fake-live" }],
              yesterday_strong_sectors: [{ name: "机器人", change_pct: 0.022, leading_symbol: "300024", source: "fake-yesterday" }]
            }),
            JSON.stringify({
              type: "result",
              snapshot: {
                status: "live",
                source: "fake-live",
                updated_at: "2026-05-27T10:30:03Z",
                market_phase: "trading",
                indexes: [{ symbol: "sh000001", name: "上证指数", last: 3100, source: "fake-live" }],
                breadth: { up: 3200, down: 1700, flat: 200, total: 5100, source: "fake-live" },
                strong_sectors: [{ name: "半导体", change_pct: 0.036, leading_symbol: "688001", source: "fake-live" }],
                yesterday_strong_sectors: [{ name: "机器人", change_pct: 0.022, leading_symbol: "300024", source: "fake-yesterday" }],
                message: "ok",
                diagnostics: []
              }
            })
          ]),
          { status: 200 }
        )
      )
    );
    const partials: string[] = [];

    const result = await loadRealtimeMarketSnapshotStream("http://127.0.0.1:9010", {
      onSnapshot: (snapshot) => {
        partials.push(`${snapshot.indexes.length}/${snapshot.breadth?.total ?? 0}/${snapshot.strong_sectors.length}`);
      }
    });

    expect(result.status).toBe("live");
    expect(partials).toEqual(["1/0/0", "1/5100/0", "1/5100/1", "1/5100/1"]);
  });
});
