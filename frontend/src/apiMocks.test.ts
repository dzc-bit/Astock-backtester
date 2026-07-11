/**
 * Table-driven tests for browser preview mock functions in apiMocks.ts.
 *
 * These tests guard against behavioral drift when mock data is extracted
 * or reorganised.  They intentionally import from ``./apiMocks`` directly
 * (not from ``../api``) so that the mock logic can be verified in isolation.
 */

import { describe, expect, it } from "vitest";
import {
  mockConditionValidation,
  mockStockSymbolValidation,
  mockMarketBriefing,
  mockRealtimeMarketSnapshot,
  mockDataServiceHealth,
  mockDataServiceStatus,
  mockDataServiceLogs,
  mockMarketNews,
  mockClsFinance,
  mockNewsSummary,
  mockRiskAlerts,
  mockRecommendedStrategies,
  mockDailyBarsCoverage,
  mockFetchDailyBarsResult,
  mockFetchCapitalFlowResult,
  mockImportDailyBarsResult,
  mockStartFullMarketSync,
  mockLoadSyncJob,
  mockCancelSyncJob,
  mockCallBackendCoverage,
  demoBacktestResult,
} from "./apiMocks";
import type { ConditionValidationResult } from "./types";

// ---------------------------------------------------------------------------
// P1-1  mockConditionValidation — entry / exit parity & drift guard
// ---------------------------------------------------------------------------

describe("mockConditionValidation", () => {
  // The original inline mock in api.ts (before extraction) accepted
  // "收盘价站上20日均线" for BOTH entry and exit mode.  The exit-mode
  // conditions ("突破20日最低", "MACD死叉", etc.) were guarded by
  // `mode === "exit"`.  These tests enforce that contract.

  type Case = {
    text: string;
    mode: "entry" | "exit";
    expectedOk: boolean;
    expectedConditionId?: string;
  };

  const cases: Case[] = [
    // --- "收盘价站上20日均线" must work in BOTH modes (original behavior) ---
    { text: "收盘价站上20日均线", mode: "entry", expectedOk: true, expectedConditionId: "close_above_ma" },
    { text: "收盘价站上20日均线", mode: "exit", expectedOk: true, expectedConditionId: "close_above_ma" },

    // --- entry mode: unrecognised text returns ok=false ---
    { text: "随便写的条件", mode: "entry", expectedOk: false },
    { text: "", mode: "entry", expectedOk: false },
    { text: "   ", mode: "entry", expectedOk: false },

    // --- exit-mode specific conditions ---
    { text: "突破20日最低", mode: "exit", expectedOk: true, expectedConditionId: "breakdown_below_n_day_low" },
    { text: "跌破20日低点", mode: "exit", expectedOk: true, expectedConditionId: "breakdown_below_n_day_low" },
    { text: "近5日涨幅小于3%", mode: "exit", expectedOk: true, expectedConditionId: "past_return_at_most" },
    { text: "MACD死叉", mode: "exit", expectedOk: true, expectedConditionId: "macd_dead_cross" },
    { text: "资金流出", mode: "exit", expectedOk: true, expectedConditionId: "capital_flow_today_at_most" },
    { text: "近3日主力净流出", mode: "exit", expectedOk: true, expectedConditionId: "capital_flow_n_day_sum_at_most" },

    // --- exit-mode specific conditions should NOT match in entry mode ---
    { text: "突破20日最低", mode: "entry", expectedOk: false },
    { text: "MACD死叉", mode: "entry", expectedOk: false },
    { text: "资金流出", mode: "entry", expectedOk: false },
    { text: "近3日主力净流出", mode: "entry", expectedOk: false },
    { text: "近5日涨幅小于3%", mode: "entry", expectedOk: false },
    { text: "跌破20日低点", mode: "entry", expectedOk: false },

    // --- unrecognised exit text ---
    { text: "随便离场条件", mode: "exit", expectedOk: false },
    { text: "", mode: "exit", expectedOk: false },
  ];

  it.each(cases)(
    'text="$text" mode=$mode → ok=$expectedOk',
    ({ text, mode, expectedOk, expectedConditionId }) => {
      const result: ConditionValidationResult = mockConditionValidation(text, mode);
      expect(result.ok).toBe(expectedOk);
      expect(result.normalized_text).toBe(text.trim());
      if (expectedOk) {
        expect(result.condition).not.toBeNull();
        expect(result.condition!.condition_id).toBe(expectedConditionId);
        expect(result.errors).toHaveLength(0);
      } else {
        expect(result.condition).toBeNull();
        expect(result.errors.length).toBeGreaterThan(0);
        expect(result.errors[0].code).toBe("unrecognized_condition");
      }
    }
  );

  it("returns examples array in all cases", () => {
    for (const mode of ["entry", "exit"] as const) {
      const okResult = mockConditionValidation("收盘价站上20日均线", mode);
      expect(okResult.examples.length).toBeGreaterThan(0);
      const failResult = mockConditionValidation("zzz", mode);
      expect(failResult.examples.length).toBeGreaterThan(0);
    }
  });

  it("trims whitespace from input", () => {
    const result = mockConditionValidation("  收盘价站上20日均线  ", "entry");
    expect(result.ok).toBe(true);
    expect(result.normalized_text).toBe("收盘价站上20日均线");
  });
});

// ---------------------------------------------------------------------------
// mockStockSymbolValidation
// ---------------------------------------------------------------------------

describe("mockStockSymbolValidation", () => {
  it("accepts known symbols", () => {
    const result = mockStockSymbolValidation(["600519", "000001"]);
    expect(result.ok).toBe(true);
    expect(result.invalid_symbols).toHaveLength(0);
  });

  it("rejects unknown symbols", () => {
    const result = mockStockSymbolValidation(["999999"]);
    expect(result.ok).toBe(false);
    expect(result.invalid_symbols).toContain("999999");
  });

  it("handles empty input", () => {
    const result = mockStockSymbolValidation([]);
    expect(result.ok).toBe(true);
    expect(result.valid_symbols).toHaveLength(0);
  });

  it("trims whitespace", () => {
    const result = mockStockSymbolValidation([" 600519 ", " "]);
    expect(result.normalized_symbols).toEqual(["600519"]);
  });
});

// ---------------------------------------------------------------------------
// Other mock functions — shape & completeness guards
// ---------------------------------------------------------------------------

describe("mockMarketBriefing", () => {
  it("returns fupan shape", () => {
    const result = mockMarketBriefing("fupan");
    expect(result.kind).toBe("fupan");
    expect(result.source).toBe("browser-preview");
    expect(result.sections.length).toBeGreaterThan(0);
    expect(result.source_url).toContain("fupan");
  });

  it("returns zaopan shape", () => {
    const result = mockMarketBriefing("zaopan");
    expect(result.kind).toBe("zaopan");
    expect(result.source_url).toContain("zaopan");
  });
});

describe("mockRealtimeMarketSnapshot", () => {
  it("returns live status with breadth and sectors", () => {
    const snap = mockRealtimeMarketSnapshot();
    expect(snap.status).toBe("live");
    expect(snap.breadth).not.toBeNull();
    expect(snap.breadth!.total).toBeGreaterThan(0);
    expect(snap.strong_sectors.length).toBeGreaterThan(0);
    expect(snap.indexes.length).toBeGreaterThan(0);
  });
});

describe("mockDataServiceHealth", () => {
  it("returns ok with coverage array", () => {
    const health = mockDataServiceHealth();
    expect(health.ok).toBe(true);
    expect(health.coverage.length).toBeGreaterThan(0);
  });
});

describe("mockDataServiceStatus", () => {
  it("returns running status", () => {
    const status = mockDataServiceStatus("/tmp/test");
    expect(status.running).toBe(true);
    expect(status.cache_dir).toBe("/tmp/test");
  });
});

describe("mockDataServiceLogs", () => {
  it("returns items array", () => {
    const logs = mockDataServiceLogs();
    expect(logs.items.length).toBeGreaterThan(0);
    expect(logs.items[0].level).toBe("info");
  });
});

describe("mockMarketNews", () => {
  it("returns items with required fields", () => {
    const news = mockMarketNews();
    expect(news.items.length).toBeGreaterThan(0);
    expect(news.items[0].title).toBeTruthy();
  });
});

describe("mockClsFinance", () => {
  it("returns complete CLS finance data", () => {
    const data = mockClsFinance();
    expect(data.tline.length).toBeGreaterThan(0);
    expect(data.anchors.length).toBeGreaterThan(0);
    expect(data.emotion).toBeDefined();
    expect(data.up_pool.length).toBeGreaterThan(0);
  });
});

describe("mockNewsSummary", () => {
  it("returns themes and highlights", () => {
    const summary = mockNewsSummary();
    expect(summary.themes.length).toBeGreaterThan(0);
    expect(summary.highlights.length).toBeGreaterThan(0);
  });
});

describe("mockRiskAlerts", () => {
  it("returns items", () => {
    const alerts = mockRiskAlerts();
    expect(alerts.items.length).toBeGreaterThan(0);
    expect(alerts.items[0].severity).toBe("high");
  });
});

describe("mockRecommendedStrategies", () => {
  it("returns at least one strategy with conditions", () => {
    const result = mockRecommendedStrategies();
    expect(result.items.length).toBeGreaterThan(0);
    expect(result.items[0].strategy.entry_groups.length).toBeGreaterThan(0);
  });
});

describe("mockDailyBarsCoverage", () => {
  it("returns coverage for given symbols", () => {
    const result = mockDailyBarsCoverage(["600519", "000001"], "2024-01-01", "2024-01-10");
    expect(result.items).toHaveLength(2);
    expect(result.items[0].symbol).toBe("600519");
  });
});

describe("mockFetchDailyBarsResult", () => {
  it("returns ok status", () => {
    const result = mockFetchDailyBarsResult(["600519"], "2024-01-01", "2024-01-10");
    expect(result.status).toBe("ok");
    expect(result.imported_rows).toBe(5);
  });
});

describe("mockFetchCapitalFlowResult", () => {
  it("handles empty symbols", () => {
    const result = mockFetchCapitalFlowResult([], "2024-01-01", "2024-01-10");
    expect(result.status).toBe("ok");
    expect(result.imported_rows).toBe(0);
    expect(result.job).toBeDefined();
  });

  it("handles non-empty symbols", () => {
    const result = mockFetchCapitalFlowResult(["600519"], "2024-01-01", "2024-01-10");
    expect(result.status).toBe("ok");
    expect(result.imported_rows).toBe(1);
  });
});

describe("mockImportDailyBarsResult", () => {
  it("returns sample source", () => {
    const result = mockImportDailyBarsResult("sample");
    expect(result.status).toBe("ok");
    expect(result.logs[0].message).toContain("sample");
  });

  it("returns file source with path", () => {
    const result = mockImportDailyBarsResult("file", "/tmp/data.csv");
    expect(result.logs[0].message).toContain("/tmp/data.csv");
  });
});

describe("mockStartFullMarketSync", () => {
  it("returns completed job", () => {
    const result = mockStartFullMarketSync("2024-01-01", "2024-12-31");
    expect(result.job.status).toBe("completed");
  });
});

describe("mockLoadSyncJob", () => {
  it("returns job with given id", () => {
    const result = mockLoadSyncJob("test-123");
    expect(result.job.job_id).toBe("test-123");
  });
});

describe("mockCancelSyncJob", () => {
  it("returns cancelled status", () => {
    const result = mockCancelSyncJob("test-123");
    expect(result.job.status).toBe("cancelled");
  });
});

describe("mockCallBackendCoverage", () => {
  it("returns coverage array", () => {
    const result = mockCallBackendCoverage();
    expect(result.coverage.length).toBeGreaterThan(0);
  });
});

describe("demoBacktestResult", () => {
  it("has required fields", () => {
    expect(demoBacktestResult.metrics).toBeDefined();
    expect(demoBacktestResult.trades.length).toBeGreaterThan(0);
    expect(demoBacktestResult.equity_curve.length).toBeGreaterThan(0);
    expect(demoBacktestResult.latest_strategy_matches).toBeDefined();
  });
});
