import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

it("keeps long market commentary out of the main panel and opens it in a dialog", async () => {
  const user = userEvent.setup();
  const commentary = buildCommentary();
  const fullTextOnly = "行情评价长文尾部哨兵：这里只应该在行情全文弹窗出现";
  commentary.summary = `${"指数仍在箱体震荡，资金更偏向低位轮动。".repeat(12)}${fullTextOnly}`;
  commentary.drivers[0].detail = `${"AI 应用内部继续分化，短线资金追逐辨识度较高方向。".repeat(12)}${fullTextOnly}`;
  commentary.risks = [`${"缩量环境下追高容错率下降。".repeat(10)}${fullTextOnly}`];
  commentary.next_watch = [`${"明日重点观察成交额和红盘家数是否同步修复。".repeat(10)}${fullTextOnly}`];

  render(<MarketCommentaryPanel commentary={commentary} />);

  expect(screen.getByRole("region", { name: "行情评价" })).not.toHaveTextContent(fullTextOnly);
  expect(screen.getByRole("button", { name: "查看行情评价全文" })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "查看行情评价全文" }));

  const dialog = screen.getByRole("dialog", { name: "行情评价全文" });
  expect(dialog).toBeInTheDocument();
  expect(dialog).toHaveTextContent(fullTextOnly);
});

it("focuses the market commentary dialog and closes it with Escape", async () => {
  const user = userEvent.setup();
  render(<MarketCommentaryPanel commentary={buildCommentary()} />);

  const openButton = screen.getByRole("button", { name: "查看行情评价全文" });
  await user.click(openButton);

  expect(screen.getByRole("button", { name: "关闭行情评价全文" })).toHaveFocus();

  await user.keyboard("{Escape}");

  expect(screen.queryByRole("dialog", { name: "行情评价全文" })).not.toBeInTheDocument();
  expect(openButton).toHaveFocus();
});

it("makes incomplete realtime market context visible in the concise main panel", () => {
  const commentary = buildCommentary();
  commentary.summary = "实时盘面暂不可用，以下仅为新闻线索候选：AI 应用和机器人消息较多。";
  commentary.diagnostics = ["缺少实时指数报价", "缺少市场红绿家数"];

  render(<MarketCommentaryPanel commentary={commentary} />);

  const panel = screen.getByRole("region", { name: "行情评价" });
  expect(panel).toHaveTextContent("实时盘面暂不可用");
  expect(panel).toHaveTextContent("新闻线索候选");
  expect(panel).toHaveTextContent("依据不完整");
  expect(panel).toHaveTextContent("缺少实时指数报价");
});
