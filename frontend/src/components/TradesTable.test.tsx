import { render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import type { Trade } from "../types";
import { TradesTable } from "./TradesTable";

function buildTrade(overrides: Partial<Trade> = {}): Trade {
  return {
    symbol: "600519",
    buy_signal_date: "2026-06-01",
    buy_date: "2026-06-02",
    sell_date: "2026-06-05",
    buy_price: 100,
    sell_price: 106,
    shares: 100,
    planned_amount: 10000,
    buy_amount: 10000,
    sell_amount: 10600,
    target_position_pct: 0.5,
    actual_position_pct: 0.5,
    buy_reason: ["close above MA20"],
    sell_reason: ["fixed holding days reached"],
    blocked_reason: null,
    pnl: 600,
    pnl_pct: 0.06,
    ...overrides
  };
}

it("labels buy and sell prices as actual execution prices", () => {
  render(<TradesTable trades={[buildTrade({ buy_price: 10.23, sell_price: 11.05 })]} />);

  expect(screen.getByText("买入实际成交价")).toBeInTheDocument();
  expect(screen.getByText("卖出实际成交价")).toBeInTheDocument();
  const row = screen.getByRole("row", { name: /600519/ });
  expect(row).toHaveTextContent("2026-06-02 @ 10.23");
  expect(row).toHaveTextContent("2026-06-05@ 11.05");
});

it("shows blocked limit-up or limit-down reasons without presenting zero-share events as profitable trades", () => {
  render(
    <TradesTable
      trades={[
        buildTrade({
          symbol: "300750",
          shares: 0,
          buy_amount: 0,
          sell_amount: null,
          sell_date: null,
          sell_price: null,
          actual_position_pct: 0,
          pnl: null,
          pnl_pct: null,
          blocked_reason: "涨停阻买：开盘一字涨停，无法按计划买入"
        })
      ]}
    />
  );

  const row = screen.getByRole("row", { name: /300750/ });
  expect(within(row).getByText("阻断/延迟")).toBeInTheDocument();
  expect(row).toHaveTextContent("涨停阻买：开盘一字涨停，无法按计划买入");
  expect(within(row).getAllByText("未成交")).toHaveLength(2);
  expect(within(row).getByText("未产生收益")).toBeInTheDocument();
  expect(within(row).queryByText("持仓中")).not.toBeInTheDocument();
});
