import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DataCenter } from "./DataCenter";

const apiMocks = vi.hoisted(() => ({
  ensureDataService: vi.fn(),
  fetchDailyBars: vi.fn(),
  importDailyBars: vi.fn(),
  loadDataServiceHealth: vi.fn(),
  loadDataServiceLogs: vi.fn(),
  loadDailyBarsCoverage: vi.fn(),
  loadSyncJob: vi.fn(),
  startFullMarketSync: vi.fn()
}));

vi.mock("../api", () => apiMocks);

const coverage = [
  { dataset: "daily_bars", symbols: 1, start_date: "2024-01-02", end_date: "2024-01-03", missing_rows: 2 },
  { dataset: "capital_flow", symbols: 1, start_date: "2024-01-03", end_date: "2024-01-03", missing_rows: 1 }
];

describe("DataCenter", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    apiMocks.ensureDataService.mockResolvedValue({
      running: true,
      port: 9011,
      base_url: "http://127.0.0.1:9011",
      cache_dir: ".astock-cache",
      message: "local data service is ready"
    });
    apiMocks.loadDailyBarsCoverage.mockResolvedValue({
      summary: coverage,
      items: [
        {
          symbol: "600519",
          start_date: "2024-01-02",
          end_date: "2024-01-03",
          rows: 2,
          missing_trade_dates: ["2024-01-04"],
          missing_capital_flow_dates: ["2024-01-02"],
          missing_market_cap_dates: []
        }
      ]
    });
    apiMocks.loadDataServiceHealth.mockResolvedValue({
      ok: true,
      cache_path: "C:\\cache",
      port: 9011,
      coverage
    });
    apiMocks.loadDataServiceLogs.mockResolvedValue({ items: [] });
    apiMocks.fetchDailyBars.mockResolvedValue({
      status: "ok",
      imported_rows: 3,
      requested_symbols: ["600519"],
      fetched_symbols: ["600519"],
      missing_symbols: [],
      coverage,
      logs: [{ level: "info", message: "Fetched 3 daily bar rows" }]
    });
    apiMocks.importDailyBars.mockResolvedValue({
      status: "ok",
      imported_rows: 2,
      coverage,
      logs: [{ level: "info", message: "Imported daily bars from sample" }]
    });
    apiMocks.loadSyncJob.mockResolvedValue({
      job: {
        job_id: "job-1",
        mode: "full_market_bootstrap",
        status: "completed",
        total_symbols: 2,
        completed_symbols: 2,
        failed_symbols: 0,
        imported_rows: 20,
        current_symbol: null,
        start_date: "2015-01-01",
        end_date: "2026-05-26",
        errors: []
      }
    });
  });

  it("starts the managed service and refreshes daily-bar coverage", async () => {
    const onCoverageChange = vi.fn();
    render(<DataCenter cacheDir=".astock-cache" coverage={[]} onCoverageChange={onCoverageChange} />);

    expect(await screen.findByText(/http:\/\/127\.0\.0\.1:9011/)).toBeInTheDocument();
    expect(apiMocks.ensureDataService).toHaveBeenCalledWith(".astock-cache");
    expect(apiMocks.loadDataServiceHealth).toHaveBeenCalledWith("http://127.0.0.1:9011");
    expect(onCoverageChange).toHaveBeenCalledWith(coverage);
    expect(apiMocks.loadDailyBarsCoverage).toHaveBeenCalledWith(
      "http://127.0.0.1:9011",
      ["600519"],
      "2024-01-02",
      "2024-01-08"
    );
    expect(screen.getByText("600519")).toBeInTheDocument();
    expect(screen.getByText(/2024-01-04/)).toBeInTheDocument();
  });

  it("shows recent service logs when a fetch fails", async () => {
    const user = userEvent.setup();
    apiMocks.fetchDailyBars.mockRejectedValue(new Error("HTTP 400: request_failed - boom"));
    apiMocks.loadDataServiceLogs.mockResolvedValue({
      items: [
        { level: "error", message: "Baidu daily source returned malformed kline", timestamp: "2026-05-26T05:00:00Z" }
      ]
    });

    render(<DataCenter cacheDir=".astock-cache" coverage={coverage} onCoverageChange={vi.fn()} />);

    await screen.findByText(/http:\/\/127\.0\.0\.1:9011/);
    await user.click(screen.getByRole("button", { name: "补全缺失数据" }));

    expect(await screen.findByText(/Baidu daily source returned malformed kline/)).toBeInTheDocument();
  });

  it("fetches missing daily bars through the service and refreshes parent coverage", async () => {
    const user = userEvent.setup();
    const onCoverageChange = vi.fn();

    render(<DataCenter cacheDir=".astock-cache" coverage={coverage} onCoverageChange={onCoverageChange} />);

    await screen.findByText(/http:\/\/127\.0\.0\.1:9011/);
    await user.clear(screen.getByLabelText("股票代码"));
    await user.type(screen.getByLabelText("股票代码"), "600519 000001");
    await user.click(screen.getByRole("button", { name: "补全缺失数据" }));

    await waitFor(() => expect(apiMocks.fetchDailyBars).toHaveBeenCalledWith(
      "http://127.0.0.1:9011",
      ["600519", "000001"],
      "2024-01-02",
      "2024-01-08"
    ));
    expect(onCoverageChange).toHaveBeenCalledWith(coverage);
    expect(await screen.findByText("Fetched 3 daily bar rows")).toBeInTheDocument();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows immediate busy feedback for data operations", async () => {
    const user = userEvent.setup();
    let resolveFetch: (value: Awaited<ReturnType<typeof apiMocks.fetchDailyBars>>) => void = () => {};
    apiMocks.fetchDailyBars.mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve;
      })
    );

    render(<DataCenter cacheDir=".astock-cache" coverage={coverage} onCoverageChange={vi.fn()} />);

    await screen.findByText(/http:\/\/127\.0\.0\.1:9011/);
    await user.click(screen.getByRole("button", { name: "补全缺失数据" }));

    expect(screen.getByRole("button", { name: "正在补全缺失数据" })).toBeDisabled();
    expect(screen.getByRole("status", { name: "数据中心状态" })).toHaveTextContent("正在补全缺失数据");

    resolveFetch({
      status: "ok",
      imported_rows: 3,
      requested_symbols: ["600519"],
      fetched_symbols: ["600519"],
      missing_symbols: [],
      coverage,
      logs: [{ level: "info", message: "Fetched 3 daily bar rows" }]
    });

    expect(await screen.findByText("Fetched 3 daily bar rows")).toBeInTheDocument();
  });

  it("starts a full-market sync job and shows progress", async () => {
    const user = userEvent.setup();
    apiMocks.startFullMarketSync.mockResolvedValue({
      job: {
        job_id: "job-1",
        mode: "full_market_bootstrap",
        status: "running",
        total_symbols: 2,
        completed_symbols: 1,
        failed_symbols: 0,
        imported_rows: 10,
        current_symbol: "000002",
        start_date: "2015-01-01",
        end_date: "2026-05-26",
        errors: []
      }
    });

    render(<DataCenter cacheDir=".astock-cache" coverage={coverage} onCoverageChange={vi.fn()} />);

    await screen.findByText(/http:\/\/127\.0\.0\.1:9011/);
    await user.click(screen.getByRole("button", { name: "下载全市场历史数据" }));

    expect(screen.getByText(/当前 000002/)).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100);
    });
    await waitFor(() => expect(apiMocks.loadSyncJob).toHaveBeenCalledWith("http://127.0.0.1:9011", "job-1"));
    expect(await screen.findByText(/已完成 2\/2/)).toBeInTheDocument();
    expect(screen.getAllByText(/导入 20 行/).length).toBeGreaterThan(0);
  });
});
