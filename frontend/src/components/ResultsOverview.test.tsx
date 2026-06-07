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

  expect(screen.getByRole("region", { name: "今日策略命中" })).toBeInTheDocument();
  expect(screen.getByText("今日策略命中")).toBeInTheDocument();
  expect(screen.getByText("信号日 2026-06-01 / 展示日 2026-06-01")).toBeInTheDocument();
  expect(screen.getByText("600519")).toBeInTheDocument();
  expect(screen.getByText("贵州茅台")).toBeInTheDocument();
  expect(screen.getByText("+2.13%")).toBeInTheDocument();
  expect(screen.getByText("收盘 1688.80")).toBeInTheDocument();
  expect(screen.getByText("收盘价站上20日均线")).toBeInTheDocument();
  expect(screen.getByText("主力净流入放大")).toBeInTheDocument();
});

it("prefers latest strategy matches over legacy matched stocks and sorts by rank score", () => {
  render(
    <ResultsOverview
      result={buildResult({
        matched_stocks: [{ symbol: "OLD", name: "旧字段", close: 1, change_pct: 0, reasons: ["legacy"] }],
        latest_strategy_matches: {
          signal_date: "2026-06-03",
          trade_date: "2026-06-03",
          matches: [
            { symbol: "LOW", name: "低分", close: 10, change_pct: 0.01, rank_score: 0.3, reasons: ["低分原因"] },
            { symbol: "HIGH", name: "高分", close: 20, change_pct: 0.02, rank_score: 2.4, reasons: ["高分原因"] }
          ]
        }
      })}
      onRun={vi.fn()}
      onOpenRiskAlerts={vi.fn()}
    />
  );

  expect(screen.queryByText("OLD")).not.toBeInTheDocument();
  const cards = screen.getAllByRole("article").filter((item) => item.className.includes("matched-stock-card"));
  expect(cards[0]).toHaveTextContent("HIGH");
  expect(cards[0]).toHaveTextContent("评分 2.40");
});

it("shows a friendly empty state when no stocks match today", () => {
  render(
    <ResultsOverview
      result={buildResult({ matched_stocks: [] })}
      onRun={vi.fn()}
      onOpenRiskAlerts={vi.fn()}
    />
  );

  expect(screen.getByText("今日策略命中")).toBeInTheDocument();
  expect(screen.getByText("今日没有股票命中当前策略")).toBeInTheDocument();
});

it("shows annualized return beside the other backtest metrics", () => {
  render(<ResultsOverview result={buildResult()} onRun={vi.fn()} onOpenRiskAlerts={vi.fn()} />);

  expect(screen.getByText("总收益 3.20%")).toBeInTheDocument();
  expect(screen.getByText("年化收益 4.10%")).toBeInTheDocument();
  expect(screen.getByText("最大回撤 -1.80%")).toBeInTheDocument();
});
