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

it("keeps all news items visible inside the scrolling list", () => {
  render(
    <NewsPanel
      news={{
        updated_at: "2026-06-01T10:30:00+08:00",
        source: "test-news",
        items: Array.from({ length: 8 }, (_, index) => ({
          title: `市场新闻 ${index + 1}`,
          summary: "短要点",
          source: "测试源",
          published_at: "2026-06-01T10:30:00+08:00",
          tags: [],
          sentiment: "neutral"
        }))
      }}
    />
  );

  expect(screen.getByText("市场新闻 1")).toBeInTheDocument();
  expect(screen.getByText("市场新闻 8")).toBeInTheDocument();
  expect(screen.queryByText(/资讯已收起/)).not.toBeInTheDocument();
});
