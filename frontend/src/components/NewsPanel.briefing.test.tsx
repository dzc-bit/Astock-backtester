import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import type { MarketNewsResponse } from "../types";
import { NewsPanel } from "./NewsPanel";

function buildNews(): MarketNewsResponse {
  return {
    updated_at: "2026-06-01T10:30:00+08:00",
    source: "test-news",
    items: []
  };
}

it("keeps Tonghuashun morning briefing out of the news panel", () => {
  render(<NewsPanel news={buildNews()} />);

  expect(screen.getByText("资讯与事件")).toBeInTheDocument();
  expect(screen.queryByText("同花顺早盘汇总")).not.toBeInTheDocument();
});
