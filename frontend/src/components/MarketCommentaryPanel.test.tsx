import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import type { MarketCommentaryResponse } from "../types";
import { MarketCommentaryPanel } from "./MarketCommentaryPanel";

function buildCommentary(): MarketCommentaryResponse {
  return {
    updated_at: "2026-06-01T15:20:00+08:00",
    trade_date: "2026-06-01",
    source: "test-commentary",
    summary: "指数震荡偏强，但赚钱效应集中在少数主线。",
    stance: "neutral",
    drivers: [
      {
        title: "AI 应用",
        detail: "资金继续围绕应用端轮动，成交额排名靠前，昨日强势方向延续。",
        weight: "high"
      }
    ],
    risks: ["缩量追高：量能不足时容易冲高回落。"],
    next_watch: ["明日先看 AI 应用龙头能否继续放量。"],
    diagnostics: []
  };
}

it("renders structured market commentary sections", () => {
  render(<MarketCommentaryPanel commentary={buildCommentary()} />);

  expect(screen.getByText("行情评价")).toBeInTheDocument();
  expect(screen.getByText("结论")).toBeInTheDocument();
  expect(screen.getByText("指数震荡偏强，但赚钱效应集中在少数主线。")).toBeInTheDocument();
  expect(screen.getByText("主线")).toBeInTheDocument();
  expect(screen.getByText("AI 应用")).toBeInTheDocument();
  expect(screen.getByText("资金继续围绕应用端轮动，成交额排名靠前，昨日强势方向延续。")).toBeInTheDocument();
  expect(screen.getByText("风险")).toBeInTheDocument();
  expect(screen.getByText("缩量追高：量能不足时容易冲高回落。")).toBeInTheDocument();
  expect(screen.getByText("明日观察")).toBeInTheDocument();
  expect(screen.getByText("明日先看 AI 应用龙头能否继续放量。")).toBeInTheDocument();
});
