import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import type { ClsFinanceResponse } from "../types";
import { ClsFinancePanel } from "./ClsFinancePanel";

const invokeMock = vi.hoisted(() => vi.fn());

vi.mock("@tauri-apps/api/core", () => ({
  invoke: invokeMock
}));

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

afterEach(() => {
  vi.restoreAllMocks();
  invokeMock.mockReset();
  Reflect.deleteProperty(window, "__TAURI_INTERNALS__");
  Reflect.deleteProperty(globalThis, "isTauri");
});

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
  const detailButton = screen.getByRole("button", { name: "查看涨停明细" });
  expect(detailButton).toBeInTheDocument();
  expect(detailButton).toHaveTextContent(/^涨停明细$/);
  expect(screen.queryByText("长飞光纤")).not.toBeInTheDocument();
  expect(screen.queryByText("光纤光缆")).not.toBeInTheDocument();
  expect(screen.queryByText("行情评价")).not.toBeInTheDocument();
  expect(screen.queryByText("明日观察")).not.toBeInTheDocument();
});

it("按交易时间和昨收展示分时，并可以打开原始看盘页", async () => {
  const user = userEvent.setup();
  const open = vi.spyOn(window, "open").mockImplementation(() => null);

  render(<ClsFinancePanel finance={buildFinance()} />);

  expect(screen.getByLabelText("上证指数昨收基准")).toBeInTheDocument();
  expect(screen.getByText("09:30")).toBeInTheDocument();
  expect(screen.getByText("11:30 / 13:00")).toBeInTheDocument();
  expect(screen.getByText("15:00")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "打开财联社看盘页" }));

  expect(open).toHaveBeenCalledWith("https://www.cls.cn/finance", "_blank", "noopener,noreferrer");
});

it("缺少昨收时仍按分时价格走势绘制并均匀排列交易点", () => {
  const finance = {
    ...buildFinance(),
    preclose_px: null,
    tline: [
      { date: 20260609, minute: 930, last_px: 100, change: 0.05 },
      { date: 20260609, minute: 931, last_px: 101, change: -0.05 },
      { date: 20260609, minute: 1300, last_px: 102, change: 0.05 }
    ]
  };

  const { container } = render(<ClsFinancePanel finance={finance} />);
  const path = container.querySelector(".cls-finance-tline path");
  const coordinates = path
    ?.getAttribute("d")
    ?.match(/[-+]?\d*\.?\d+/g)
    ?.map(Number);

  expect(coordinates).toBeDefined();
  expect(coordinates?.[2]).toBeGreaterThan(40);
  expect(coordinates?.[1]).toBeGreaterThan(coordinates?.[3] ?? Number.POSITIVE_INFINITY);
  expect(coordinates?.[3]).toBeGreaterThan(coordinates?.[5] ?? Number.POSITIVE_INFINITY);
  expect(screen.getByText("09:30 基准 100.00")).toBeInTheDocument();
});

it("在桌面端通过系统命令打开财联社看盘页", async () => {
  const user = userEvent.setup();
  Object.defineProperty(window, "__TAURI_INTERNALS__", {
    configurable: true,
    value: {}
  });
  invokeMock.mockResolvedValueOnce(undefined);

  render(<ClsFinancePanel finance={buildFinance()} />);

  await user.click(screen.getByRole("button", { name: "打开财联社看盘页" }));

  expect(invokeMock).toHaveBeenCalledWith("open_external_url", {
    url: "https://www.cls.cn/finance"
  });
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

it("labels the score card as Tonghuashun market rating when the score comes from q.10jqka.com", () => {
  const finance = {
    ...buildFinance(),
    emotion: {
      ...buildFinance().emotion,
      market_degree: 7.3,
      market_degree_source: "ths-market-summary",
      market_degree_label: "同花顺大盘评级"
    }
  };

  render(<ClsFinancePanel finance={finance} />);

  expect(screen.getAllByText("大盘评分").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("7.3")).toBeInTheDocument();
  expect(screen.getByText("3 个分时点 / 同花顺大盘评级")).toBeInTheDocument();
  expect(screen.getByText("同花顺大盘评级 7.3，涨停 130 家，开板 25 家。")).toBeInTheDocument();
  expect(screen.getByText("3 个分时点 / 同花顺大盘评级").closest("article")).toHaveClass("positive");
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

it("shows an explicit loading state for the CLS finance board", async () => {
  const user = userEvent.setup();
  const open = vi.spyOn(window, "open").mockImplementation(() => null);

  render(<ClsFinancePanel finance={null} isLoading />);

  expect(screen.getByText("正在加载财联社看盘")).toBeInTheDocument();
  const openButton = screen.getByRole("button", { name: "打开财联社看盘页" });
  expect(openButton).toBeEnabled();
  await user.click(openButton);
  expect(open).toHaveBeenCalledWith("https://www.cls.cn/finance", "_blank", "noopener,noreferrer");
});

it("shows retained-source status without an error panel when recent data is usable", () => {
  render(
    <ClsFinancePanel
      finance={{
        ...buildFinance(),
        source: "cls-finance+recent-success-cache",
        diagnostics: ["recent_success_cache_used", "CLS emotion endpoint failed"]
      }}
    />
  );

  expect(screen.getByText(/^最近成功数据 \/ 更新/)).toBeInTheDocument();
  expect(screen.queryByRole("status", { name: "财联社数据诊断" })).not.toBeInTheDocument();
  expect(screen.queryByText("recent_success_cache_used")).not.toBeInTheDocument();
  expect(screen.queryByText("CLS emotion endpoint failed")).not.toBeInTheDocument();
});

it("marks an entirely unavailable CLS response as unavailable while keeping diagnostics", () => {
  render(
    <ClsFinancePanel
      finance={{
        ...buildFinance(),
        preclose_px: null,
        tline: [],
        anchors: [],
        emotion: null,
        up_pool: [],
        diagnostics: ["CLS finance endpoints unavailable"]
      }}
    />
  );

  expect(screen.getByText("CLS 数据暂不可用")).toBeInTheDocument();
  expect(screen.queryByText(/CLS 实时数据/)).not.toBeInTheDocument();
  expect(screen.getByText("CLS finance endpoints unavailable")).toBeInTheDocument();
});
