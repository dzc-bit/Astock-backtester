import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import type { RealtimeMarketSnapshot } from "../types";
import { MarketDashboard } from "./MarketDashboard";

function buildSnapshot(overrides: Partial<RealtimeMarketSnapshot> = {}): RealtimeMarketSnapshot {
  return {
    status: "stale",
    source: "test",
    updated_at: "2026-05-27T15:10:00+08:00",
    indexes: [],
    breadth: { up: 3200, down: 1700, flat: 200, total: 5100, source: "test" },
    strong_sectors: [
      { name: "半导体", change_pct: 0.036, leading_symbol: "688001", source: "test" },
      { name: "机器人", change_pct: 0.024, leading_symbol: "300024", source: "test" }
    ],
    yesterday_strong_sectors: [
      { name: "半导体", change_pct: 0.031, leading_symbol: "688001", source: "local-yesterday-group" }
    ],
    message: "test",
    ...overrides
  };
}

it("keeps the realtime market panel focused on structured market data", () => {
  render(<MarketDashboard snapshot={buildSnapshot()} />);

  expect(screen.getByText("红绿家数")).toBeInTheDocument();
  expect(screen.getByText("强势板块")).toBeInTheDocument();
  expect(screen.getByText("昨日强势追踪")).toBeInTheDocument();
  expect(screen.queryByText(/收盘后板块解读：/)).not.toBeInTheDocument();
  expect(screen.queryByText(/行情评价：/)).not.toBeInTheDocument();
});

it("does not mix commentary into live intraday snapshots", () => {
  render(
    <MarketDashboard
      snapshot={buildSnapshot({
        status: "live",
        updated_at: "2026-05-27T14:10:00+08:00"
      })}
    />
  );

  expect(screen.queryByText(/收盘后板块解读：/)).not.toBeInTheDocument();
  expect(screen.queryByText(/行情评价：/)).not.toBeInTheDocument();
});

it("shows an empty yesterday-sector result after its background tracking completes", () => {
  render(
    <MarketDashboard
      snapshot={buildSnapshot({
        yesterday_strong_sectors: [],
        diagnostics: ["eastmoney-yesterday-limit-up tracking loaded pool_date=2026-05-26, as_of_date=2026-05-27, sectors=0."]
      })}
    />
  );

  expect(screen.getByText("暂无昨日强势板块")).toBeInTheDocument();
  expect(screen.queryByText("正在加载昨日板块数据")).not.toBeInTheDocument();
});

it("shows refresh fallback metadata while preserving the last successful snapshot", () => {
  render(
    <MarketDashboard
      snapshot={buildSnapshot({
        status: "live",
        indexes: [
          {
            symbol: "sh000001",
            name: "上证指数",
            last: 3120.5,
            previous_close: 3100,
            change: 20.5,
            change_pct: 0.0066,
            source: "test",
            updated_at: "2026-06-05T14:50:00+08:00"
          }
        ]
      })}
      refreshMeta={{
        phase: "post_close",
        status: "using_last_success",
        message: "实时接口暂不可用，使用最近数据",
        last_success_at: "2026-06-05T14:50:00+08:00",
        last_error: "timeout",
        next_refresh_ms: 300_000
      }}
    />
  );

  expect(screen.getByText("上证指数")).toBeInTheDocument();
  expect(screen.getByText("3,120.5")).toBeInTheDocument();
  expect(screen.getByText("使用最近数据")).toBeInTheDocument();
  expect(screen.getByText(/收盘后/)).toBeInTheDocument();
  expect(screen.getByText(/实时接口暂不可用/)).toBeInTheDocument();
});

it("separates successful realtime sources from failed attempted sources", () => {
  render(
    <MarketDashboard
      snapshot={buildSnapshot({
        status: "live",
        source: "ashare-sina+cls-quote-breadth+cls-hot-plate",
        indexes: [
          {
            symbol: "sh000001",
            name: "上证指数",
            last: 4010.03,
            previous_close: 3959.34,
            change: 50.69,
            change_pct: 0.0128,
            source: "ashare-sina",
            updated_at: "2026-06-09T15:30:39+08:00"
          }
        ],
        breadth: null,
        strong_sectors: [],
        diagnostics: ["cls-hot-plate strong-sector source returned no valid rows."]
      })}
    />
  );

  expect(screen.getByText(/成功来源 指数 Ashare\/Sina/)).toBeInTheDocument();
  expect(screen.getByText(/尝试未成功 cls-hot-plate strong-sector source returned no valid rows\./)).toBeInTheDocument();
  expect(screen.queryByText(/来源 ashare-sina\+cls-quote-breadth\+cls-hot-plate/)).not.toBeInTheDocument();
});
