import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { MarketNewsResponse } from "../types";
import { NewsPanel } from "./NewsPanel";

const invokeMock = vi.hoisted(() => vi.fn());

vi.mock("@tauri-apps/api/core", () => ({
  invoke: invokeMock
}));

beforeEach(() => {
  invokeMock.mockReset();
  Reflect.deleteProperty(window, "__TAURI_INTERNALS__");
  Reflect.deleteProperty(globalThis, "isTauri");
});

function buildNews(): MarketNewsResponse {
  return {
    updated_at: "2026-06-01T10:30:00+08:00",
    source: "test-news",
    items: []
  };
}

it("keeps the market news panel mounted as a standalone section", () => {
  const { container } = render(<NewsPanel news={buildNews()} />);

  expect(container.querySelector(".news-panel")).toBeInTheDocument();
  expect(container.querySelector(".news-list")).not.toBeInTheDocument();
});

it("keeps all news items visible inside the scrolling list", () => {
  render(
    <NewsPanel
      news={{
        updated_at: "2026-06-01T10:30:00+08:00",
        source: "test-news",
        items: Array.from({ length: 8 }, (_, index) => ({
          title: `market-news-${index + 1}`,
          summary: "summary",
          source: "source",
          published_at: "2026-06-01T10:30:00+08:00",
          tags: [],
          sentiment: "neutral"
        }))
      }}
    />
  );

  expect(screen.getByText("market-news-1")).toBeInTheDocument();
  expect(screen.getByText("market-news-8")).toBeInTheDocument();
});

it("opens news item urls through the desktop shell command", async () => {
  const user = userEvent.setup();
  Object.defineProperty(window, "__TAURI_INTERNALS__", {
    configurable: true,
    value: {}
  });
  invokeMock.mockResolvedValueOnce(undefined);

  render(
    <NewsPanel
      news={{
        updated_at: "2026-06-01T10:30:00+08:00",
        source: "test-news",
        items: [
          {
            title: "cls-news",
            summary: "summary",
            source: "source",
            published_at: "2026-06-01T10:30:00+08:00",
            url: "https://www.cls.cn/detail/123",
            tags: [],
            sentiment: "neutral"
          }
        ]
      }}
    />
  );

  await user.click(screen.getByRole("link", { name: "打开cls-news" }));

  expect(invokeMock).toHaveBeenCalledWith("open_external_url", {
    url: "https://www.cls.cn/detail/123"
  });
});

it("detects Tauri v2 runtime when opening news item urls", async () => {
  const user = userEvent.setup();
  Object.defineProperty(globalThis, "isTauri", {
    configurable: true,
    value: true
  });
  invokeMock.mockResolvedValueOnce(undefined);

  render(
    <NewsPanel
      news={{
        updated_at: "2026-06-01T10:30:00+08:00",
        source: "test-news",
        items: [
          {
            title: "eastmoney-news",
            summary: "summary",
            source: "eastmoney",
            published_at: "2026-06-01T10:30:00+08:00",
            url: "http://finance.eastmoney.com/news/1345,202607053794287518.html",
            tags: [],
            sentiment: "neutral"
          }
        ]
      }}
    />
  );

  await user.click(screen.getByRole("link", { name: "打开eastmoney-news" }));

  expect(invokeMock).toHaveBeenCalledWith("open_external_url", {
    url: "http://finance.eastmoney.com/news/1345,202607053794287518.html"
  });
});
