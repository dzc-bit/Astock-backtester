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
