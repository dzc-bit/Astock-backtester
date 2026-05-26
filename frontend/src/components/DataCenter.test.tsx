import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DataCenter } from "./DataCenter";

const apiMocks = vi.hoisted(() => ({
  ensureDataService: vi.fn(),
  fetchDailyBars: vi.fn(),
  importDailyBars: vi.fn(),
  loadDailyBarsCoverage: vi.fn()
}));

vi.mock("../api", () => apiMocks);

const coverage = [
  { dataset: "daily_bars", symbols: 1, start_date: "2024-01-02", end_date: "2024-01-03", missing_rows: 2 },
  { dataset: "capital_flow", symbols: 1, start_date: "2024-01-03", end_date: "2024-01-03", missing_rows: 1 }
];

describe("DataCenter", () => {
  beforeEach(() => {
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
  });

  it("starts the managed service and refreshes daily-bar coverage", async () => {
    render(<DataCenter cacheDir=".astock-cache" coverage={coverage} onRefresh={vi.fn()} />);

    expect(await screen.findByText(/http:\/\/127\.0\.0\.1:9011/)).toBeInTheDocument();
    expect(apiMocks.ensureDataService).toHaveBeenCalledWith(".astock-cache");
    expect(apiMocks.loadDailyBarsCoverage).toHaveBeenCalledWith(
      "http://127.0.0.1:9011",
      ["600519"],
      "2024-01-02",
      "2024-01-08"
    );
    expect(screen.getByText("600519")).toBeInTheDocument();
    expect(screen.getByText(/2024-01-04/)).toBeInTheDocument();
  });

  it("fetches missing daily bars through the service and refreshes parent coverage", async () => {
    const user = userEvent.setup();
    const onRefresh = vi.fn().mockResolvedValue(undefined);

    render(<DataCenter cacheDir=".astock-cache" coverage={coverage} onRefresh={onRefresh} />);

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
    expect(onRefresh).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("Fetched 3 daily bar rows")).toBeInTheDocument();
  });
});
