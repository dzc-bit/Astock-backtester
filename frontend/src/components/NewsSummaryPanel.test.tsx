import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

it("renders today's news topics as concise cards", () => {
  render(<NewsSummaryPanel summary={buildSummary()} />);

  expect(screen.getByText("新闻汇总")).toBeInTheDocument();
  expect(screen.getByText("12 条新闻")).toBeInTheDocument();
  expect(screen.getByText("机器人产业链")).toBeInTheDocument();
  expect(screen.getByText("政策和订单催化共同升温。")).toBeInTheDocument();
  expect(screen.getByText("减速器方向成交活跃")).toBeInTheDocument();
  expect(screen.getByText("5 个来源 / positive")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "查看新闻汇总全文" })).toBeInTheDocument();
  expect(screen.queryByText("高位股波动加大")).not.toBeInTheDocument();
});

it("keeps long news text out of the main card and shows it in a dialog", async () => {
  const user = userEvent.setup();
  const summary = buildSummary();
  const fullTextOnly = "长篇新闻全文尾部哨兵：这里应该只在新闻汇总全文弹窗里出现";
  summary.themes[0].summary = `${"政策、订单和资金线索持续发酵。".repeat(18)}${fullTextOnly}`;
  summary.themes[0].headlines = ["主界面第一条短要点", "第二条短要点", fullTextOnly];
  summary.risks = ["第一条风险", fullTextOnly];

  render(<NewsSummaryPanel summary={summary} />);

  expect(screen.queryByText(fullTextOnly)).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "查看新闻汇总全文" }));

  expect(screen.getByRole("dialog", { name: "新闻汇总全文" })).toBeInTheDocument();
  expect(screen.getAllByText(fullTextOnly).length).toBeGreaterThan(0);
});

it("does not leak long headline text through main-card attributes", () => {
  const summary = buildSummary();
  const fullTextOnly = `${"主卡片属性泄漏哨兵：".repeat(4)}这里不能出现在任何 title 属性里`;
  summary.themes[0].headlines = [fullTextOnly, "第二条短要点"];

  const { container } = render(<NewsSummaryPanel summary={summary} />);

  expect(screen.queryByText(fullTextOnly)).not.toBeInTheDocument();
  expect(
    Array.from(container.querySelectorAll("[title]")).some((element) => element.getAttribute("title")?.includes(fullTextOnly))
  ).toBe(false);
});

it("focuses the full-text dialog and closes it with Escape", async () => {
  const user = userEvent.setup();
  render(<NewsSummaryPanel summary={buildSummary()} />);

  const openButton = screen.getByRole("button", { name: "查看新闻汇总全文" });
  await user.click(openButton);

  expect(screen.getByRole("button", { name: "关闭新闻汇总全文" })).toHaveFocus();

  await user.keyboard("{Escape}");

  expect(screen.queryByRole("dialog", { name: "新闻汇总全文" })).not.toBeInTheDocument();
  expect(openButton).toHaveFocus();
});
