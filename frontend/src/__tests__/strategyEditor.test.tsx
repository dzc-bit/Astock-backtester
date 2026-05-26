import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";

const apiMocks = vi.hoisted(() => ({
  ensureDataService: vi.fn(),
  fetchDailyBars: vi.fn(),
  importDailyBars: vi.fn(),
  loadDailyBarsCoverage: vi.fn(),
  loadCoverage: vi.fn(),
  runConfiguredBacktest: vi.fn()
}));

vi.mock("../api", () => apiMocks);

const demoResult = {
  metrics: {
    total_return_pct: 0.032,
    annualized_return_pct: 0.032,
    max_drawdown_pct: -0.018,
    win_rate_pct: 0.6,
    trade_count: 1,
    average_trade_return_pct: 0.011
  },
  equity_curve: [
    { trade_date: "2024-01-02", equity: 100000, cash: 100000, market_value: 0, drawdown_pct: 0 },
    { trade_date: "2024-01-08", equity: 103200, cash: 103200, market_value: 0, drawdown_pct: 0 }
  ],
  trades: [
    {
      symbol: "AAA",
      buy_signal_date: "2024-01-04",
      buy_date: "2024-01-05",
      sell_date: "2024-01-08",
      buy_price: 12,
      sell_price: 10.2,
      shares: 4000,
      buy_reason: [
        "float market cap 8000000000 in [1000000000, 30000000000]",
        "3d main net inflow 6000000 >= 3000000",
        "2d volume ratio 1.20 in [1.00, 2.50]",
        "turnover 4.00% in [2.00%, 8.00%]",
        "MACD histogram 0.0310 >= 0.0000",
        "5d return 8.00% in [0.00%, 20.00%]",
        "close 12.00 broke prior 20d high 11.80"
      ],
      sell_reason: ["fixed holding days reached"],
      pnl: -7200,
      pnl_pct: -0.15
    }
  ],
  preflight_issues: []
};

describe("A 股回测工作台界面", () => {
  beforeEach(() => {
    apiMocks.ensureDataService.mockResolvedValue({
      running: true,
      port: 9010,
      base_url: "http://127.0.0.1:9010",
      cache_dir: ".astock-cache",
      message: "browser preview uses mock local service"
    });
    apiMocks.loadDailyBarsCoverage.mockResolvedValue({
      items: []
    });
    apiMocks.fetchDailyBars.mockResolvedValue({
      status: "ok",
      imported_rows: 0,
      requested_symbols: [],
      fetched_symbols: [],
      missing_symbols: [],
      coverage: [],
      logs: []
    });
    apiMocks.importDailyBars.mockResolvedValue({
      status: "ok",
      imported_rows: 0,
      coverage: [],
      logs: []
    });
    apiMocks.loadCoverage.mockResolvedValue([
      { dataset: "daily_bars", symbols: 2, start_date: "2024-01-02", end_date: "2024-01-08", missing_rows: 0 }
    ]);
    apiMocks.runConfiguredBacktest.mockResolvedValue(demoResult);
  });

  it("renders the Chinese workstation areas", async () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "A股策略回测工作台" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "检查更新" })).toBeInTheDocument();
    expect(screen.getByText(/当前版本/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "数据中心" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "策略条件" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "回测设置" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "收益概览" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "交易明细" })).toBeInTheDocument();
    expect(screen.getAllByText("市场热度").length).toBeGreaterThan(0);
    expect(screen.getAllByText("资金流向").length).toBeGreaterThan(0);
    expect(screen.getAllByText("风险提示").length).toBeGreaterThan(0);
    expect(await screen.findByText("日线行情")).toBeInTheDocument();
  });

  it("exposes common A-share strategy conditions in Chinese", async () => {
    render(<App />);

    expect(screen.getAllByText("流通市值区间").length).toBeGreaterThan(0);
    expect(screen.getAllByText("近N日主力净流入").length).toBeGreaterThan(0);
    expect(screen.getAllByText("MACD柱线下限").length).toBeGreaterThan(0);
    expect(screen.getAllByText("量比区间").length).toBeGreaterThan(0);
    expect(screen.getAllByText("换手率区间").length).toBeGreaterThan(0);
    expect(screen.getAllByText("前期涨幅区间").length).toBeGreaterThan(0);
    expect(screen.getAllByText("突破前高形态").length).toBeGreaterThan(0);
    expect(await screen.findByText("日线行情")).toBeInTheDocument();
  });

  it("lets the user adjust Chinese strategy parameters before running a backtest", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.clear(screen.getByLabelText("流通市值下限"));
    await user.type(screen.getByLabelText("流通市值下限"), "5000000000");
    await user.clear(screen.getByLabelText("量比下限"));
    await user.type(screen.getByLabelText("量比下限"), "1.2");
    await user.clear(screen.getByLabelText("初始资金"));
    await user.type(screen.getByLabelText("初始资金"), "250000");
    await user.click(screen.getByRole("button", { name: "运行历史回测" }));

    expect(await screen.findByText("交易次数 1")).toBeInTheDocument();
    expect(screen.getAllByText(/流通市值/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/主力净流入/).length).toBeGreaterThan(0);
    expect(screen.getByText(/2d 量比 1\.20 位于区间/)).toBeInTheDocument();
    expect(screen.getByText(/换手率 4\.00% 位于区间/)).toBeInTheDocument();
    expect(screen.getByText(/MACD柱线 0\.0310 >= 0\.0000/)).toBeInTheDocument();
    expect(screen.getByText(/5d 前期涨幅 8\.00% 位于区间/)).toBeInTheDocument();
    expect(screen.getByText(/收盘价 12\.00 突破前 20d 高点 11\.80/)).toBeInTheDocument();
    expect(screen.queryByText(/volume ratio|turnover|MACD histogram|return|prior high/)).not.toBeInTheDocument();
  });

  it("shows backend errors without dropping the page", async () => {
    const user = userEvent.setup();
    apiMocks.runConfiguredBacktest.mockRejectedValue(new Error("No cached daily bars found."));
    render(<App />);

    await user.click(screen.getByRole("button", { name: "运行历史回测" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("未找到已缓存的日线行情");
    expect(screen.getByRole("heading", { name: "策略条件" })).toBeInTheDocument();
  });

  it("uses a Chinese fallback for unrecognized backend errors", async () => {
    const user = userEvent.setup();
    apiMocks.runConfiguredBacktest.mockRejectedValue(new Error("initial_cash must be > 0"));
    render(<App />);

    await user.click(screen.getByRole("button", { name: "运行历史回测" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("回测参数不合法");
    expect(screen.queryByText(/initial_cash must be > 0/)).not.toBeInTheDocument();
  });
});
