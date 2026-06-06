import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import type { NewsSummaryResponse } from "../types";
import { NewsSummaryPanel } from "./NewsSummaryPanel";

function buildSummary(): NewsSummaryResponse {
  return {
    updated_at: "2026-06-01T14:40:00+08:00",
    source: "test-summary",
    item_count: 12,
    themes: [
      {
        title: "机器人产业链",
        summary: "政策和订单催化共同升温。",
        sentiment: "positive",
        source_count: 5,
        headlines: ["减速器方向成交活跃", "部分公司披露新订单"]
      }
    ],
    highlights: ["机器人产业链热度靠前"],
    risks: ["高位股波动加大"],
    diagnostics: []
  };
}

it("renders today's news topics, key points, risks and source count", () => {
  render(<NewsSummaryPanel summary={buildSummary()} />);

  expect(screen.getByText("新闻汇总")).toBeInTheDocument();
  expect(screen.getByText("12 条新闻")).toBeInTheDocument();
  expect(screen.getByText("机器人产业链")).toBeInTheDocument();
  expect(screen.getByText("政策和订单催化共同升温。")).toBeInTheDocument();
  expect(screen.getByText("要点")).toBeInTheDocument();
  expect(screen.getByText("减速器方向成交活跃")).toBeInTheDocument();
  expect(screen.getByText("风险")).toBeInTheDocument();
  expect(screen.getByText("高位股波动加大")).toBeInTheDocument();
  expect(screen.getByText("5 个来源 / positive")).toBeInTheDocument();
});
