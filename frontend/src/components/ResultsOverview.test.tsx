import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { BacktestResult } from "../types";
import { ResultsOverview } from "./ResultsOverview";

function buildResult(overrides: Partial<BacktestResult> = {}): BacktestResult {
  return {
    metrics: {
      total_return_pct: 0.032,
      annualized_return_pct: 0.041,
      max_drawdown_pct: -0.018,
      win_rate_pct: 0.6,
      trade_count: 2,
      average_trade_return_pct: 0.011,
      average_position_pct: 0.48,
      max_position_pct: 0.5
    },
    equity_curve: [
      { trade_date: "2026-06-01", equity: 100000, cash: 100000, market_value: 0, drawdown_pct: 0 },
      { trade_date: "2026-06-02", equity: 101000, cash: 52000, market_value: 49000, drawdown_pct: 0 }
    ],
    trades: [],
    preflight_issues: [],
    ...overrides
  };
}

it("lists today's matched stocks after a strategy run", () => {
  render(
    <ResultsOverview
      result={buildResult({
        latest_strategy_matches: {
          signal_date: "2026-06-01",
          trade_date: "2026-06-01",
          matches: [
            {
              symbol: "600519",
              name: "贵州茅台",
              close: 1688.8,
              change_pct: 0.0213,
              reasons: ["收盘价站上20日均线", "主力净流入放大"]
            },
            {
              symbol: "300750",
              name: "宁德时代",
              close: 218.32,
              change_pct: -0.008,
              reasons: ["量比2日介于1.2到2.5"]
            }
          ]
        }
      })}
      onRun={vi.fn()}
      onOpenRiskAlerts={vi.fn()}
    />
  );

  expect(screen.getByText("当日符合策略股票")).toBeInTheDocument();
  expect(screen.getByText("600519")).toBeInTheDocument();
  expect(screen.getByText("贵州茅台")).toBeInTheDocument();
  expect(screen.getByText("+2.13%")).toBeInTheDocument();
  expect(screen.getByText("收盘 1688.80")).toBeInTheDocument();
  expect(screen.getByText("收盘价站上20日均线")).toBeInTheDocument();
  expect(screen.getByText("主力净流入放大")).toBeInTheDocument();
});

it("shows a friendly empty state when no stocks match today", () => {
  render(
    <ResultsOverview
      result={buildResult({ matched_stocks: [] })}
      onRun={vi.fn()}
      onOpenRiskAlerts={vi.fn()}
    />
  );

  expect(screen.getByText("当日符合策略股票")).toBeInTheDocument();
  expect(screen.getByText("今日没有股票命中当前策略")).toBeInTheDocument();
});
