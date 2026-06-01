import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import type { MarketBriefingResponse } from "../types";
import { TonghuashunBriefingPanel } from "./TonghuashunBriefingPanel";

function buildBriefing(kind: "fupan" | "zaopan"): MarketBriefingResponse {
  return {
    kind,
    updated_at: kind === "fupan" ? "2026-06-01T15:30:00+08:00" : "2026-06-01T08:30:00+08:00",
    source: kind === "fupan" ? "ths-fupan" : "ths-zaopan",
    source_url: kind === "fupan" ? "https://stock.10jqka.com.cn/fupan/" : "https://stock.10jqka.com.cn/zaopan/",
    summary:
      kind === "fupan"
        ? "A股三大指数集体下跌，煤炭、养鸡、AI应用活跃。"
        : "昨日收盘指数 上证指数：4068.57 -0.734%",
    sections: [
      {
        title: kind === "fupan" ? "指数/概念分析" : "早盘要点",
        content:
          kind === "fupan"
            ? "ERP概念、财税数字化和小红书概念涨幅居前。"
            : "关注公司事项、机构观点和今日停复牌。",
        links:
          kind === "fupan"
            ? [{ title: "煤炭板块复盘全文", url: "https://stock.10jqka.com.cn/fupan/detail.html" }]
            : [{ title: "早盘公司事项全文", url: "https://stock.10jqka.com.cn/zaopan/detail.html" }],
        tables: [
          {
            title: kind === "fupan" ? "强势题材" : "早盘关注",
            columns: ["题材", "涨幅"],
            rows: [{ 题材: kind === "fupan" ? "ERP概念" : "公司事项", 涨幅: kind === "fupan" ? "+3.2%" : "关注" }]
          }
        ]
      }
    ],
    diagnostics: []
  };
}

it("renders fupan and zaopan as standalone Tonghuashun briefing cards", () => {
  render(<TonghuashunBriefingPanel fupan={buildBriefing("fupan")} zaopan={buildBriefing("zaopan")} />);

  expect(screen.getByText("同花顺复盘总评")).toBeInTheDocument();
  expect(screen.getByText("同花顺早盘总评")).toBeInTheDocument();
  expect(screen.getByText("A股三大指数集体下跌，煤炭、养鸡、AI应用活跃。")).toBeInTheDocument();
  expect(screen.getByText("昨日收盘指数 上证指数：4068.57 -0.734%")).toBeInTheDocument();
  expect(screen.getByText("ERP概念、财税数字化和小红书概念涨幅居前。")).toBeInTheDocument();
  expect(screen.getByText("关注公司事项、机构观点和今日停复牌。")).toBeInTheDocument();
});

it("opens a full briefing dialog from each Tonghuashun card", async () => {
  const user = userEvent.setup();
  render(<TonghuashunBriefingPanel fupan={buildBriefing("fupan")} zaopan={buildBriefing("zaopan")} />);

  await user.click(screen.getByRole("button", { name: "查看同花顺复盘总评全文" }));

  expect(screen.getByRole("dialog", { name: "同花顺复盘总评全文" })).toBeInTheDocument();
  expect(screen.getByText("指数/概念分析")).toBeInTheDocument();
  expect(screen.getByText("煤炭板块复盘全文")).toBeInTheDocument();
  expect(screen.getByText("强势题材")).toBeInTheDocument();
  expect(screen.getByText("ERP概念")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "关闭同花顺复盘总评全文" }));

  expect(screen.queryByRole("dialog", { name: "同花顺复盘总评全文" })).not.toBeInTheDocument();
});
