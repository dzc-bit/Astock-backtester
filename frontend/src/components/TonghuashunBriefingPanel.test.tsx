import { render, screen, within } from "@testing-library/react";
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

it("renders fupan and zaopan as concise standalone Tonghuashun briefing cards", () => {
  render(<TonghuashunBriefingPanel fupan={buildBriefing("fupan")} zaopan={buildBriefing("zaopan")} />);

  expect(screen.getByText("同花顺复盘总评")).toBeInTheDocument();
  expect(screen.getByText("同花顺早盘总评")).toBeInTheDocument();
  expect(screen.getByText("A股三大指数集体下跌，煤炭、养鸡、AI应用活跃。")).toBeInTheDocument();
  expect(screen.getByText("昨日收盘指数 上证指数：4068.57 -0.734%")).toBeInTheDocument();
  expect(screen.queryByText("ERP概念、财税数字化和小红书概念涨幅居前。")).not.toBeInTheDocument();
  expect(screen.queryByText("关注公司事项、机构观点和今日停复牌。")).not.toBeInTheDocument();
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

it("focuses the briefing dialog and closes it with Escape", async () => {
  const user = userEvent.setup();
  render(<TonghuashunBriefingPanel fupan={buildBriefing("fupan")} zaopan={buildBriefing("zaopan")} />);

  const openButton = screen.getByRole("button", { name: "查看同花顺复盘总评全文" });
  await user.click(openButton);

  expect(screen.getByRole("button", { name: "关闭同花顺复盘总评全文" })).toHaveFocus();

  await user.keyboard("{Escape}");

  expect(screen.queryByRole("dialog", { name: "同花顺复盘总评全文" })).not.toBeInTheDocument();
  expect(openButton).toHaveFocus();
});

it("keeps the end of a long full briefing readable in the dialog", async () => {
  const user = userEvent.setup();
  const longBriefing = buildBriefing("fupan");
  longBriefing.summary = "复盘摘要：先看指数位置，再看主线持续性。";
  longBriefing.sections = [
    {
      title: "指数与情绪",
      content: [
        "指数全天震荡，权重护盘但题材分化。",
        "成交额没有明显放大，追高需要更多确认。",
        "长文本尾部：明日继续观察量能能否回到万亿上方。"
      ].join("\n\n"),
      links: [{ title: "复盘原文", url: "https://stock.10jqka.com.cn/fupan/detail.html" }],
      tables: []
    }
  ];

  render(<TonghuashunBriefingPanel fupan={longBriefing} zaopan={buildBriefing("zaopan")} />);

  await user.click(screen.getByRole("button", { name: "查看同花顺复盘总评全文" }));

  expect(screen.getByText("重点摘要")).toBeInTheDocument();
  expect(screen.getByText("阅读全文")).toBeInTheDocument();
  expect(screen.getByText("长文本尾部：明日继续观察量能能否回到万亿上方。")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /打开同花顺原文/ })).toHaveAttribute(
    "href",
    "https://stock.10jqka.com.cn/fupan/"
  );
});

it("keeps long briefing body out of the main card and opens it in the dialog", async () => {
  const user = userEvent.setup();
  const longBriefing = buildBriefing("fupan");
  const fullTextOnly = "同花顺长文尾部哨兵：这里只应该在总评全文弹窗出现";
  longBriefing.summary = `${"复盘主线很多，需要压缩。".repeat(16)}${fullTextOnly}`;
  longBriefing.sections = [
    {
      title: "全文：A股收评",
      content: `${"指数、题材和资金线索展开说明。".repeat(24)}${fullTextOnly}`,
      links: [],
      tables: []
    }
  ];

  render(<TonghuashunBriefingPanel fupan={longBriefing} zaopan={buildBriefing("zaopan")} />);

  expect(screen.queryByText(fullTextOnly)).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "查看同花顺复盘总评全文" }));

  const dialog = screen.getByRole("dialog", { name: "同花顺复盘总评全文" });
  expect(dialog).toBeInTheDocument();
  expect(dialog).toHaveTextContent(fullTextOnly);
});

it("highlights crawled article full text separately from the summary", async () => {
  const user = userEvent.setup();
  const briefing = buildBriefing("fupan");
  briefing.sections = [
    {
      title: "同花顺解盘",
      content: "列表页解盘只提供了文章入口。",
      links: [{ title: "A股收评：机器人走强", url: "https://stock.10jqka.com.cn/20260605/c677247169.shtml" }],
      tables: []
    },
    {
      title: "全文：A股收评：机器人走强",
      content: "今日机器人板块午后持续冲高。\n\n明日重点观察成交额能否继续放大。",
      links: [{ title: "A股收评：机器人走强", url: "https://stock.10jqka.com.cn/20260605/c677247169.shtml" }],
      tables: []
    }
  ];

  render(<TonghuashunBriefingPanel fupan={briefing} zaopan={buildBriefing("zaopan")} />);

  await user.click(screen.getByRole("button", { name: "查看同花顺复盘总评全文" }));

  expect(screen.getByText("抓取到的原文详情")).toBeInTheDocument();
  expect(screen.getByText("今日机器人板块午后持续冲高。")).toBeInTheDocument();
  expect(screen.getByText("明日重点观察成交额能否继续放大。")).toBeInTheDocument();
});

it("cleans placeholder table field names in the full briefing dialog", async () => {
  const user = userEvent.setup();
  const briefing = buildBriefing("fupan");
  briefing.sections = [
    {
      title: "复盘表格",
      content: "结构化表格来自页面抓取，需要整理字段名。",
      links: [],
      tables: [
        {
          title: "强势方向",
          columns: ["字段1", "字段2", "字段3"],
          rows: [{ 字段1: "机器人", 字段2: "午后持续拉升", 字段3: "" }]
        }
      ]
    }
  ];

  render(<TonghuashunBriefingPanel fupan={briefing} zaopan={buildBriefing("zaopan")} />);

  await user.click(screen.getByRole("button", { name: "查看同花顺复盘总评全文" }));

  expect(screen.queryByText("字段1")).not.toBeInTheDocument();
  expect(screen.queryByText("字段2")).not.toBeInTheDocument();
  expect(screen.queryByText("字段3")).not.toBeInTheDocument();
  expect(screen.getByText("题材")).toBeInTheDocument();
  expect(screen.getByText("异动原因")).toBeInTheDocument();
  expect(screen.queryByText("影响")).not.toBeInTheDocument();
  expect(screen.getByText("机器人")).toBeInTheDocument();
  expect(screen.getByText("午后持续拉升")).toBeInTheDocument();
});

it("keeps diagnostics and long table details out of the main card while organizing them in the dialog", async () => {
  const user = userEvent.setup();
  const briefing = buildBriefing("fupan");
  const mainHiddenText = "弹窗专属长表格内容，不应铺在主界面";
  briefing.summary = "复盘重点：指数缩量震荡，题材轮动加快。";
  briefing.diagnostics = ["已过滤纯数字汤和重复时间戳"];
  briefing.sections = [
    {
      title: "重点摘要",
      content: "题材轮动较快，注意追高风险。",
      links: [{ title: "阅读全文链接", url: "https://stock.10jqka.com.cn/fupan/detail.html" }],
      tables: [
        {
          title: "相关表格",
          columns: ["题材", "说明"],
          rows: [{ 题材: "机器人", 说明: mainHiddenText }]
        }
      ]
    }
  ];

  render(<TonghuashunBriefingPanel fupan={briefing} zaopan={buildBriefing("zaopan")} />);

  const panel = screen.getByRole("region", { name: "同花顺复盘与早盘总评" });
  expect(panel).not.toHaveTextContent(mainHiddenText);
  expect(panel).not.toHaveTextContent("已过滤纯数字汤和重复时间戳");

  await user.click(screen.getByRole("button", { name: "查看同花顺复盘总评全文" }));

  const dialog = screen.getByRole("dialog", { name: "同花顺复盘总评全文" });
  expect(within(dialog).getAllByText("重点摘要").length).toBeGreaterThan(0);
  expect(within(dialog).getByText("阅读全文")).toBeInTheDocument();
  expect(within(dialog).getByText("相关表格")).toBeInTheDocument();
  expect(within(dialog).getByText("阅读全文链接")).toBeInTheDocument();
  expect(within(dialog).getByLabelText("同花顺总评诊断")).toHaveTextContent("已过滤纯数字汤和重复时间戳");
});
