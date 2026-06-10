import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import type { ClsFinanceResponse } from "../types";
import { ClsFinancePanel } from "./ClsFinancePanel";

function buildFinance(): ClsFinanceResponse {
  return {
    updated_at: "2026-06-09T17:56:03+08:00",
    source: "cls-finance",
    source_url: "https://www.cls.cn/finance",
    preclose_px: 3959.337,
    tline: [
      { date: 20260609, minute: 930, last_px: 3977.539, change: 0.0047 },
      { date: 20260609, minute: 931, last_px: 3966.391, change: -0.0028 },
      { date: 20260609, minute: 1500, last_px: 4015.5, change: 0.0142 }
    ],
    anchors: [
      {
        code: "cls80025",
        name: "PCB",
        article_id: 2394344,
        c_time: "2026-06-09 09:31:30",
        direction: "up",
        url: "https://www.cls.cn/plate?code=cls80025"
      },
      {
        code: "cls80081",
        name: "油气设服",
        article_id: 2394352,
        c_time: "2026-06-09 09:39:24",
        direction: "down",
        url: "https://www.cls.cn/plate?code=cls80081"
      }
    ],
    emotion: {
      market_degree: 56,
      shsz_balance: "2.64万亿",
      shsz_balance_change: "-1524亿",
      up_limit: 130,
      open_limit: 25,
      performance: "1.74%",
      breadth: {
        up: 3322,
        down: 2049,
        flat: 156,
        total: 5527,
        source: "cls-finance-emotion",
        distribution: { suspend: 12 }
      }
    },
    up_pool: [
      {
        symbol: "601869",
        name: "长飞光纤",
        change_pct: 0.1,
        last: 484.33,
        time: "2026-06-09 13:34:47",
        reason: "光纤|全球光纤光缆行业领先企业。",
        limit_up_days: 1,
        plates: [{ code: "cls81670", name: "光纤光缆", change_pct: 0.0393 }]
      }
    ],
    diagnostics: []
  };
}

it("renders CLS finance market board with news-summary style briefing cards", () => {
  render(<ClsFinancePanel finance={buildFinance()} />);

  expect(screen.getByRole("region", { name: "财联社看盘" })).toBeInTheDocument();
  expect(screen.getByText("财联社看盘")).toBeInTheDocument();
  expect(screen.getByText("市场热度")).toBeInTheDocument();
  expect(screen.getByText("56.0")).toBeInTheDocument();
  expect(screen.getByText("涨停 130")).toBeInTheDocument();
  expect(screen.getByText("开板 25")).toBeInTheDocument();
  expect(screen.getByText("PCB")).toBeInTheDocument();
  expect(screen.getByText("油气设服")).toBeInTheDocument();
  expect(screen.getByText("盘面热度")).toBeInTheDocument();
  expect(screen.getByText("重点板块")).toBeInTheDocument();
  expect(screen.getByText("涨停动因")).toBeInTheDocument();
  expect(screen.getByText("财联社市场热度 56.0，涨停 130 家，开板 25 家。")).toBeInTheDocument();
  expect(screen.getByText("PCB、油气设服")).toBeInTheDocument();
  expect(screen.getByText("3 个分时点 / 热度偏强")).toBeInTheDocument();
  expect(screen.getByText("2 个锚点 / 1 强 1 弱")).toBeInTheDocument();
  expect(screen.getByText("1 个样本 / 涨停池")).toBeInTheDocument();
  expect(screen.queryByText(/个来源/)).not.toBeInTheDocument();
  expect(screen.queryByText(/positive/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "查看涨停明细" })).toBeInTheDocument();
  expect(screen.queryByText("长飞光纤")).not.toBeInTheDocument();
  expect(screen.queryByText("光纤光缆")).not.toBeInTheDocument();
  expect(screen.queryByText("行情评价")).not.toBeInTheDocument();
  expect(screen.queryByText("明日观察")).not.toBeInTheDocument();
});

it("renders explicit fallback chips when CLS anchors and limit-up samples are empty", () => {
  const finance = {
    ...buildFinance(),
    anchors: [],
    up_pool: [],
    emotion: {
      ...buildFinance().emotion,
      market_degree: 42
    }
  };

  render(<ClsFinancePanel finance={finance} />);

  expect(screen.getByText("0 个锚点 / 暂无锚点")).toBeInTheDocument();
  expect(screen.getByText("0 个样本 / 暂无涨停池")).toBeInTheDocument();
  expect(screen.getAllByText("暂无明确要点").length).toBeGreaterThanOrEqual(1);
});

it("opens the limit-up pool in a scrollable dialog on demand", async () => {
  const user = userEvent.setup();
  render(<ClsFinancePanel finance={buildFinance()} />);

  await user.click(screen.getByRole("button", { name: "查看涨停明细" }));

  const dialog = screen.getByRole("dialog", { name: "财联社涨停明细" });
  expect(dialog).toBeInTheDocument();
  expect(within(dialog).getByText("共 1 条")).toBeInTheDocument();
  expect(within(dialog).getByText("长飞光纤")).toBeInTheDocument();
  expect(within(dialog).getByText("光纤光缆")).toBeInTheDocument();

  await user.click(within(dialog).getByRole("button", { name: "关闭涨停明细" }));
  expect(screen.queryByRole("dialog", { name: "财联社涨停明细" })).not.toBeInTheDocument();
});

it("shows an explicit loading state for the CLS finance board", () => {
  render(<ClsFinancePanel finance={null} isLoading />);

  expect(screen.getByText("正在加载财联社看盘")).toBeInTheDocument();
});
