import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";

const apiMocks = vi.hoisted(() => ({
  loadCoverage: vi.fn(),
  runConfiguredBacktest: vi.fn()
}));

vi.mock("../api", () => apiMocks);

const demoResult = {
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
      buy_reason: ["float market cap in range"],
      sell_reason: ["fixed holding days reached"],
      pnl: -7200,
      pnl_pct: -0.15
    }
  ],
  preflight_issues: []
};

describe("Backtester UI", () => {
  beforeEach(() => {
    apiMocks.loadCoverage.mockResolvedValue([
      { dataset: "daily_bars", symbols: 2, start_date: "2024-01-02", end_date: "2024-01-08", missing_rows: 0 }
    ]);
    apiMocks.runConfiguredBacktest.mockResolvedValue(demoResult);
  });

  it("renders the five first-version work areas", async () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "Data Center" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Strategy Editor" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Backtest Settings" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Result Overview" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Trade Explanations" })).toBeInTheDocument();
    expect(await screen.findByText("daily_bars")).toBeInTheDocument();
  });

  it("exposes market cap and capital flow conditions", async () => {
    render(<App />);

    expect(screen.getByText("Float market cap range")).toBeInTheDocument();
    expect(screen.getByText("N-day main net inflow")).toBeInTheDocument();
    expect(await screen.findByText("daily_bars")).toBeInTheDocument();
  });

  it("lets the user adjust strategy parameters before running a backtest", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.clear(screen.getByLabelText("Minimum float market cap"));
    await user.type(screen.getByLabelText("Minimum float market cap"), "5000000000");
    await user.clear(screen.getByLabelText("Volume ratio minimum"));
    await user.type(screen.getByLabelText("Volume ratio minimum"), "1.2");
    await user.clear(screen.getByLabelText("Initial capital"));
    await user.type(screen.getByLabelText("Initial capital"), "250000");
    await user.click(screen.getByRole("button", { name: "Run Backtest" }));

    expect(await screen.findByText("Trades 1")).toBeInTheDocument();
  });

  it("shows backend errors without dropping the page", async () => {
    const user = userEvent.setup();
    apiMocks.runConfiguredBacktest.mockRejectedValue(new Error("No cached daily bars found."));
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Run Backtest" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("No cached daily bars found.");
    expect(screen.getByRole("heading", { name: "Strategy Editor" })).toBeInTheDocument();
  });
});
